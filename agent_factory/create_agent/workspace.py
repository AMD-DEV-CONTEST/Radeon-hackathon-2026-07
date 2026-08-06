from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agent_factory.create_agent.models import (
    ACTION_FILE,
    KNOWLEDGE_SOURCES_FILE,
    PUBLISH_FILE,
    PUBLISH_DECISION_FILE,
    RESOURCES_FILE,
    SKILL_GATEWAY_STATE_FILE,
    SYSTEM_STATE_FILE,
    TASK_ANALYSIS_FILE,
    TOOL_PROBE_FILE,
    VALIDATION_FILE,
    VALIDATION_STATE_FILE,
    CreateAgentAction,
    CreateAgentPublishDecision,
    CreateAgentTaskAnalysis,
    EvolutionTaskAnalysis,
    PackageToolProbeState,
    PackageKnowledgeSourceRegistry,
    PackageValidationReport,
    PackageValidationState,
    SystemManufacturingState,
    initial_system_manufacturing_state,
)
from agent_factory.create_agent.package_scaffold import materialize_empty_agent_package
from agent_factory.paths import factory_artifact_path


ModelT = TypeVar("ModelT", bound=BaseModel)


class CreateAgentWorkspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def for_session(cls, session_id: str) -> "CreateAgentWorkspace":
        safe_session_id = "".join(char for char in session_id if char.isalnum() or char in {"-", "_"})[:64]
        if not safe_session_id:
            raise ValueError("create-agent session id must not be empty")
        return cls(factory_artifact_path("create_agent_workspaces", safe_session_id))

    def initialize(self, *, user_input: str, task_analysis: CreateAgentTaskAnalysis) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.factory_dir.mkdir(parents=True, exist_ok=True)
        self.write_task_analysis(task_analysis)
        analysis = self.read_task_analysis()
        if not self.package_manifest_path().exists():
            materialize_empty_agent_package(
                self.root,
                factory_run_id=self.root.name,
                user_input=user_input,
                pattern_id=analysis.selected_pattern_id,
            )
        if not self.system_state_path.exists():
            self.write_system_state(initial_system_manufacturing_state())
        if not self.action_path.exists():
            self.write_action(CreateAgentAction())
        if not self.resources_path.exists():
            self._write_json(self.resources_path, {"version": "resource_facts.v0", "facts": []})
        request_path = self.factory_dir / "request.txt"
        if not request_path.exists():
            request_path.write_text(user_input, encoding="utf-8")

    @property
    def factory_dir(self) -> Path:
        return self.root / ".factory"

    @property
    def system_state_path(self) -> Path:
        return self.root / SYSTEM_STATE_FILE

    @property
    def action_path(self) -> Path:
        return self.root / ACTION_FILE

    @property
    def validation_path(self) -> Path:
        return self.root / VALIDATION_FILE

    @property
    def validation_state_path(self) -> Path:
        return self.root / VALIDATION_STATE_FILE

    @property
    def publish_path(self) -> Path:
        return self.root / PUBLISH_FILE

    @property
    def publish_decision_path(self) -> Path:
        return self.root / PUBLISH_DECISION_FILE

    @property
    def tool_probe_path(self) -> Path:
        return self.root / TOOL_PROBE_FILE

    @property
    def resources_path(self) -> Path:
        return self.root / RESOURCES_FILE

    @property
    def knowledge_sources_path(self) -> Path:
        return self.root / KNOWLEDGE_SOURCES_FILE

    @property
    def skill_gateway_state_path(self) -> Path:
        return self.root / SKILL_GATEWAY_STATE_FILE

    @property
    def task_analysis_path(self) -> Path:
        return self.root / TASK_ANALYSIS_FILE

    @property
    def request_path(self) -> Path:
        return self.factory_dir / "request.txt"

    @property
    def manufacturing_trace_path(self) -> Path:
        return self.factory_dir / "manufacturing_trace.json"

    @property
    def tool_outputs_path(self) -> Path:
        return self.factory_dir / "tool_outputs"

    def read_system_state(self) -> SystemManufacturingState:
        if not self.system_state_path.exists():
            return initial_system_manufacturing_state()
        return SystemManufacturingState.model_validate_json(self.system_state_path.read_text(encoding="utf-8"))

    def write_system_state(self, state: SystemManufacturingState) -> None:
        self._write_json(self.system_state_path, state.model_dump(mode="json"))

    def read_knowledge_sources(self) -> PackageKnowledgeSourceRegistry:
        if not self.knowledge_sources_path.exists():
            return PackageKnowledgeSourceRegistry()
        return PackageKnowledgeSourceRegistry.model_validate_json(
            self.knowledge_sources_path.read_text(encoding="utf-8")
        )

    def write_knowledge_sources(self, registry: PackageKnowledgeSourceRegistry) -> None:
        self._write_json(self.knowledge_sources_path, registry.model_dump(mode="json"))

    def read_task_analysis(self) -> CreateAgentTaskAnalysis | EvolutionTaskAnalysis:
        if not self.task_analysis_path.is_file():
            raise ValueError(
                f"missing managed create-agent task analysis: {self.task_analysis_path}. "
                "Start a new /create-agent manufacture run so task analysis can select a runtime pattern."
            )
        payload = _read_json_object(self.task_analysis_path)
        if payload.get("version") == "evolution_task_analysis.v0":
            return EvolutionTaskAnalysis.model_validate(payload)
        return CreateAgentTaskAnalysis.model_validate(payload)

    def write_task_analysis(self, analysis: CreateAgentTaskAnalysis | EvolutionTaskAnalysis) -> None:
        self._write_json(self.task_analysis_path, analysis.model_dump(mode="json"))

    def read_action(self) -> CreateAgentAction:
        return _read_managed_model(
            self.action_path,
            CreateAgentAction,
            missing=CreateAgentAction(),
            owner_tool="create_agent_control",
        )

    def write_action(self, action: CreateAgentAction) -> None:
        self._write_json(self.action_path, action.model_dump(mode="json"))

    def write_validation(self, report: PackageValidationReport) -> None:
        self._write_json(self.validation_path, report.model_dump(mode="json"))

    def read_validation(self) -> PackageValidationReport | None:
        return _read_managed_model(
            self.validation_path,
            PackageValidationReport,
            missing=None,
            owner_tool="create_agent_validate",
        )

    def read_validation_state(self) -> PackageValidationState | None:
        return _read_managed_model(
            self.validation_state_path,
            PackageValidationState,
            missing=None,
            owner_tool="create_agent_validate",
        )

    def write_validation_state(self, state: PackageValidationState) -> None:
        self._write_json(self.validation_state_path, state.model_dump(mode="json"))

    def read_tool_probe_state(self) -> PackageToolProbeState:
        return _read_managed_model(
            self.tool_probe_path,
            PackageToolProbeState,
            missing=PackageToolProbeState(),
            owner_tool="create_agent_probe_tool",
        ) or PackageToolProbeState()

    def write_tool_probe_state(self, state: PackageToolProbeState) -> None:
        self._write_json(self.tool_probe_path, state.model_dump(mode="json"))

    def read_publish_report(self) -> dict[str, Any]:
        return _read_json_object(self.publish_path)

    def write_publish_report(self, payload: dict[str, Any]) -> None:
        self._write_json(self.publish_path, payload)

    def read_publish_decision(self) -> CreateAgentPublishDecision:
        return _read_managed_model(
            self.publish_decision_path,
            CreateAgentPublishDecision,
            missing=CreateAgentPublishDecision(),
            owner_tool="the create-agent publish API",
        ) or CreateAgentPublishDecision()

    def write_publish_decision(self, decision: CreateAgentPublishDecision) -> None:
        self._write_json(self.publish_decision_path, decision.model_dump(mode="json"))

    def reset_manufacturing_trace(self, *, session_id: str, request_id: str, graph_id: str) -> None:
        self._write_json(
            self.manufacturing_trace_path,
            {
                "version": "create_agent_manufacturing_trace.v0",
                "session_id": session_id,
                "request_id": request_id,
                "graph_id": graph_id,
                "workspace_path": str(self.root),
                "created_at": datetime.now(UTC).isoformat(),
                "records": [],
            },
        )

    def reset_evolution_trace(
        self,
        *,
        session_id: str | None,
        request_id: str,
        graph_id: str,
        package_id: str,
        trace_id: str | None,
        target_plan: dict[str, Any],
    ) -> None:
        self._write_json(
            self.manufacturing_trace_path,
            {
                "version": "agent_evolution_manufacturing_trace.v0",
                "session_id": session_id,
                "request_id": request_id,
                "graph_id": graph_id,
                "package_id": package_id,
                "trace_id": trace_id,
                "workspace_path": str(self.root),
                "target_plan": target_plan,
                "created_at": datetime.now(UTC).isoformat(),
                "records": [],
            },
        )

    def append_manufacturing_trace_record(self, record: dict[str, Any]) -> None:
        payload = _read_json_object(self.manufacturing_trace_path)
        if payload.get("version") != "create_agent_manufacturing_trace.v0":
            payload = {
                "version": "create_agent_manufacturing_trace.v0",
                "workspace_path": str(self.root),
                "created_at": datetime.now(UTC).isoformat(),
                "records": [],
            }
        records = payload.get("records")
        if not isinstance(records, list):
            records = []
            payload["records"] = records
        records.append(record)
        payload["updated_at"] = datetime.now(UTC).isoformat()
        self._write_json(self.manufacturing_trace_path, payload)

    def append_evolution_trace_record(self, record: dict[str, Any]) -> None:
        payload = _read_json_object(self.manufacturing_trace_path)
        if payload.get("version") != "agent_evolution_manufacturing_trace.v0":
            payload = {
                "version": "agent_evolution_manufacturing_trace.v0",
                "workspace_path": str(self.root),
                "created_at": datetime.now(UTC).isoformat(),
                "records": [],
            }
        records = payload.get("records")
        if not isinstance(records, list):
            records = []
            payload["records"] = records
        records.append(record)
        payload["updated_at"] = datetime.now(UTC).isoformat()
        self._write_json(self.manufacturing_trace_path, payload)

    def manufacturing_trace_record_count(self) -> int:
        payload = _read_json_object(self.manufacturing_trace_path)
        records = payload.get("records")
        if not isinstance(records, list):
            return 0
        return len(records)

    def evolution_trace_record_count(self) -> int:
        payload = _read_json_object(self.manufacturing_trace_path)
        if payload.get("version") != "agent_evolution_manufacturing_trace.v0":
            return 0
        records = payload.get("records")
        if not isinstance(records, list):
            return 0
        return len(records)

    def package_manifest_path(self) -> Path:
        return self.root / "agent_package.json"

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        _assert_inside(self.root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(path)


def _read_managed_model(path: Path, model: type[ModelT], *, missing: ModelT | None, owner_tool: str) -> ModelT | None:
    if not path.exists():
        return missing
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            f"invalid managed create-agent file: {path}. Regenerate it through {owner_tool}; "
            "direct edits and older structures are not accepted."
        ) from exc


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes create-agent workspace: {path}") from exc
