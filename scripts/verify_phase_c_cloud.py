"""Non-destructive cloud smoke test for Phase C contracts and real LLM explanation."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from app.config import Settings
from app.llm.client import LLMClient
from app.reports.generator import evaluate_with_llm, evaluate_with_rules
from app.schemas import Evidence
from app.services.phase_c import evaluate_tasks, load_tasks, render_reports
from app.services.projects import create_project, project_paths
from app.schemas import ProjectCreate
from app.tools.task_reader import TaskRecord


def main() -> int:
    settings = Settings()
    llm_settings = Settings(llm_timeout_seconds=max(settings.llm_timeout_seconds, 90))
    project_id = "phase-c-smoke-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    project = create_project(
        settings.project_root,
        settings.output_root,
        ProjectCreate(project_id=project_id, name="Phase C cloud smoke test"),
    )
    source_dir = project_paths(settings.project_root, settings.output_root, project.project_id)["source"]
    (source_dir / "tasks.csv").write_text(
        "title,assignee,deadline,priority,acceptance_criteria,original_source\n"
        "Cloud report verification,Ada,2026-12-31,high,test report,cloud smoke fixture\n",
        encoding="utf-8",
    )

    tasks = load_tasks(project_id, settings=settings)
    if len(tasks) != 1:
        raise AssertionError(f"expected one task, got {len(tasks)}")
    evidence = Evidence(
        evidence_id="cloud-evidence-1",
        relative_path="source/status.md",
        locator="## Verification",
        excerpt="Cloud report verification is completed and the test report is available.",
        score=0.95,
    )
    evaluations = evaluate_tasks(tasks, {tasks[0].task_id: [evidence]})
    draft = render_reports(project_id, evaluations)
    if evidence.relative_path not in draft.markdown:
        raise AssertionError("report draft did not retain the evidence citation")

    record = TaskRecord(
        title=tasks[0].title,
        assignee=tasks[0].owner or "unassigned",
        deadline=tasks[0].due_date.isoformat() if tasks[0].due_date else "",
        priority=tasks[0].priority or "normal",
        acceptance_criteria=tasks[0].acceptance_criteria or "",
        original_source=tasks[0].source_reference or "",
    )
    rule_only = evaluate_with_rules(record, [evidence.excerpt])
    llm_client = LLMClient(llm_settings)
    direct_response = asyncio.run(
        llm_client.generate_text("Reply with exactly PHASE_C_LLM_OK.", temperature=0)
    )
    if not direct_response.strip():
        raise AssertionError("chat model returned an empty smoke-test response")
    llm_evaluation = asyncio.run(evaluate_with_llm(record, [evidence.excerpt], llm_client))
    if llm_evaluation.status != rule_only.status:
        raise AssertionError("LLM explanation changed the rule-owned task status")

    print(
        json.dumps(
            {
                "result": "passed",
                "project_id": project_id,
                "task_count": len(tasks),
                "rule_status": rule_only.status.value,
                "llm_status": llm_evaluation.status.value,
                "citation_retained": evidence.relative_path in draft.markdown,
                "direct_llm_response_length": len(direct_response),
                "llm_explanation_length": len(llm_evaluation.evidence_summary),
                "llm_explanation_applied": llm_evaluation.evidence_summary != rule_only.evidence_summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
