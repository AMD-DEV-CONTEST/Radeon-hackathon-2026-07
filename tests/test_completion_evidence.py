import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from buildguard.agent.nodes.response import generate_response
from buildguard.config import AdvancedRagConfig, RetentionConfig, load_settings
from buildguard.evaluation.ablation import (
    REQUIRED_GROUPS,
    MeasuredAblationRun,
    build_ablation_report,
)
from buildguard.llm.base import ChatMessage
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.llm.openai_compatible import OpenAICompatibleLocalBackend
from buildguard.rag.advanced.answer_grounding import AnswerGrounder
from buildguard.scheduling.runtime_gate import ModelResidencyRegistry
from buildguard.schemas.tools import ToolCallResult
from buildguard.workspace.manager import WorkspaceManager
from buildguard.workspace.retention import RetentionCleaner
from buildguard.workspace.retention_loop import RetentionLoop


def test_agent_rag_response_is_forced_through_grounding_refusal() -> None:
    state = {
        "intent": None,
        "user_query": "unsupported question",
        "tool_results": [
            ToolCallResult(
                call_id="rag-call",
                success=True,
                output={"chunks": [], "evidence_status": "insufficient_evidence"},
                duration_ms=1,
            )
        ],
        "memory_messages": [],
        "performance_trace": [],
    }
    config = AdvancedRagConfig(refusal_message="insufficient local evidence")

    result = generate_response(
        state,  # type: ignore[arg-type]
        MockLLMBackend(),
        AnswerGrounder(config),
    )

    assert result["final_response"] == "insufficient local evidence"
    assert result["grounding_result"] is not None


def test_complete_chat_stream_measures_real_ttft(config_tree: Path) -> None:
    settings = load_settings(config_tree)
    settings.llm.mode = "local"
    settings.llm.stream_complete_responses = True

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.read().find(b'"stream":true') >= 0
        body = (
            'data: {"choices":[{"delta":{"content":"ready"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body)

    backend = OpenAICompatibleLocalBackend(
        settings.llm,
        settings.permissions,
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = backend.chat([ChatMessage(role="user", content="measure")])

    assert response.content == "ready"
    assert response.metrics.ttft_seconds is not None
    assert response.metrics.ttft_seconds <= response.metrics.total_seconds


def test_residency_registry_preserves_pinned_model_identity() -> None:
    registry = ModelResidencyRegistry()
    registry.register("llm:qwen", 16_000)
    registry.register("vision:ppe", 4096)
    models, pinned = registry.snapshot()
    registry.unregister("vision:ppe")

    assert models == {"llm:qwen": 16_000, "vision:ppe": 4096}
    assert pinned == set(models)
    assert registry.snapshot() == ({"llm:qwen": 16_000}, {"llm:qwen"})


def test_retention_loop_enforces_enabled_policy_once(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspace")
    paths = manager.initialize()
    old = paths["events/clips"] / "old.mp4"
    old.write_bytes(b"video")
    timestamp = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(old, (timestamp, timestamp))
    loop = RetentionLoop(
        RetentionCleaner(
            manager,
            RetentionConfig(enabled=True, event_clips_days=14),
        ),
        3600,
    )

    result = loop.run_once()

    assert old.resolve() in result.deleted
    assert not old.exists()


def test_ablation_report_rejects_missing_runs_and_accepts_complete_measured_suite() -> None:
    started = datetime(2026, 1, 1, tzinfo=UTC)
    runs: list[MeasuredAblationRun] = []
    for group, (_, variants, required_metrics) in REQUIRED_GROUPS.items():
        for index, variant in enumerate(variants):
            runs.append(
                MeasuredAblationRun(
                    group=group,
                    variant=variant,
                    status="PASS",
                    source="measured",
                    mock=False,
                    dataset_sha256="a" * 64,
                    code_revision="abcdef1234567",
                    configuration_sha256=f"{index + 1:064x}",
                    host="amd-test",
                    gpu_name="AMD Radeon",
                    rocm_version="7.2.1",
                    started_at=started,
                    finished_at=started + timedelta(seconds=1),
                    sample_count=10,
                    metrics={key: float(index + 1) for key in required_metrics},
                    artifact_paths=[Path(f"{group}-{variant}.json")],
                    artifact_sha256={f"{group}-{variant}.json": "b" * 64},
                )
            )

    assert build_ablation_report(runs[:-1]).status == "INCOMPLETE"
    report = build_ablation_report(runs)
    assert report.status == "PASS"
    assert report.measured_only is True
    assert all(group.complete for group in report.groups)
