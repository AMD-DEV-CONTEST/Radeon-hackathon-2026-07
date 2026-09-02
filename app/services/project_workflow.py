"""Registered, project-scoped tools for the fixed RAG-to-report workflow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable

from app.agent.runner import RunContext, Tool
from app.config import Settings
from app.rag.indexer import ProjectIndex
from app.rag.manifest import ParsedDocument
from app.rag.parsers import import_project
from app.rag.retriever import Retriever
from app.schemas import Evidence, ReportDraft, Task, TaskEvaluation
from app.security.paths import ensure_project_path
from app.services.phase_c import evaluate_tasks, evaluate_tasks_with_llm, load_tasks, render_report_bundle


@dataclass
class WorkflowArtifacts:
    import_success_count: int = 0
    chunk_count: int = 0
    parsed_documents: list[ParsedDocument] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    evidence_by_task: dict[str, list[Evidence]] = field(default_factory=dict)
    evaluations: list[TaskEvaluation] = field(default_factory=list)
    report: ReportDraft | None = None
    report_relative_path: str | None = None
    risk_relative_path: str | None = None
    plan_relative_path: str | None = None
    result_relative_path: str | None = None

    def summary(self) -> dict[str, str]:
        return {
            "imported_files": str(self.import_success_count),
            "indexed_chunks": str(self.chunk_count),
            "tasks_evaluated": str(len(self.evaluations)),
            **({"report": self.report_relative_path} if self.report_relative_path else {}),
            **({"risk_csv": self.risk_relative_path} if self.risk_relative_path else {}),
            **({"next_week_plan": self.plan_relative_path} if self.plan_relative_path else {}),
            **({"result": self.result_relative_path} if self.result_relative_path else {}),
        }


IndexFactory = Callable[[str, Settings], ProjectIndex]


def build_project_report_tools(
    settings: Settings,
    *,
    index_factory: IndexFactory | None = None,
    use_llm: bool = True,
    retrieval_min_score: float = 0.35,
) -> tuple[dict[str, Tool], WorkflowArtifacts]:
    """Build the only tool registry accepted by the production report runner."""
    artifacts = WorkflowArtifacts()
    indexes: dict[str, ProjectIndex] = {}

    def scan(context: RunContext) -> dict[str, Any]:
        result = import_project(context.project_id, project_root=settings.project_root)
        if not result.parsed:
            raise ValueError("no parseable source documents found")
        artifacts.import_success_count = result.success_count
        artifacts.parsed_documents = result.parsed
        return {"success_count": result.success_count, "failure_count": result.failure_count}

    def index(context: RunContext) -> dict[str, Any]:
        factory = index_factory or (lambda project_id, runtime: ProjectIndex(project_id, runtime))
        project_index = factory(context.project_id, settings)
        artifacts.chunk_count = project_index.index(artifacts.parsed_documents)
        project_index.save()
        indexes[context.project_id] = project_index
        return {"chunk_count": artifacts.chunk_count}

    def retrieve(context: RunContext) -> dict[str, Any]:
        project_index = indexes.get(context.project_id)
        if project_index is None:
            raise RuntimeError("project index is unavailable")
        artifacts.tasks = load_tasks(context.project_id, settings=settings)
        retriever = Retriever(project_index)
        artifacts.evidence_by_task = {
            task.task_id: retriever.search(_task_query(task), min_score=retrieval_min_score)
            for task in artifacts.tasks
        }
        evidence_count = sum(len(items) for items in artifacts.evidence_by_task.values())
        return {"task_count": len(artifacts.tasks), "evidence_count": evidence_count}

    def evaluate(context: RunContext) -> dict[str, Any]:
        if use_llm:
            artifacts.evaluations = asyncio.run(
                evaluate_tasks_with_llm(
                    artifacts.tasks, artifacts.evidence_by_task, settings, project_id=context.project_id
                )
            )
        else:
            artifacts.evaluations = evaluate_tasks(artifacts.tasks, artifacts.evidence_by_task)
        return {"evaluation_count": len(artifacts.evaluations)}

    def draft(context: RunContext) -> dict[str, Any]:
        bundle = render_report_bundle(context.project_id, artifacts.tasks, artifacts.evaluations)
        artifacts.report = ReportDraft(
            project_id=context.project_id,
            markdown=bundle.markdown,
            evaluations=artifacts.evaluations,
        )
        report_path = ensure_project_path(
            settings.output_root, context.project_id, "reports", f"{context.run_id}.md"
        )
        risk_path = ensure_project_path(
            settings.output_root, context.project_id, "risks", f"{context.run_id}.csv"
        )
        plan_path = ensure_project_path(
            settings.output_root, context.project_id, "plans", f"{context.run_id}.md"
        )
        result_path = ensure_project_path(
            settings.output_root, context.project_id, "results", f"{context.run_id}.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        risk_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(artifacts.report.markdown, encoding="utf-8")
        risk_path.write_text(bundle.risk_csv, encoding="utf-8", newline="")
        plan_path.write_text(bundle.next_week_plan, encoding="utf-8")
        result_path.write_text(
            json.dumps(
                {"project_id": context.project_id, "run_id": context.run_id, "evaluations": [item.model_dump(mode="json") for item in artifacts.evaluations]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        artifacts.report_relative_path = f"reports/{context.run_id}.md"
        artifacts.risk_relative_path = f"risks/{context.run_id}.csv"
        artifacts.plan_relative_path = f"plans/{context.run_id}.md"
        artifacts.result_relative_path = f"results/{context.run_id}.json"
        return {
            "report": artifacts.report_relative_path,
            "risk_csv": artifacts.risk_relative_path,
            "next_week_plan": artifacts.plan_relative_path,
            "result": artifacts.result_relative_path,
        }

    return {"scan": scan, "index": index, "retrieve": retrieve, "evaluate": evaluate, "draft": draft}, artifacts


def _task_query(task: Task) -> str:
    parts = [task.title]
    if task.acceptance_criteria:
        parts.append(task.acceptance_criteria)
    return " ".join(parts)
