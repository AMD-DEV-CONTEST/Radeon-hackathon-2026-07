import json
from pathlib import Path

import orjson
from typer.testing import CliRunner

from buildguard.cli import app
from buildguard.config import Settings, load_settings
from buildguard.evaluation.competition_readiness import (
    CompetitionReadinessChecker,
)
from buildguard.system.runtime_info import Availability, RuntimeInfo


def _runtime(*, healthy: bool = True, gpu: bool = True) -> RuntimeInfo:
    return RuntimeInfo(
        operating_system="test",
        python_version="3.12",
        cpu_count=8,
        memory_total_mb=32_768,
        commands={},
        llm_endpoint=Availability(available=healthy),
        amd_gpu_detected=gpu,
        rocm_version="7.2.1" if gpu else None,
    )


def _write_cases(path: Path, count: int) -> Path:
    path.write_bytes(orjson.dumps([{"case_id": str(index)} for index in range(count)]))
    return path


def _agent_settings(config_tree: Path, tmp_path: Path) -> Settings:
    settings = load_settings(config_tree)
    return settings.model_copy(
        update={
            "llm": settings.llm.model_copy(update={"mode": "local"}),
            "evaluation": settings.evaluation.model_copy(
                update={"agent_dataset_path": _write_cases(tmp_path / "agent.json", 2)}
            ),
            "competition": settings.competition.model_copy(
                update={
                    "agent_min_cases": 2,
                    "knowledge_dir": tmp_path / "knowledge",
                    "ppe_dataset_dir": tmp_path / "ppe",
                    "rag_manifest_path": tmp_path / "manifest.json",
                }
            ),
        }
    )


def test_agent_level_ignores_missing_rag_and_vision(
    config_tree: Path, tmp_path: Path
) -> None:
    report = CompetitionReadinessChecker(
        _agent_settings(config_tree, tmp_path), _runtime()
    ).run("agent")

    assert report.agent_ready is True
    assert report.rag_ready is False
    assert report.vision_ready is False
    assert report.ready_for("agent") is True
    assert {check.scope for check in report.checks} == {"agent"}


def test_agent_level_rejects_mock_unhealthy_or_missing_gpu(
    config_tree: Path, tmp_path: Path
) -> None:
    settings = _agent_settings(config_tree, tmp_path)
    mock_settings = settings.model_copy(
        update={"llm": settings.llm.model_copy(update={"mode": "mock"})}
    )

    mock_report = CompetitionReadinessChecker(mock_settings, _runtime()).run("agent")
    runtime_report = CompetitionReadinessChecker(
        settings, _runtime(healthy=False, gpu=False)
    ).run("agent")

    assert mock_report.agent_ready is False
    assert runtime_report.agent_ready is False
    failed_names = {
        check.name for check in runtime_report.checks if check.status == "failed"
    }
    assert failed_names == {"local_llm_health", "rocm_gpu"}


def test_rag_level_requires_real_models_documents_index_and_cases(
    config_tree: Path, tmp_path: Path
) -> None:
    settings = _agent_settings(config_tree, tmp_path)
    embedding = tmp_path / "embedding"
    reranker = tmp_path / "reranker"
    knowledge = tmp_path / "knowledge"
    manifest = tmp_path / "manifest.json"
    for directory in (embedding, reranker, knowledge):
        directory.mkdir()
    embedding_manifest = embedding / "model-manifest.json"
    reranker_manifest = reranker / "model-manifest.json"
    model_digest = "a" * 64
    for model_manifest in (embedding_manifest, reranker_manifest):
        model_manifest.write_text(
            json.dumps(
                {"revision": "immutable-test-revision", "model_sha256": model_digest}
            ),
            encoding="utf-8",
        )
    (knowledge / "standard.md").write_text("authorized standard", encoding="utf-8")
    manifest.write_text("{}", encoding="utf-8")
    rag_cases = _write_cases(tmp_path / "rag.json", 3)
    settings = settings.model_copy(
        update={
            "rag": settings.rag.model_copy(
                update={
                    "embedding_mode": "transformers",
                        "embedding_model_path": embedding,
                        "embedding_manifest_path": embedding_manifest,
                        "embedding_model_revision": "immutable-test-revision",
                        "embedding_model_sha256": model_digest,
                        "reranker_mode": "transformers",
                        "reranker_model_path": reranker,
                        "reranker_manifest_path": reranker_manifest,
                        "reranker_model_revision": "immutable-test-revision",
                        "reranker_model_sha256": model_digest,
                    "reranker_enabled": True,
                }
            ),
            "evaluation": settings.evaluation.model_copy(
                update={
                    "agent_dataset_path": settings.evaluation.agent_dataset_path,
                    "rag_dataset_path": rag_cases,
                }
            ),
            "competition": settings.competition.model_copy(
                update={
                    "rag_min_cases": 3,
                    "knowledge_dir": knowledge,
                    "rag_manifest_path": manifest,
                }
            ),
        }
    )

    report = CompetitionReadinessChecker(settings, _runtime()).run("rag")

    assert report.rag_ready is True
    assert report.full_competition_ready is False
    assert report.ready_for("rag") is True
    assert {check.scope for check in report.checks} == {"rag"}


def test_competition_check_rejects_unknown_level(config_tree: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["competition-check", "--config", str(config_tree), "--level", "unknown"],
    )

    assert result.exit_code == 2
