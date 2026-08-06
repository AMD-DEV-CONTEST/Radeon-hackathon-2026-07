from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.model_pool.schema import ModelSelectionRequirement, ModelToolSelectionRequirement


SYSTEM_STATE_FILE = ".factory/system_state.json"
ACTION_FILE = ".factory/action.json"
VALIDATION_FILE = ".factory/validation.json"
VALIDATION_STATE_FILE = ".factory/validation_state.json"
TOOL_PROBE_FILE = ".factory/tool_probe.json"
TASK_ANALYSIS_FILE = ".factory/task_analysis.json"
PUBLISH_FILE = ".factory/publish.json"
PUBLISH_DECISION_FILE = ".factory/publish_decision.json"
RESOURCES_FILE = ".factory/resources.json"
SKILL_GATEWAY_STATE_FILE = ".factory/skill_gateway_state.json"
KNOWLEDGE_SOURCES_FILE = ".factory/knowledge_sources.json"
TEXT_SUMMARY_LIMIT = 240


PackageKnowledgePurpose = Literal["domain_reference", "operational_reference", "curated_facts"]
PackageKnowledgeSourceKind = Literal[
    "user_provided",
    "project_asset",
    "skill_asset",
    "authorized_public_source",
]


class PackageKnowledgeSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: PackageKnowledgeSourceKind
    reference: str = Field(min_length=1)
    distributable: Literal[True]

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reference must identify the concrete source material")
        return normalized


class PackageKnowledgeSourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_path: str = Field(min_length=1)
    purpose: PackageKnowledgePurpose
    source: PackageKnowledgeSourceEvidence

    @field_validator("knowledge_path")
    @classmethod
    def validate_knowledge_path(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        parts = normalized.split("/")
        if len(parts) < 2 or parts[0] != "knowledge" or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("knowledge_path must identify a package-relative file under knowledge/")
        return normalized


class PackageKnowledgeSourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_knowledge_sources.v0"] = "package_knowledge_sources.v0"
    records: list[PackageKnowledgeSourceRecord] = Field(default_factory=list)


class ResourceFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any = None
    secret: bool = False
    source: Literal["user", "tool", "mcp", "skill", "default", "system"] = "user"
    confidence: float = 1.0
    evidence_refs: list[str] = Field(default_factory=list)


class ResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str
    description: str = ""
    secret: bool = False


class CreateAgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["continue", "ask_user", "finalize"] = "continue"
    message: str = ""
    resource_facts: list[ResourceFact] = Field(default_factory=list)
    resource_requests: list[ResourceRequest] = Field(default_factory=list)


class CreateAgentIntentDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal["manufacture_agent", "workspace_assist", "chat"]
    rationale: str = ""
    reasoning: str = ""
    confidence: float | None = None

    @model_validator(mode="after")
    def _normalize_rationale(self) -> "CreateAgentIntentDecision":
        if not self.rationale and self.reasoning:
            self.rationale = self.reasoning
        return self


class CreateAgentTaskAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["create_agent_task_analysis.v0"] = "create_agent_task_analysis.v0"
    intent_summary: str = ""
    capability_goals: list[str] = Field(default_factory=list)
    interaction_style: str = ""
    requires_dynamic_plan: bool = False
    selected_pattern_id: Literal["react_agent", "plan_and_execute"]
    model_requirements: list[ModelSelectionRequirement] = Field(default_factory=list)
    model_tool_requirements: list[ModelToolSelectionRequirement] = Field(default_factory=list)
    resource_requirements: list["TaskResourceRequirement"] = Field(default_factory=list)
    reasoning: str = ""
    selection_reason: str = ""
    manufacturing_notes: list[str] = Field(default_factory=list)
    available_patterns: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class TaskResourceRequirement(BaseModel):
    """A deployment-time resource inferred from a requested capability."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    description: str = ""
    required: bool = True
    value_schema: dict[str, Any] = Field(default_factory=dict)
    secret_fields: list[str] = Field(default_factory=list)
    used_by: list[str] = Field(default_factory=list)
    sandbox_access_expectation: str = ""

    @field_validator("resource_id")
    @classmethod
    def _resource_id_is_clean(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("resource_id must not be empty")
        return normalized


EvolutionSystemId = Literal[
    "package_identity_system",
    "model_system",
    "resources_system",
    "context_system",
    "knowledge_system",
    "tools_system",
    "package_tool_system",
    "skillhub_system",
    "assembly_pattern_system",
    "scheduler_system",
    "validation_publish_system",
    "runtime_infrastructure",
]


class EvolutionTaskAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["evolution_task_analysis.v0"] = "evolution_task_analysis.v0"
    goal_summary: str = ""
    selected_pattern_id: Literal["react_agent", "plan_and_execute"]
    affected_systems: list[EvolutionSystemId] = Field(default_factory=list)
    capability_changes: list[str] = Field(default_factory=list)
    model_requirements: list[ModelSelectionRequirement] = Field(default_factory=list)
    model_tool_requirements: list[ModelToolSelectionRequirement] = Field(default_factory=list)
    resource_requirements: list[TaskResourceRequirement] = Field(default_factory=list)
    tool_source_decisions: list[str] = Field(default_factory=list)
    preserved_systems: list[EvolutionSystemId] = Field(default_factory=list)
    validation_focuses: list[str] = Field(default_factory=list)
    reasoning: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class SystemStageStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    validating = "validating"
    done = "done"
    failed_needs_repair = "failed_needs_repair"
    blocked_waiting_user = "blocked_waiting_user"


class SystemRepairIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str
    where: str
    summary: str
    category: Literal[
        "schema_error",
        "package_shape_error",
        "runtime_contract_error",
        "assembly_compile_error",
        "tool_binding_error",
        "model_behavior_error",
        "resource_missing",
        "resource_unavailable",
        "validator_runtime_defect",
    ] = "schema_error"
    target_files: list[str] = Field(default_factory=list)
    repair_hint: str = ""
    resolved: bool = False


class SystemStageValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    status: Literal["not_run", "passed", "failed"] = "not_run"
    summary: str = ""
    issue_ids: list[str] = Field(default_factory=list)
    updated_at: str = ""


class SystemStageHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outputs: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SystemStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_id: str
    stage_order: int
    title: str
    status: SystemStageStatus = SystemStageStatus.pending
    focus_files: list[str] = Field(default_factory=list)
    suggested_skills: list[str] = Field(default_factory=list)
    validation_focus: str = "workspace_hygiene"
    focus_summary: str = ""
    repair_history: list[SystemRepairIssue] = Field(default_factory=list)
    handoff_outputs: SystemStageHandoff = Field(default_factory=SystemStageHandoff)
    validation: SystemStageValidation | None = None

    def to_digest(self) -> dict[str, Any]:
        return {
            "system_id": self.system_id,
            "stage_order": self.stage_order,
            "title": self.title,
            "status": self.status.value,
            "focus_files": self.focus_files,
            "suggested_skills": self.suggested_skills,
            "validation_focus": self.validation_focus,
            "focus_summary": self.focus_summary,
            "open_issues": [
                issue.model_dump(mode="json")
                for issue in self.repair_history
                if not issue.resolved
            ][:6],
        }


class SystemManufacturingState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["system_manufacturing_state.v0"] = "system_manufacturing_state.v0"
    workflow_kind: Literal["manufacture", "evolution"] = "manufacture"
    stages: list[SystemStage] = Field(default_factory=list)
    active_focus_id: str = ""
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def active_stage(self) -> SystemStage | None:
        if self.active_focus_id:
            for stage in self.stages:
                if stage.system_id == self.active_focus_id:
                    return stage
        return None

    def all_done(self) -> bool:
        active = self.active_stage()
        return active is not None and active.system_id == "validation_publish"

    def update_stage(self, updated_stage: SystemStage) -> "SystemManufacturingState":
        stages = [
            updated_stage if stage.system_id == updated_stage.system_id else stage
            for stage in self.stages
        ]
        return self.model_copy(
            update={
                "stages": stages,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )

    def set_focus(self, focus_id: str, *, status: SystemStageStatus = SystemStageStatus.in_progress) -> "SystemManufacturingState":
        target = str(focus_id or "").strip()
        if not target:
            raise ValueError("focus_id must not be empty")
        found = False
        target_order = 0
        active_order = 0
        for stage in self.stages:
            if stage.system_id == target:
                target_order = stage.stage_order
            if stage.system_id == self.active_focus_id:
                active_order = stage.stage_order
        stages: list[SystemStage] = []
        for stage in self.stages:
            if stage.system_id == target:
                stages.append(stage.model_copy(update={"status": status}))
                found = True
                continue
            next_status = stage.status
            if stage.status == SystemStageStatus.in_progress:
                if active_order and target_order and stage.stage_order < target_order:
                    next_status = SystemStageStatus.done
                elif stage.stage_order > target_order:
                    next_status = SystemStageStatus.pending
                else:
                    next_status = SystemStageStatus.pending
            stages.append(stage.model_copy(update={"status": next_status}) if next_status != stage.status else stage)
        if not found:
            raise ValueError(f"unknown create-agent focus_id: {focus_id}")
        return self.model_copy(
            update={
                "stages": stages,
                "active_focus_id": target,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )

    def working_set(self) -> dict[str, Any]:
        active = self.active_stage()
        return {
            "active_focus": active.to_digest() if active else None,
            "remaining": sum(1 for stage in self.stages if stage.status != SystemStageStatus.done),
            "total": len(self.stages),
            "stages": [stage.to_digest() for stage in self.stages],
        }


class PackageValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    where: str
    summary: str
    message: str
    severity: Literal["blocking", "warning", "info"] = "blocking"
    path: str = ""
    expected: str = ""
    actual: str = ""
    repair_hint: str = ""
    target_files: list[str] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)
    schema_path: str = ""
    invalid_value_path: str = ""
    expected_shape: dict[str, Any] = Field(default_factory=dict)
    repair_template: dict[str, Any] = Field(default_factory=dict)
    replace_strategy: Literal["", "replace_object", "replace_array_item", "rewrite_file"] = ""
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expected_shape", "repair_template", "details", mode="before")
    @classmethod
    def _dict_fields_json_safe(cls, value: Any) -> dict[str, Any]:
        safe = _json_safe_value(value)
        return safe if isinstance(safe, dict) else {}

    def repair_issue_id(self) -> str:
        return self.to_digest().repair_issue_id()

    def to_digest(self) -> "ValidationIssueDigest":
        raw = json.dumps(
            {
                "where": self.where,
                "path": self.path,
                "target_files": self.target_files,
                "recommended_skill": self.recommended_skill,
                "summary": self.summary,
                "schema_path": self.schema_path,
                "invalid_value_path": self.invalid_value_path,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        issue_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return ValidationIssueDigest(
            issue_id=issue_id,
            where=self.where,
            summary=_compact_text(self.summary, TEXT_SUMMARY_LIMIT),
            severity=self.severity,
            path=self.path,
            expected=_compact_text(self.expected, TEXT_SUMMARY_LIMIT),
            actual=_compact_text(self.actual, TEXT_SUMMARY_LIMIT),
            repair_hint=_compact_text(self.repair_hint, TEXT_SUMMARY_LIMIT),
            target_files=self.target_files[:8],
            recommended_skill=self.recommended_skill,
            recommended_resources=self.recommended_resources[:8],
            schema_path=self.schema_path,
            invalid_value_path=self.invalid_value_path,
            expected_shape=self.expected_shape,
            repair_template=self.repair_template,
            replace_strategy=self.replace_strategy,
        )


class ValidationIssueDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str
    where: str
    summary: str
    severity: Literal["blocking", "warning", "info"] = "blocking"
    path: str = ""
    expected: str = ""
    actual: str = ""
    repair_hint: str = ""
    target_files: list[str] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)
    schema_path: str = ""
    invalid_value_path: str = ""
    expected_shape: dict[str, Any] = Field(default_factory=dict)
    repair_template: dict[str, Any] = Field(default_factory=dict)
    replace_strategy: Literal["", "replace_object", "replace_array_item", "rewrite_file"] = ""

    def repair_issue_id(self) -> str:
        return f"repair_{self.issue_id}"


class PackageValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_report.v0"] = "package_validation_report.v0"
    status: Literal["passed", "failed"] = "failed"
    package_root: str
    validation_scope: Literal[
        "workspace_hygiene",
        "package_shape",
        "runtime_contract_build",
        "assembly_compile",
        "python_syntax",
        "full_static",
    ] = "full_static"
    changed_files: list[str] = Field(default_factory=list)
    cached: bool = False
    skipped: bool = False
    summary: str = ""
    issues: list[PackageValidationIssue] = Field(default_factory=list)

    def to_digest(self) -> "PackageValidationDigest":
        return PackageValidationDigest(
            status=self.status,
            package_root=self.package_root,
            validation_scope=self.validation_scope,
            changed_files=self.changed_files[:12],
            cached=self.cached,
            skipped=self.skipped,
            summary=_compact_text(self.summary, TEXT_SUMMARY_LIMIT),
            issues=[issue.to_digest() for issue in self.issues[:8]],
        )


class PackageValidationDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_digest.v0"] = "package_validation_digest.v0"
    status: Literal["passed", "failed"] = "failed"
    package_root: str
    validation_scope: Literal[
        "workspace_hygiene",
        "package_shape",
        "runtime_contract_build",
        "assembly_compile",
        "python_syntax",
        "full_static",
    ] = "full_static"
    changed_files: list[str] = Field(default_factory=list)
    cached: bool = False
    skipped: bool = False
    summary: str = ""
    issues: list[ValidationIssueDigest] = Field(default_factory=list)


class PackageValidationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_state.v0"] = "package_validation_state.v0"
    package_fingerprint: dict[str, str] = Field(default_factory=dict)
    probe_digest: str = ""
    validation_scope: str = ""
    active_focus_id: str = ""
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PackageToolProbeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    probe_kind: Literal["unknown", "success_path", "error_path"] = "unknown"
    prompt: str = ""
    tool_goal: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    package_digest: str = ""
    tool_digest: str = ""
    tool_digest_kind: str = "package_tool_surface.v2"
    status: Literal["passed", "failed", "configuration_required"] = "failed"
    observation_status: str = ""
    execution_status: str = ""
    contract_status: str = ""
    message: str = ""
    output_summary: str = ""
    observation_output: dict[str, Any] = Field(default_factory=dict)
    dependency_report: dict[str, Any] = Field(default_factory=dict)
    runtime_paths: dict[str, Any] = Field(default_factory=dict)
    final_answer: str = ""
    summary: str = ""
    goal_satisfied: bool | None = None
    tool_returned_business_output: bool = False
    only_error_handling_verified: bool = False
    evaluator: str = ""
    evaluation: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    probed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @field_validator("arguments", "observation_output", "dependency_report", "runtime_paths", "evaluation", mode="before")
    @classmethod
    def _probe_dict_fields_json_safe(cls, value: Any) -> dict[str, Any]:
        safe = _json_safe_value(value)
        return safe if isinstance(safe, dict) else {}

    @field_validator("tool_calls", mode="before")
    @classmethod
    def _tool_calls_json_safe(cls, value: Any) -> list[dict[str, Any]]:
        safe = _json_safe_value(value)
        if not isinstance(safe, list):
            return []
        return [item if isinstance(item, dict) else {"value": item} for item in safe]


class PackageToolProbeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_tool_probe_state.v0"] = "package_tool_probe_state.v0"
    records: list[PackageToolProbeRecord] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def latest_by_tool(self) -> dict[str, PackageToolProbeRecord]:
        latest: dict[str, PackageToolProbeRecord] = {}
        for record in self.records:
            latest[record.tool_id] = record
        return latest


class CreateAgentPublishDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["create_agent_publish_decision.v0"] = "create_agent_publish_decision.v0"
    decision: Literal["pending", "approve"] = "pending"
    input_text: str = ""
    package_fingerprint: dict[str, str] = Field(default_factory=dict)
    validation_scope: str = ""
    validation_status: str = ""
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def initial_system_manufacturing_state(
    *,
    workflow_kind: Literal["manufacture", "evolution"] = "manufacture",
) -> SystemManufacturingState:
    evolution = workflow_kind == "evolution"
    stages = [
        _stage(
            "requirement_focus",
            1,
            "Requirement focus",
            [RESOURCES_FILE, "agent_package.json", "assembly_spec.json", "contracts/resources.json"],
            ["01-evolution-requirement-focus"] if evolution else ["00-manufacturing-control", "01-package-identity-system", "05-resources-system"],
            "workspace_hygiene",
            "Clarify user intent, package identity, missing resources, secrets, schedules, and manufacturable capability boundaries.",
        ),
        _stage(
            "capability_implementation",
            2,
            "Capability implementation",
            [
                "agent_package.json",
                "contracts/resources.json",
                "tools/",
                "extensions/",
                "extensions/extension_bindings.json",
                "knowledge/",
                "contracts/dependencies.json",
                "contracts/model.json",
                "contracts/tools.json",
                "contracts/scheduler_seed.json",
                "assembly_spec.json",
            ],
            ["02-evolution-capability-implementation"] if evolution else [
                "01-package-identity-system",
                "02-model-system",
                "05-resources-system",
                "06-context-system",
                "08-knowledge-system",
                "09-tools-system",
                "10-package-tool-system",
                "11-skillhub-system",
                "14-scheduler-system",
                "15-scheduler-seed-system",
            ],
            "runtime_contract_build",
            "Implement one user-facing capability increment at a time. Baseline package and contracts are already scaffolded; do not audit them.",
        ),
        _stage(
            "experience_assembly",
            3,
            "Experience assembly",
            ["assembly_spec.json"],
            ["03-evolution-experience-assembly"] if evolution else ["12-assembly-pattern-system"],
            "assembly_compile",
            "Bind implemented capabilities into runtime assembly and user-visible experience only after capability files exist.",
        ),
        _stage(
            "validation_publish",
            4,
            "Validation and publish",
            [],
            ["04-evolution-validation-publish"] if evolution else ["17-final-validation-repair"],
            "full_static",
            "Run full validation, repair from evidence, and finalize only when the package is ready.",
        ),
    ]
    started = stages[0].model_copy(update={"status": SystemStageStatus.in_progress})
    return SystemManufacturingState(
        workflow_kind=workflow_kind,
        stages=[started, *stages[1:]],
        active_focus_id=started.system_id,
    )


def _stage(
    system_id: str,
    stage_order: int,
    title: str,
    focus_files: list[str],
    suggested_skills: list[str],
    validation_focus: str,
    focus_summary: str,
) -> SystemStage:
    return SystemStage(
        system_id=system_id,
        stage_order=stage_order,
        title=title,
        focus_files=focus_files,
        suggested_skills=suggested_skills,
        validation_focus=validation_focus,
        focus_summary=focus_summary,
    )


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"


def _compact_issue_details(details: dict[str, Any]) -> dict[str, Any]:
    where = str(details.get("where") or "")
    summary = _compact_text(details.get("summary") or details.get("message") or where, TEXT_SUMMARY_LIMIT)
    target_files = details.get("target_files")
    if not isinstance(target_files, list):
        target_files = []
    recommended_resources = details.get("recommended_resources")
    if not isinstance(recommended_resources, list):
        recommended_resources = []
    issue_id = str(details.get("issue_id") or "")
    if not issue_id:
        raw = json.dumps(
            {
                "where": where,
                "path": details.get("path") or "",
                "target_files": target_files,
                "recommended_skill": details.get("recommended_skill") or "",
                "summary": summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        issue_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return {
        "issue_id": issue_id,
        "where": where,
        "summary": summary,
        "repair_hint": _compact_text(details.get("repair_hint") or "", TEXT_SUMMARY_LIMIT),
        "target_files": [str(item) for item in target_files[:8]],
        "recommended_skill": str(details.get("recommended_skill") or ""),
        "recommended_resources": [str(item) for item in recommended_resources[:8]],
    }


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
