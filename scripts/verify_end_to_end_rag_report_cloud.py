"""Cloud verification of the controlled RAG-to-report run using live model services."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from app.config import Settings
from app.llm.client import LLMClient
from app.schemas import ProjectCreate, RunStatus
from app.services.projects import create_project, project_paths
from app.services.runs import create_run, execute_project_report_run


def main() -> int:
    base_settings = Settings()
    settings = Settings(llm_timeout_seconds=max(base_settings.llm_timeout_seconds, 90))
    direct_reply = asyncio.run(
        LLMClient(settings).generate_text("Reply with exactly END_TO_END_OK.", temperature=0)
    )
    if not direct_reply.strip():
        raise AssertionError("chat service returned an empty direct response")

    project_id = "rag-report-smoke-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    project = create_project(
        settings.project_root,
        settings.output_root,
        ProjectCreate(project_id=project_id, name="RAG report cloud smoke test"),
    )
    source_dir = project_paths(settings.project_root, settings.output_root, project.project_id)["source"]
    (source_dir / "tasks.csv").write_text(
        "title,assignee,deadline,priority,acceptance_criteria,original_source\n"
        "API verification,Ada,2026-12-31,high,test report,cloud smoke fixture\n",
        encoding="utf-8",
    )
    (source_dir / "status.md").write_text(
        "# API verification\n"
        "API verification is completed. The test report is available and approved.\n",
        encoding="utf-8",
    )

    queued = create_run(settings, project_id)
    result = execute_project_report_run(settings, project_id, queued.run_id)
    if result.status is not RunStatus.COMPLETED:
        raise AssertionError(f"workflow failed: {result.error}")
    report_relative_path = result.artifacts.get("report")
    risk_relative_path = result.artifacts.get("risk_csv")
    plan_relative_path = result.artifacts.get("next_week_plan")
    result_relative_path = result.artifacts.get("result")
    if not all((report_relative_path, risk_relative_path, plan_relative_path, result_relative_path)):
        raise AssertionError("completed workflow is missing one or more report artifacts")
    report_path = settings.output_root / project_id / report_relative_path
    risk_path = settings.output_root / project_id / risk_relative_path
    plan_path = settings.output_root / project_id / plan_relative_path
    result_path = settings.output_root / project_id / result_relative_path
    report = report_path.read_text(encoding="utf-8")
    if "status.md" not in report:
        raise AssertionError("report did not retain retrieved source citation")
    if not risk_path.is_file() or not plan_path.is_file() or not result_path.is_file():
        raise AssertionError("one or more report artifact files were not written")

    print(
        json.dumps(
            {
                "result": "passed",
                "project_id": project_id,
                "run_id": result.run_id,
                "status": result.status.value,
                "artifacts": result.artifacts,
                "direct_chat_response_length": len(direct_reply),
                "report_has_status_citation": "status.md" in report,
                "has_risk_csv": risk_path.is_file(),
                "has_next_week_plan": plan_path.is_file(),
                "has_structured_result": result_path.is_file(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
