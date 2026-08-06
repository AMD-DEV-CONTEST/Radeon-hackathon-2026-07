"""Unified offline benchmark suite using measured or explicitly mock data."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

import orjson
from pydantic import BaseModel, Field

from buildguard.config import Settings
from buildguard.evaluation.agent_metrics import (
    AgentEvaluationCase,
    evaluate_agent,
)
from buildguard.evaluation.rag_metrics import RagEvaluationCase, evaluate_rag
from buildguard.evaluation.realtime_metrics import (
    RealtimeEvaluationCase,
    evaluate_realtime,
)
from buildguard.evaluation.report import export_report
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
from buildguard.llm.base import LocalLLMBackend
from buildguard.logging_system.jsonl_writer import JsonlWriter
from buildguard.schemas.common import StrictSchema
from buildguard.security.advanced.capabilities import CapabilityManager
from buildguard.security.advanced.data_policy import DataFlowPolicy
from buildguard.security.advanced.injection_tests import (
    normal_flow_cases,
    prompt_injection_cases,
)
from buildguard.security.advanced.trust_labels import LabeledData, Provenance, TrustLabel
from buildguard.security.audit import ToolAuditLogger
from buildguard.security.confirmation import ConfirmationManager
from buildguard.security.permission_engine import PermissionEngine
from buildguard.tools.builtin.system_tools import register_system_tools
from buildguard.tools.executor import ToolExecutor
from buildguard.tools.registry import ToolRegistry
from buildguard.tools.schemas import ToolExecutionRequest
from buildguard.utils.time import utc_now

SuiteSection = Literal["all", "agent", "rag", "vision", "realtime", "security", "rocm"]
CaseT = TypeVar("CaseT", bound=BaseModel)


class StabilityCheck(StrictSchema):
    name: str
    status: Literal["validated", "skipped", "failed"]
    requested_iterations: int = Field(ge=0)
    completed_iterations: int = Field(ge=0)
    reason: str | None = None


class BenchmarkSuiteReport(StrictSchema):
    status: Literal["completed", "completed_with_unavailable_resources", "failed"]
    competition_ready: bool
    mock_only: bool
    created_at: datetime = Field(default_factory=utc_now)
    seed: int
    section: SuiteSection
    metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    rocm: list[RocmBenchmarkRecord] = Field(default_factory=list)
    stability: list[StabilityCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    json_path: Path | None = None
    markdown_path: Path | None = None


class ExperimentRunner:
    def __init__(self, settings: Settings, backend: LocalLLMBackend) -> None:
        self.settings = settings
        self.backend = backend
        workspace = settings.app.workspace_dir.resolve()
        output = settings.evaluation.output_dir.resolve()
        try:
            output.relative_to(workspace)
        except ValueError as exc:
            raise ConfigurationError(
                "Evaluation output_dir must remain inside workspace"
            ) from exc
        self.output_dir = output

    def _load_cases(
        self,
        path: Path | None,
        schema: type[CaseT],
        fallback: list[CaseT],
    ) -> tuple[list[CaseT], bool]:
        if path is None:
            return fallback, True
        source = path.resolve()
        try:
            source.relative_to(self.settings.app.workspace_dir.resolve())
        except ValueError as exc:
            raise ConfigurationError(
                "Evaluation datasets must remain inside workspace"
            ) from exc
        if not source.is_file():
            raise ConfigurationError(f"Evaluation dataset does not exist: {source}")
        raw = source.read_bytes().strip()
        if not raw:
            raise ConfigurationError(f"Evaluation dataset is empty: {source}")
        payload = orjson.loads(raw)
        if not isinstance(payload, list):
            raise ConfigurationError("Evaluation dataset root must be a JSON list")
        return [schema.model_validate(item) for item in payload], False

    @staticmethod
    def _agent_cases() -> list[AgentEvaluationCase]:
        return [
            AgentEvaluationCase(
                case_id="single-tool",
                task_succeeded=True,
                expected_tools=["echo"],
                selected_tools=["echo"],
                expected_arguments=[{"text": "$user.query"}],
                actual_arguments=[{"text": "$user.query"}],
                planned_steps=1,
                completed_steps=1,
            ),
            AgentEvaluationCase(
                case_id="replan-multiturn",
                task_succeeded=True,
                expected_tools=["echo", "echo"],
                selected_tools=["echo", "echo"],
                expected_arguments=[{"text": "first"}, {"text": "second"}],
                actual_arguments=[{"text": "first"}, {"text": "second"}],
                planned_steps=2,
                completed_steps=2,
                replan_required=True,
                replan_succeeded=True,
                multi_turn=True,
                multi_turn_succeeded=True,
            ),
        ]

    @staticmethod
    def _rag_cases() -> list[RagEvaluationCase]:
        return [
            RagEvaluationCase(
                case_id="grounded",
                relevant_chunk_ids=["chunk-a", "chunk-b"],
                retrieved_chunk_ids=["chunk-a", "chunk-x", "chunk-b"],
                citation_supported=[True, True],
                claim_supported=[True, True],
            ),
            RagEvaluationCase(
                case_id="refusal",
                expected_refusal=True,
                actual_refusal=True,
            ),
        ]

    @staticmethod
    def _vision_cases() -> list[VisionEvaluationCase]:
        return [
            VisionEvaluationCase(
                case_id="rgc-fixture",
                ground_truth_labels=["missing_helmet", "unsafe_edge"],
                high_risk_labels=["unsafe_edge"],
                predictions=[
                    VisionPrediction(
                        label="missing_helmet",
                        confidence=0.9,
                        matched=True,
                    ),
                    VisionPrediction(
                        label="unsafe_edge",
                        confidence=0.8,
                        matched=True,
                    ),
                ],
                model_calls=2,
                full_model_calls=3,
                latency_ms=20,
                processed_frames=5,
                elapsed_seconds=1,
            )
        ]

    @staticmethod
    def _realtime_cases() -> list[RealtimeEvaluationCase]:
        return [
            RealtimeEvaluationCase(
                case_id="synthetic-video",
                frame_ground_truth=[False, True, True, False],
                frame_predictions=[False, True, True, False],
                ground_truth_event_ids=["event-a"],
                detected_event_ids=["event-a"],
                emitted_event_ids=["event-a"],
                confirmation_latencies_ms=[200],
                reconnect_times_seconds=[0.5],
                observed_seconds=10,
            )
        ]

    @staticmethod
    def _security_cases() -> list[SecurityEvaluationCase]:
        policy = DataFlowPolicy()
        result: list[SecurityEvaluationCase] = []
        for case in [*prompt_injection_cases(), *normal_flow_cases()]:
            decision = policy.check(
                LabeledData(
                    value=case.payload,
                    label=case.source_label,
                    provenance=Provenance(
                        source_id=case.case_id,
                        source_kind="benchmark_suite",
                    ),
                    sensitive=case.sensitive,
                ),
                case.destination,
            )
            result.append(
                SecurityEvaluationCase(
                    case_id=case.case_id,
                    attack=case.attack,
                    expected_allowed=case.expected_allowed,
                    actual_allowed=decision.allowed,
                    unauthorized_access_attempt=(
                        case.attack
                        and case.destination in {"read_path", "write_path"}
                    ),
                    sensitive_leakage=(
                        case.sensitive
                        and case.destination == "network_payload"
                        and decision.allowed
                    ),
                )
            )
        return result

    def _stability_manifest(self) -> list[StabilityCheck]:
        config = self.settings.evaluation
        return [
            StabilityCheck(
                name="20-agent-tasks",
                status="skipped",
                requested_iterations=config.agent_iterations,
                completed_iterations=0,
                reason="Run scripts/run_agent_benchmark.sh for the full repeated workflow",
            ),
            StabilityCheck(
                name="50-tool-tasks",
                status="skipped",
                requested_iterations=config.tool_iterations,
                completed_iterations=0,
                reason="Tool stability execution has not run",
            ),
            StabilityCheck(
                name="single-video-continuous",
                status="skipped",
                requested_iterations=config.video_stability_seconds,
                completed_iterations=0,
                reason="Requires a configured local video or camera",
            ),
            StabilityCheck(
                name="multi-camera-stress",
                status="skipped",
                requested_iterations=config.multi_camera_stress_count,
                completed_iterations=0,
                reason="Requires configured physical or RTSP camera sources",
            ),
            StabilityCheck(
                name="offline-operation",
                status="skipped",
                requested_iterations=1,
                completed_iterations=0,
                reason="Run in an isolated host/container network and retain logs",
            ),
            StabilityCheck(
                name="model-service-restart",
                status="skipped",
                requested_iterations=1,
                completed_iterations=0,
                reason="Requires control of the configured local model service",
            ),
            StabilityCheck(
                name="rtsp-disconnect",
                status="skipped",
                requested_iterations=1,
                completed_iterations=0,
                reason="Requires a controllable RTSP test source",
            ),
            StabilityCheck(
                name="disk-space-exhaustion",
                status="skipped",
                requested_iterations=1,
                completed_iterations=0,
                reason="Requires a disposable quota-limited volume",
            ),
            StabilityCheck(
                name="single-model-failure",
                status="skipped",
                requested_iterations=1,
                completed_iterations=0,
                reason="Requires a configured multi-model detector setup",
            ),
        ]

    def _configured_stability(self) -> list[StabilityCheck]:
        configured = self.settings.evaluation.stability_manifest_path
        if configured is None:
            return self._stability_manifest()
        loaded, _ = self._load_cases(
            configured,
            StabilityCheck,
            [],
        )
        if not loaded:
            raise ConfigurationError("Stability manifest must contain at least one check")
        return loaded

    def run_tool_stability(self, iterations: int | None = None) -> StabilityCheck:
        requested = iterations or self.settings.evaluation.tool_iterations
        if requested < 1:
            raise ValueError("Tool stability iterations must be positive")
        registry = ToolRegistry()
        register_system_tools(
            registry,
            timeout_seconds=self.settings.app.tools.default_timeout_seconds,
        )
        capability_manager = CapabilityManager(
            max_ttl_seconds=self.settings.permissions.advanced.capability_ttl_seconds,
            default_max_uses=requested,
        )
        task_id = "benchmark-tool-stability"
        token = capability_manager.issue(
            task_id=task_id,
            tool_name="get_runtime_status",
            root=self.settings.app.workspace_dir,
            operations=["read"],
            resource_ids=[],
            ttl_seconds=self.settings.permissions.advanced.capability_ttl_seconds,
            issued_by=LabeledData(
                value="benchmark-suite-policy",
                label=TrustLabel.TRUSTED_POLICY,
                provenance=Provenance(
                    source_id="benchmark-suite",
                    source_kind="local_policy",
                ),
            ),
            max_uses=requested,
        )
        audit_path = self.output_dir / "tool-stability-audit.jsonl"
        completed = 0
        with JsonlWriter(audit_path) as writer:
            executor = ToolExecutor(
                registry,
                PermissionEngine(
                    ConfirmationManager(
                        self.settings.permissions.confirmation_ttl_seconds
                    )
                ),
                ToolAuditLogger(writer),
                retry_attempts=self.settings.permissions.tool_retry_attempts,
                retry_wait_seconds=self.settings.permissions.tool_retry_wait_seconds,
                capability_manager=capability_manager,
                require_capability=True,
            )
            for index in range(requested):
                result = executor.execute(
                    ToolExecutionRequest(
                        session_id="benchmark-session",
                        task_id=task_id,
                        actor="benchmark-suite",
                        tool_name="get_runtime_status",
                        arguments={"include_process": index % 2 == 0},
                        capability_id=token.capability_id,
                    )
                )
                if not result.success:
                    return StabilityCheck(
                        name="50-tool-tasks",
                        status="failed",
                        requested_iterations=requested,
                        completed_iterations=completed,
                        reason=result.error,
                    )
                completed += 1
        return StabilityCheck(
            name="50-tool-tasks",
            status="validated",
            requested_iterations=requested,
            completed_iterations=completed,
        )

    def run(self, section: SuiteSection = "all") -> BenchmarkSuiteReport:
        metrics: dict[str, dict[str, Any]] = {}
        fixture_sections: list[str] = []
        config = self.settings.evaluation
        if section in {"all", "agent"}:
            agent_cases, fixture = self._load_cases(
                config.agent_dataset_path,
                AgentEvaluationCase,
                self._agent_cases(),
            )
            if fixture:
                fixture_sections.append("agent")
            metrics["agent"] = evaluate_agent(
                agent_cases
            ).model_dump(mode="json")
        if section in {"all", "rag"}:
            rag_cases, fixture = self._load_cases(
                config.rag_dataset_path,
                RagEvaluationCase,
                self._rag_cases(),
            )
            if fixture:
                fixture_sections.append("rag")
            metrics["rag"] = evaluate_rag(
                rag_cases
            ).model_dump(mode="json")
        if section in {"all", "vision"}:
            vision_cases, fixture = self._load_cases(
                config.vision_dataset_path,
                VisionEvaluationCase,
                self._vision_cases(),
            )
            if fixture:
                fixture_sections.append("vision")
            metrics["vision"] = evaluate_vision(
                vision_cases
            ).model_dump(mode="json")
        if section in {"all", "realtime"}:
            realtime_cases, fixture = self._load_cases(
                config.realtime_dataset_path,
                RealtimeEvaluationCase,
                self._realtime_cases(),
            )
            if fixture:
                fixture_sections.append("realtime")
            metrics["realtime"] = evaluate_realtime(
                realtime_cases
            ).model_dump(mode="json")
        if section in {"all", "security"}:
            security_cases, fixture = self._load_cases(
                config.security_dataset_path,
                SecurityEvaluationCase,
                self._security_cases(),
            )
            if fixture:
                fixture_sections.append("security")
            metrics["security"] = evaluate_security(security_cases).model_dump(
                mode="json"
            )
        rocm = (
            RocmBenchmarkRunner(self.settings, self.backend).run_matrix()
            if section in {"all", "rocm"}
            else []
        )
        unavailable = any(
            item.status in {"unavailable", "failed", "mock_validation"}
            for item in rocm
        )
        mock_only = self.settings.llm.mode == "mock"
        warnings: list[str] = []
        if mock_only:
            warnings.append(
                "Mock results validate program flow only and are not competition results"
            )
        if unavailable and not mock_only:
            warnings.append("One or more real ROCm benchmark cases were unavailable")
        if fixture_sections:
            warnings.append(
                "Built-in deterministic fixtures used for: "
                + ", ".join(fixture_sections)
                + "; provide configured datasets for competition metrics"
            )
        stability = self._configured_stability()
        tool_stability = self.run_tool_stability(
            self.settings.evaluation.tool_iterations
        )
        stability = [
            tool_stability if item.name == "50-tool-tasks" else item
            for item in stability
        ]
        if all(item.name != "50-tool-tasks" for item in stability):
            stability.append(tool_stability)
        stability_ready = bool(stability) and all(
            item.status == "validated" for item in stability
        )
        stability_failed = any(item.status == "failed" for item in stability)
        stability_unavailable = any(item.status == "skipped" for item in stability)
        if stability_failed:
            warnings.append("One or more stability checks failed")
        elif stability_unavailable:
            warnings.append("One or more resource-dependent stability checks were skipped")
        report_status: Literal[
            "completed", "completed_with_unavailable_resources", "failed"
        ] = (
            "failed"
            if stability_failed
            else (
                "completed_with_unavailable_resources"
                if unavailable or fixture_sections or stability_unavailable
                else "completed"
            )
        )
        report = BenchmarkSuiteReport(
            status=report_status,
            competition_ready=(
                section == "all"
                and not mock_only
                and not unavailable
                and not fixture_sections
                and stability_ready
            ),
            mock_only=mock_only,
            seed=self.settings.app.seed,
            section=section,
            metrics=metrics,
            rocm=rocm,
            stability=stability,
            warnings=warnings,
        )
        json_path, markdown_path = export_report(report, self.output_dir)
        return report.model_copy(
            update={
                "json_path": json_path,
                "markdown_path": markdown_path,
            }
        )
