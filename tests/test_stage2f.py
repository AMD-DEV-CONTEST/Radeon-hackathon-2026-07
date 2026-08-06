from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from buildguard.config import EvaluationConfig, load_settings
from buildguard.evaluation.agent_metrics import (
    AgentEvaluationCase,
    evaluate_agent,
)
from buildguard.evaluation.experiment_runner import (
    BenchmarkSuiteReport,
    ExperimentRunner,
    StabilityCheck,
)
from buildguard.evaluation.rag_metrics import RagEvaluationCase, evaluate_rag
from buildguard.evaluation.realtime_metrics import (
    RealtimeEvaluationCase,
    evaluate_realtime,
)
from buildguard.evaluation.report import export_competition_archive, export_report
from buildguard.evaluation.rocm_benchmark import (
    RocmBenchmarkRecord,
    RocmBenchmarkRunner,
)
from buildguard.evaluation.security_metrics import (
    SecurityEvaluationCase,
    evaluate_security,
)
from buildguard.evaluation.vision_metrics import (
    VisionEvaluationCase,
    VisionPrediction,
    evaluate_vision,
)
from buildguard.exceptions import ConfigurationError
from buildguard.llm.mock_backend import MockLLMBackend
from buildguard.monitoring.base import GPUStats, HardwareSnapshot


class _SnapshotMonitor:
    def __init__(self, *, with_gpu: bool) -> None:
        self.with_gpu = with_gpu

    def snapshot(self) -> HardwareSnapshot:
        return HardwareSnapshot(
            source="test-monitor",
            gpus=[GPUStats(name="Radeon Test GPU")] if self.with_gpu else [],
        )


def test_agent_metrics_and_validation() -> None:
    metrics = evaluate_agent(
        [
            AgentEvaluationCase(
                case_id="success",
                task_succeeded=True,
                expected_tools=["inspect"],
                selected_tools=["inspect"],
                expected_arguments=[{"path": "image.png"}],
                actual_arguments=[{"path": "image.png"}],
                planned_steps=2,
                completed_steps=2,
                multi_turn=True,
                multi_turn_succeeded=True,
            ),
            AgentEvaluationCase(
                case_id="failure",
                task_succeeded=False,
                expected_tools=["rag"],
                selected_tools=["inspect"],
                expected_arguments=[{"query": "helmet"}],
                actual_arguments=[{"path": "wrong.png"}],
                planned_steps=2,
                completed_steps=1,
                replan_required=True,
                replan_succeeded=False,
            ),
        ]
    )
    assert metrics.task_success_rate == 0.5
    assert metrics.tool_selection_accuracy == 0.5
    assert metrics.argument_accuracy == 0.5
    assert metrics.plan_completion == 0.75
    assert metrics.replan_success == 0
    assert metrics.multi_turn_success == 1
    with pytest.raises(ValidationError, match="cannot exceed"):
        AgentEvaluationCase(
            case_id="invalid",
            task_succeeded=False,
            planned_steps=1,
            completed_steps=2,
        )


def test_rag_metrics_exclude_refusal_from_retrieval_denominator() -> None:
    metrics = evaluate_rag(
        [
            RagEvaluationCase(
                case_id="retrieval",
                relevant_chunk_ids=["a", "b"],
                retrieved_chunk_ids=["a", "x", "b"],
                citation_supported=[True, False],
                claim_supported=[True, False],
            ),
            RagEvaluationCase(
                case_id="refusal",
                expected_refusal=True,
                actual_refusal=True,
            ),
        ]
    )
    assert metrics.recall_at_5 == 1
    assert metrics.recall_at_10 == 1
    assert metrics.mrr == 1
    assert metrics.citation_accuracy == 0.5
    assert metrics.unsupported_claim_rate == 0.5
    assert metrics.refusal_accuracy == 1


def test_vision_metrics_and_real_fps() -> None:
    metrics = evaluate_vision(
        [
            VisionEvaluationCase(
                case_id="vision",
                ground_truth_labels=["helmet", "edge"],
                high_risk_labels=["edge"],
                predictions=[
                    VisionPrediction(label="helmet", confidence=0.9, matched=True),
                    VisionPrediction(label="edge", confidence=0.8, matched=False),
                ],
                model_calls=1,
                full_model_calls=2,
                latency_ms=25,
                vram_mb=512,
                processed_frames=10,
                elapsed_seconds=2,
            )
        ]
    )
    assert metrics.recall == 0.5
    assert metrics.high_risk_recall == 0
    assert metrics.reduction_rate == 0.5
    assert metrics.average_latency_ms == 25
    assert metrics.peak_vram_mb == 512
    assert metrics.fps == 5


def test_realtime_metrics_and_length_validation() -> None:
    metrics = evaluate_realtime(
        [
            RealtimeEvaluationCase(
                case_id="video",
                frame_ground_truth=[False, False, True],
                frame_predictions=[True, False, True],
                ground_truth_event_ids=["a", "b"],
                detected_event_ids=["a"],
                emitted_event_ids=["a", "a", "extra"],
                confirmation_latencies_ms=[100, 300],
                reconnect_times_seconds=[2],
                observed_seconds=100,
            )
        ]
    )
    assert metrics.frame_false_positive_rate == 0.5
    assert metrics.event_false_positive_rate == 0.5
    assert metrics.event_miss_rate == 0.5
    assert metrics.duplicate_event_rate == pytest.approx(1 / 3)
    assert metrics.average_confirmation_latency_ms == 200
    assert metrics.average_reconnect_time_seconds == 2
    assert metrics.continuous_stability == 1
    with pytest.raises(ValidationError, match="equal length"):
        RealtimeEvaluationCase(
            case_id="invalid",
            frame_ground_truth=[True],
            frame_predictions=[],
        )


def test_security_metrics_count_attempts_without_claiming_leakage() -> None:
    metrics = evaluate_security(
        [
            SecurityEvaluationCase(
                case_id="blocked",
                attack=True,
                expected_allowed=False,
                actual_allowed=False,
                unauthorized_access_attempt=True,
            ),
            SecurityEvaluationCase(
                case_id="normal",
                attack=False,
                expected_allowed=True,
                actual_allowed=True,
            ),
        ]
    )
    assert metrics.attack_success_rate == 0
    assert metrics.false_blocking_rate == 0
    assert metrics.unauthorized_access == 1
    assert metrics.sensitive_leakage == 0


def test_experiment_runner_marks_mock_and_fixtures_not_competition_ready(
    config_tree: Path,
    tmp_path: Path,
) -> None:
    settings = load_settings(config_tree)
    workspace = tmp_path / "workspace"
    settings.app.workspace_dir = workspace
    settings.evaluation = EvaluationConfig(output_dir=workspace / "evaluation")
    report = ExperimentRunner(
        settings,
        MockLLMBackend(seed=settings.app.seed),
    ).run()
    assert report.status == "completed_with_unavailable_resources"
    assert report.mock_only
    assert not report.competition_ready
    assert set(report.metrics) == {
        "agent",
        "rag",
        "vision",
        "realtime",
        "security",
    }
    assert all(item.status == "mock_validation" for item in report.rocm)
    tool_check = next(
        item for item in report.stability if item.name == "50-tool-tasks"
    )
    assert tool_check.status == "validated"
    assert tool_check.completed_iterations == 50
    assert report.json_path is not None and report.json_path.is_file()
    assert report.markdown_path is not None and report.markdown_path.is_file()
    persisted = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert persisted["mock_only"] is True
    assert "not competition results" in " ".join(persisted["warnings"])
    stability = ExperimentRunner(
        settings,
        MockLLMBackend(seed=settings.app.seed),
    ).run_tool_stability(3)
    assert stability.status == "validated"
    assert stability.completed_iterations == 3
    audit_lines = (
        settings.evaluation.output_dir
        / "tool-stability-audit.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 53


def test_rocm_benchmark_requires_real_gpu_telemetry_and_labels(
    config_tree: Path,
) -> None:
    settings = load_settings(config_tree)
    settings.llm.mode = "local"
    settings.evaluation.active_quantization = "Q4_K_M"
    settings.evaluation.prefix_cache_enabled = True
    settings.evaluation.context_compression_enabled = False
    settings.evaluation.model_residency = "on_demand"
    settings.evaluation.rgc_enabled = True
    runner = RocmBenchmarkRunner(settings, MockLLMBackend())
    runner.monitor = _SnapshotMonitor(with_gpu=False)  # type: ignore[assignment]
    no_gpu = runner.run_mode("non-thinking")
    assert no_gpu.status == "unavailable"
    assert no_gpu.reason is not None and "Radeon GPU telemetry" in no_gpu.reason

    settings.evaluation.active_quantization = "unreported"
    runner.monitor = _SnapshotMonitor(with_gpu=True)  # type: ignore[assignment]
    missing_label = runner.run_mode("thinking")
    assert missing_label.status == "unavailable"
    assert missing_label.reason is not None
    assert "active_quantization" in missing_label.reason


def test_failed_stability_check_fails_suite(
    config_tree: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(config_tree)
    settings.app.workspace_dir = tmp_path / "workspace"
    settings.evaluation = EvaluationConfig(
        output_dir=settings.app.workspace_dir / "evaluation"
    )
    runner = ExperimentRunner(settings, MockLLMBackend())
    failed = StabilityCheck(
        name="50-tool-tasks",
        status="failed",
        requested_iterations=50,
        completed_iterations=2,
        reason="injected isolated tool failure",
    )
    monkeypatch.setattr(runner, "run_tool_stability", lambda _iterations: failed)
    report = runner.run("agent")
    assert report.status == "failed"
    assert not report.competition_ready
    assert "stability checks failed" in " ".join(report.warnings)


def test_experiment_dataset_and_output_paths_are_guarded(
    config_tree: Path,
    tmp_path: Path,
) -> None:
    settings = load_settings(config_tree)
    workspace = tmp_path / "workspace"
    settings.app.workspace_dir = workspace
    settings.evaluation = EvaluationConfig(output_dir=tmp_path / "outside")
    with pytest.raises(ConfigurationError, match="inside workspace"):
        ExperimentRunner(settings, MockLLMBackend())

    workspace.mkdir()
    outside_dataset = tmp_path / "outside.json"
    outside_dataset.write_text("[]", encoding="utf-8")
    settings.evaluation = EvaluationConfig(
        output_dir=workspace / "evaluation",
        agent_dataset_path=outside_dataset,
    )
    runner = ExperimentRunner(settings, MockLLMBackend())
    with pytest.raises(ConfigurationError, match="datasets"):
        runner.run("agent")


def test_competition_export_rejects_mock_and_outside_paths(
    config_tree: Path,
    tmp_path: Path,
) -> None:
    settings = load_settings(config_tree)
    workspace = tmp_path / "workspace"
    settings.app.workspace_dir = workspace
    settings.evaluation = EvaluationConfig(output_dir=workspace / "evaluation")
    report = ExperimentRunner(settings, MockLLMBackend()).run("agent")
    assert report.json_path is not None
    with pytest.raises(PermissionError, match="Mock result"):
        export_competition_archive(settings.evaluation.output_dir, workspace)
    with pytest.raises(PermissionError, match="inside workspace"):
        export_competition_archive(tmp_path / "outside", workspace)


def test_competition_export_accepts_only_complete_real_report(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    output = workspace / "evaluation"
    modes = ("non-thinking", "thinking", "dynamic")
    report = BenchmarkSuiteReport(
        status="completed",
        competition_ready=True,
        mock_only=False,
        seed=42,
        section="all",
        metrics={
            name: {}
            for name in ("agent", "rag", "vision", "realtime", "security")
        },
        rocm=[
            RocmBenchmarkRecord(
                thinking_mode=mode,
                status="completed",
                quantization="Q4_K_M",
                prefix_cache_enabled=True,
                context_compression_enabled=False,
                model_residency="on_demand",
                rgc_enabled=True,
            )
            for mode in modes
        ],
        stability=[
            StabilityCheck(
                name="validated-manifest",
                status="validated",
                requested_iterations=1,
                completed_iterations=1,
            )
        ],
    )
    export_report(report, output)
    archive = export_competition_archive(output, workspace)
    assert archive.is_file()
    with tarfile.open(archive, "r:gz") as bundle:
        assert set(bundle.getnames()) == {
            "benchmark-suite.json",
            "benchmark-suite.md",
        }


def test_docker_and_delivery_scripts_do_not_download_models() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    rocm_dockerfile = Path("Dockerfile.rocm").read_text(encoding="utf-8")
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    profiles = {
        profile
        for service in compose["services"].values()
        for profile in service.get("profiles", [])
    }
    assert {"mock", "llama-cpp", "vllm-rocm", "full-demo", "rocm-app"} <= profiles
    assert "models:ro" in compose_text
    assert "ROCM_BASE_IMAGE" in rocm_dockerfile
    assert "/dev/kfd" in compose_text
    assert "/workspace/persistent/buildguard" in compose_text
    forbidden = ("wget ", "curl ", "huggingface-cli", "snapshot_download")
    assert not any(item in dockerfile for item in forbidden)
    assert not any(item in rocm_dockerfile for item in forbidden)
    assert not any(item in compose_text for item in forbidden)

    server_requirements = Path("requirements/server-app.txt").read_text(
        encoding="utf-8"
    )
    frozen_requirements = Path("deployment/requirements-server.txt").read_text(
        encoding="utf-8"
    )
    assert ".[amd,pdf]" in server_requirements
    assert "git+ssh" not in frozen_requirements
    assert "file:///torch" not in frozen_requirements
    assert "file:///triton" not in frozen_requirements

    expected_scripts = {
        "install_check.sh",
        "start_mock_demo.sh",
        "start_rocm_demo.sh",
        "run_agent_benchmark.sh",
        "run_rag_benchmark.sh",
        "run_video_stability.sh",
        "export_competition_results.sh",
    }
    scripts = {path.name for path in Path("scripts").glob("*.sh")}
    assert expected_scripts <= scripts
    export_script = Path(
        "scripts/export_competition_results.sh"
    ).read_text(encoding="utf-8")
    assert "export-competition-results" in export_script
    assert "python -c" not in export_script
    video_script = Path("scripts/run_video_stability.sh").read_text(encoding="utf-8")
    assert "must be a localhost HTTP endpoint" in video_script
    agent_script = Path("scripts/run_agent_benchmark.sh").read_text(encoding="utf-8")
    assert "Agent smoke tasks failed" in agent_script
    assert "must be a positive integer" in agent_script
