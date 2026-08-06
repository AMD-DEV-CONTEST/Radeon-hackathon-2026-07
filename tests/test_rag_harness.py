import json
from pathlib import Path

from buildguard.config import load_settings
from buildguard.evaluation.rag_harness import RagEvaluationHarness
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.rag.service import create_rag_service


def test_rag_harness_measures_refusal_and_resumes(
    config_tree: Path, tmp_path: Path
) -> None:
    settings = load_settings(config_tree)
    workspace = tmp_path / "workspace"
    settings = settings.model_copy(
        update={
            "app": settings.app.model_copy(
                update={
                    "workspace_dir": workspace,
                    "database_path": workspace / "database" / "buildguard.db",
                }
            ),
            "rag": settings.rag.model_copy(
                update={"index_dir": workspace / "indexes" / "standards"}
            ),
        }
    )
    cases = tmp_path / "rag.jsonl"
    cases.write_text(
        json.dumps(
            {
                "case_id": "refusal",
                "question": "What does the missing local standard require?",
                "answerable": False,
                "relevant_chunk_ids": [],
                "forbidden_outdated_sources": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "results.jsonl"
    harness = RagEvaluationHarness(
        settings, create_rag_service(settings), MockLLMBackend()
    )

    first = harness.run(cases, output)
    second = harness.run(cases, output)

    assert first.succeeded_cases == 1
    assert first.failed_cases == 0
    assert second.executed_cases == 0
    assert second.resumed_cases == 1
