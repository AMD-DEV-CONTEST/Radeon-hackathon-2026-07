"""EXP-001A module-private primitive and JSON helpers.

Under section 13.2 this module defines no public API. Canonical serialization,
strict parsing, canonical material, leaf primitive builders, and defensive
rebuild helpers are module-private implementation details outside the A/B ABI.
:mod:`specstyle.exporting.manifest` calls this module while validating input
model invariants and assembling documents in ``_prepare_export``.

Section 13.9 canonical JSON uses ``sort_keys``, compact separators,
``ensure_ascii=False``, ``allow_nan=False``, no BOM or trailing newline, and
recursive normalization of ``-0.0`` to ``0.0``. The strict parser rejects
duplicate keys, NaN/Infinity, and unknown or missing keys, and requires parsed
primitives to re-dump to the original bytes. Canonical material reproduces
``repair.history._canonical`` semantics for cross-object compiled Spec material
comparison under section 13.4.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from typing import Any

from specstyle.domain.artifacts import ArtifactRef, AssetRef
from specstyle.domain.enums import StaticApplicability
from specstyle.domain.identifiers import (
    ArtifactId,
    AssetId,
    DecisionId,
    Identifier,
    RuleId,
    Sha256,
)
from specstyle.errors import DomainError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationParameters, GenerationRequest
from specstyle.generation.seed_policy import SeedSnapshot
from specstyle.observability.environment import (
    DeviceInventory,
    DeviceSnapshot,
    EnvironmentSnapshot,
    IntegerObservation,
    TextObservation,
)
from specstyle.repair.history import RepairHistory
from specstyle.repair.loop import RepairTerminal
from specstyle.repair.models import NoAction, RepairDecision, RepairPatch
from specstyle.spec.compiled_models import (
    CompiledExecutionGraph,
    CompiledRule,
    CompiledStyleSpec,
    CompiledThresholdBinding,
    CompiledVerificationPlan,
    ResolvedModel,
    ResolvedRuntime,
    ResourcePin,
)
from specstyle.verification.rule_models import (
    ArtifactDecision,
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)

QA_REPORT_SCHEMA_VERSION = "specstyle.export.qa_report.v1"
MANIFEST_SCHEMA_VERSION = "specstyle.export.manifest.v1"
ASSET_CREDITS_SCHEMA_VERSION = "specstyle.export.asset_credits.v1"
PAYLOAD_DOMAIN = "specstyle.export.payload.v1"
BUNDLE_DOMAIN = "specstyle.export.bundle.v1"
STYLE_SPEC_PATH = "style_spec.yaml"
MANIFEST_PATH = "manifest.json"
QA_REPORT_PATH = "qa_report.json"
ASSET_CREDITS_PATH = "asset_credits.json"
ENVIRONMENT_PATH = "environment.json"
_OUTPUT_RANK = ("xhs_grid", "talking_head_cover", "background_sequence")
_CREDIT_ROLE_ORDER = ("input", "style_reference")
_PROVENANCE_FIELDS = ("source_url", "license", "attribution", "consent")
_METRIC_KEYS = (
    "between_profile_separation",
    "content_diversity",
    "duplicate_rate",
    "style_fidelity",
    "technical_failure_rate",
    "within_batch_style_dispersion",
)


# --------------------------------------------------------------------------- #
# Canonical JSON + strict parser (§13.9)
# --------------------------------------------------------------------------- #


def _normalize(value: Any) -> Any:
    """Recursively normalize ``-0.0`` to ``0.0`` and preserve other values."""
    if type(value) is float:
        return 0.0 if value == 0.0 else value
    if type(value) is dict:
        return {key: _normalize(item) for key, item in value.items()}
    if type(value) is list:
        return [_normalize(item) for item in value]
    return value


def canonical_json_bytes(primitive: Any) -> bytes:
    """Section 13.9 canonical JSON bytes."""
    return json.dumps(
        _normalize(primitive),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str or key in seen:
            raise DomainError("export invariant violation")
        seen.add(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise DomainError("export invariant violation")


def parse_strict(data: bytes) -> Any:
    """Strict JSON parsing that rejects duplicate keys and NaN/Infinity."""
    if type(data) is not bytes:
        raise DomainError("export invariant violation")
    try:
        return json.loads(
            data,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError:
        raise DomainError("export invariant violation") from None
    except json.JSONDecodeError:
        raise DomainError("export invariant violation") from None


def assert_canonical_round_trip(data: bytes) -> None:
    """Require a parsed primitive to re-dump to the original bytes."""
    parsed = parse_strict(data)
    if canonical_json_bytes(parsed) != data:
        raise DomainError("export invariant violation")


# --------------------------------------------------------------------------- #
# Canonical material (section 13.4, reproducing repair.history._canonical semantics)
# --------------------------------------------------------------------------- #


def _text(value: object) -> str:
    if type(value) is not str:
        raise DomainError("invalid export request")
    return str.__str__(value)


def canonical_material(value: object) -> tuple[object, ...]:
    """Type-tagged material matching repair history canonical semantics."""
    if value is None:
        return ("none",)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if type(value) is float:
        return ("float", value.hex())
    if type(value) is str:
        return ("str", str.__str__(value))
    if type(value) is bytes:
        return ("bytes", bytes(value))
    if type(value) is Sha256 or isinstance(value, Identifier):
        return (
            "identifier",
            type(value).__module__,
            type(value).__qualname__,
            _text(value.value),
        )
    if isinstance(value, enum.Enum):
        return (
            "enum",
            type(value).__module__,
            type(value).__qualname__,
            _text(value.value),
        )
    if type(value) is tuple:
        return ("tuple", tuple(canonical_material(item) for item in value))
    if type(value) is list:
        return ("list", tuple(canonical_material(item) for item in value))
    if type(value) is dict:
        pairs = tuple(
            (canonical_material(key), canonical_material(item))
            for key, item in value.items()
        )
        return ("dict", tuple(sorted(pairs, key=repr)))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _dataclass_material(value)
    if hasattr(type(value), "model_fields"):
        return _model_material(value)
    raise DomainError("invalid export request")


def _dataclass_material(value: object) -> tuple[object, ...]:
    return (
        "dataclass",
        type(value).__module__,
        type(value).__qualname__,
        tuple(
            (item.name, canonical_material(getattr(value, item.name)))
            for item in dataclasses.fields(value)
        ),
    )


def _model_material(value: object) -> tuple[object, ...]:
    names = tuple(type(value).model_fields)
    return (
        "model",
        type(value).__module__,
        type(value).__qualname__,
        tuple((name, canonical_material(getattr(value, name))) for name in names),
    )


# --------------------------------------------------------------------------- #
# Defensive rebuild helpers (section 13.2; trust neither caches nor equality)
# --------------------------------------------------------------------------- #


def _raise_invalid_request() -> None:
    raise DomainError("invalid export request") from None


def _rebuild_identifier(value: object, kind: type[Identifier]) -> Identifier:
    if type(value) is not kind or type(value.value) is not str:
        _raise_invalid_request()
    rebuilt = kind(str.__str__(value.value))
    if rebuilt.value != value.value or rebuilt != value:
        _raise_invalid_request()
    return rebuilt


def _rebuild_sha256(value: object) -> Sha256:
    if type(value) is not Sha256 or type(value.value) is not str:
        _raise_invalid_request()
    rebuilt = Sha256(str.__str__(value.value))
    if rebuilt.value != value.value:
        _raise_invalid_request()
    return rebuilt


def rebuild_asset_ref(value: object) -> AssetRef:
    if type(value) is not AssetRef:
        _raise_invalid_request()
    return AssetRef(
        _rebuild_identifier(value.asset_id, AssetId),
        _rebuild_sha256(value.sha256),
    )


def _rebuild_artifact_ref(value: object) -> ArtifactRef:
    if type(value) is not ArtifactRef:
        _raise_invalid_request()
    return ArtifactRef(
        _rebuild_identifier(value.artifact_id, ArtifactId),
        _rebuild_sha256(value.sha256),
    )


def _rebuild_resource_pin(value: object) -> ResourcePin:
    if type(value) is not ResourcePin:
        _raise_invalid_request()
    rebuilt = ResourcePin(
        _text(value.id), _text(value.revision), _rebuild_sha256(value.sha256)
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_text_observation(value: object) -> TextObservation:
    if type(value) is not TextObservation:
        _raise_invalid_request()
    rebuilt = TextObservation(value.status, value.value, value.reason)
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_integer_observation(value: object) -> IntegerObservation:
    if type(value) is not IntegerObservation:
        _raise_invalid_request()
    rebuilt = IntegerObservation(value.status, value.value, value.reason)
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_device_snapshot(value: object) -> DeviceSnapshot:
    if type(value) is not DeviceSnapshot or type(value.index) is not int:
        _raise_invalid_request()
    rebuilt = DeviceSnapshot(
        value.index,
        _rebuild_text_observation(value.name),
        _rebuild_integer_observation(value.total_memory_bytes),
        _rebuild_text_observation(value.gfx_arch),
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_device_inventory(value: object) -> DeviceInventory:
    if type(value) is not DeviceInventory or type(value.devices) is not tuple:
        _raise_invalid_request()
    rebuilt = DeviceInventory(
        value.status,
        value.reason,
        tuple(_rebuild_device_snapshot(item) for item in value.devices),
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def rebuild_environment(value: object) -> EnvironmentSnapshot:
    if type(value) is not EnvironmentSnapshot:
        _raise_invalid_request()
    try:
        rebuilt = EnvironmentSnapshot(
            value.schema_version,
            _rebuild_text_observation(value.os_name),
            _rebuild_text_observation(value.os_release),
            _rebuild_text_observation(value.kernel_version),
            _rebuild_text_observation(value.machine),
            _rebuild_text_observation(value.python_implementation),
            _rebuild_text_observation(value.python_version),
            _rebuild_text_observation(value.rocm_version),
            _rebuild_text_observation(value.hip_version),
            _rebuild_text_observation(value.pytorch_version),
            _rebuild_text_observation(value.diffusers_version),
            _rebuild_device_inventory(value.hip_devices),
        )
    except Exception:
        _raise_invalid_request()
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_gate_policy(value: object) -> GatePolicy:
    if type(value) is not GatePolicy:
        _raise_invalid_request()
    rebuilt = GatePolicy(value.on_fail, value.on_unverifiable, value.on_warning)
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_rule_definition(value: object) -> RuleDefinition:
    if type(value) is not RuleDefinition:
        _raise_invalid_request()
    rebuilt = RuleDefinition(
        _rebuild_identifier(value.rule_id, RuleId),
        value.level,
        value.scope,
        value.required,
        value.applicability,
        _rebuild_gate_policy(value.gate_policy),
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_rule_result(value: object) -> RuleResult:
    if type(value) is not RuleResult or type(value.affected_artifact_ids) is not tuple:
        _raise_invalid_request()
    rebuilt = RuleResult(
        _rebuild_identifier(value.rule_id, RuleId),
        value.status,
        tuple(
            _rebuild_identifier(item, ArtifactId)
            for item in value.affected_artifact_ids
        ),
        value.score,
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def rebuild_verification_report(value: object) -> VerificationReport:
    if (
        type(value) is not VerificationReport
        or type(value.artifacts) is not tuple
        or type(value.rules) is not tuple
        or type(value.results) is not tuple
    ):
        _raise_invalid_request()
    try:
        rebuilt = VerificationReport(
            tuple(_rebuild_artifact_ref(item) for item in value.artifacts),
            tuple(_rebuild_rule_definition(item) for item in value.rules),
            tuple(_rebuild_rule_result(item) for item in value.results),
        )
    except Exception:
        _raise_invalid_request()
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_repair_patch(value: object) -> RepairPatch:
    if type(value) is not RepairPatch:
        _raise_invalid_request()
    rebuilt = RepairPatch(
        value.before_parameters,
        value.after_parameters,
        value.before_variation_index,
        value.after_variation_index,
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_repair_decision(value: object) -> RepairDecision:
    if type(value) is not RepairDecision:
        _raise_invalid_request()
    rebuilt = RepairDecision(
        _rebuild_identifier(value.decision_id, DecisionId),
        value.policy_version,
        _rebuild_identifier(value.trigger_rule_id, RuleId),
        _rebuild_identifier(value.action_id, Identifier),
        _rebuild_repair_patch(value.patch),
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_no_action(value: object) -> NoAction | None:
    if value is None:
        return None
    if type(value) is not NoAction or type(value.blocked_rule_ids) is not tuple:
        _raise_invalid_request()
    rebuilt = NoAction(
        _rebuild_identifier(value.decision_id, DecisionId),
        tuple(_rebuild_identifier(item, RuleId) for item in value.blocked_rule_ids),
        tuple(
            _rebuild_identifier(item, Identifier) for item in value.blocked_action_ids
        ),
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def _rebuild_artifact_decision(value: object) -> ArtifactDecision:
    if type(value) is not ArtifactDecision:
        _raise_invalid_request()
    rebuilt = ArtifactDecision(
        _rebuild_identifier(value.artifact_id, ArtifactId),
        value.artifact_status,
        value.decision_reason,
        value.repair_stop_reason,
        value.accepted_with_override,
    )
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def rebuild_repair_terminal(value: object) -> RepairTerminal:
    if type(value) is not RepairTerminal:
        _raise_invalid_request()
    try:
        rebuilt = RepairTerminal(
            _rebuild_artifact_decision(value.artifact_decision),
            _rebuild_no_action(value.no_action),
        )
    except Exception:
        _raise_invalid_request()
    if canonical_material(rebuilt) != canonical_material(value):
        _raise_invalid_request()
    return rebuilt


def rebuild_repair_history(value: object) -> RepairHistory:
    if (
        type(value) is not RepairHistory
        or type(value.repair_attempts) is not tuple
        or type(value.seen_state_keys) is not tuple
    ):
        _raise_invalid_request()
    try:
        rebuilt = RepairHistory(value.initial_attempt, value.repair_attempts)
    except Exception:
        _raise_invalid_request()
    if (
        type(value.rounds) is not int
        or value.rounds != rebuilt.rounds
        or type(value.consecutive_no_improvement) is not int
        or value.consecutive_no_improvement != rebuilt.consecutive_no_improvement
        or canonical_material(value.seen_state_keys)
        != canonical_material(rebuilt.seen_state_keys)
    ):
        _raise_invalid_request()
    return rebuilt


def rebuild_compiled_spec(value: object) -> CompiledStyleSpec:
    """Rebuild and validate the computed compiled_spec_hash under section 13.4."""
    if type(value) is not CompiledStyleSpec:
        _raise_invalid_request()
    try:
        rebuilt = CompiledStyleSpec(
            value.source_spec,
            _rebuild_resource_pin(value.compiler_pin),
            _rebuild_resource_pin(value.ruleset_pin),
            value.l2_encoder,
            value.preview_graphs,
            value.production_graphs,
            value.verification_plans,
        )
    except Exception:
        _raise_invalid_request()
    if rebuilt.compiled_spec_hash != value.compiled_spec_hash:
        _raise_invalid_request()
    return rebuilt


# --------------------------------------------------------------------------- #
# Leaf primitive builders (§13.5)
# --------------------------------------------------------------------------- #


def _finite(value: float) -> float:
    if (
        type(value) is not float
        or value != value
        or value in (float("inf"), float("-inf"))
    ):
        raise DomainError("export invariant violation")
    return 0.0 if value == 0.0 else value


def _sha_value(value: Sha256) -> str:
    rebuilt = _rebuild_sha256(value)
    return rebuilt.value


def _identifier_value(value: Identifier) -> str:
    return str.__str__(value.value)


def pin_primitive(value: ResourcePin) -> dict[str, Any]:
    rebuilt = _rebuild_resource_pin(value)
    return {
        "id": rebuilt.id,
        "revision": rebuilt.revision,
        "sha256": rebuilt.sha256.value,
    }


def asset_ref_primitive(value: AssetRef) -> dict[str, Any]:
    rebuilt = rebuild_asset_ref(value)
    return {
        "asset_id": rebuilt.asset_id.value,
        "sha256": rebuilt.sha256.value,
    }


def artifact_ref_primitive(value: ArtifactRef) -> dict[str, Any]:
    rebuilt = _rebuild_artifact_ref(value)
    return {
        "artifact_id": rebuilt.artifact_id.value,
        "sha256": rebuilt.sha256.value,
    }


def file_entry(path: str, sha256: Sha256, size_bytes: int) -> dict[str, Any]:
    if (
        type(path) is not str
        or type(size_bytes) is not int
        or isinstance(size_bytes, bool)
    ):
        raise DomainError("export invariant violation")
    return {"path": path, "sha256": _sha_value(sha256), "size_bytes": size_bytes}


def parameters_primitive(value: GenerationParameters) -> dict[str, Any]:
    if type(value) is not GenerationParameters:
        raise DomainError("export invariant violation")
    return {
        "controlnet_scale": _finite(value.controlnet_scale),
        "img2img_strength": _finite(value.img2img_strength),
        "ip_adapter_scale": _finite(value.ip_adapter_scale),
    }


def gate_policy_primitive(value: GatePolicy) -> dict[str, Any]:
    rebuilt = _rebuild_gate_policy(value)
    return {
        "on_fail": rebuilt.on_fail,
        "on_unverifiable": rebuilt.on_unverifiable,
        "on_warning": rebuilt.on_warning,
    }


def seed_primitive(value: SeedSnapshot) -> dict[str, Any]:
    if type(value) is not SeedSnapshot:
        raise DomainError("export invariant violation")
    return {
        "algorithm": value.algorithm,
        "compiled_spec_hash": value.compiled_spec_hash.value,
        "output_profile": value.output_profile,
        "seed": value.seed,
        "source_sha256": value.source_sha256.value,
        "variation_index": value.variation_index,
    }


def runtime_primitive(value: ResolvedRuntime) -> dict[str, Any]:
    if type(value) is not ResolvedRuntime:
        raise DomainError("export invariant violation")
    return {
        "backend": value.backend,
        "diffusers_version": value.diffusers_version,
        "dtype": value.dtype,
        "pin": pin_primitive(value.pin),
        "rocm_version": value.rocm_version,
        "torch_version": value.torch_version,
    }


def _model_primitive(value: ResolvedModel) -> dict[str, Any]:
    if type(value) is not ResolvedModel:
        raise DomainError("export invariant violation")
    return pin_primitive(value.pin)


def graph_primitive(value: CompiledExecutionGraph) -> dict[str, Any]:
    return _graph_primitive(value)


def _graph_primitive(graph: CompiledExecutionGraph) -> dict[str, Any]:
    if type(graph) is not CompiledExecutionGraph or type(graph.resolution) is not tuple:
        raise DomainError("export invariant violation")
    if len(graph.resolution) != 2 or any(
        type(item) is not int or isinstance(item, bool) for item in graph.resolution
    ):
        raise DomainError("export invariant violation")
    primitive = {
        "base_model": _model_primitive(graph.base_model),
        "batch_execution": graph.batch_execution,
        "controlnet": {
            "pin": pin_primitive(graph.controlnet.pin),
            "type": graph.controlnet.controlnet_type,
        },
        "guidance_scale": _finite(graph.guidance_scale),
        "ip_adapter": _model_primitive(graph.ip_adapter),
        "output_profile": graph.output_profile,
        "output_profile_pin": pin_primitive(graph.output_profile_pin),
        "pipeline": graph.pipeline,
        "resolution": [graph.resolution[0], graph.resolution[1]],
        "runtime": runtime_primitive(graph.runtime),
        "scheduler": graph.scheduler,
        "seed_policy": graph.seed_policy,
        "steps": graph.steps,
        "strength_mapping_pin": pin_primitive(graph.strength_mapping_pin),
    }
    if graph.render_contract is not None:
        contract = graph.render_contract
        render_primitive = {
            "background": list(contract.background),
            "final_resolution": list(contract.final_resolution),
            "fit": contract.fit,
            "overlay": contract.overlay,
            "resampling": contract.resampling,
            "sequence_semantics": contract.sequence_semantics,
        }
        if contract.native_resolution is not None:
            render_primitive["native_resolution"] = list(contract.native_resolution)
        primitive["render_contract"] = render_primitive
    return primitive


def attempt_primitive(
    request: GenerationRequest, artifact: GeneratedArtifact
) -> dict[str, Any]:
    if (
        type(request) is not GenerationRequest
        or type(artifact) is not GeneratedArtifact
    ):
        raise DomainError("export invariant violation")
    if type(request.style_references) is not tuple:
        raise DomainError("export invariant violation")
    return {
        "artifact": artifact_ref_primitive(artifact.ref),
        "attempt_id": request.attempt_id.value,
        "environment_sha256": request.environment_hash.value,
        "generation_fingerprint_sha256": request.generation_fingerprint.value,
        "generation_profile": request.generation_profile,
        "graph": _graph_primitive(request.graph),
        "parameters": parameters_primitive(request.execution_parameters),
        "parent_attempt_id": (
            None
            if request.parent_attempt_id is None
            else request.parent_attempt_id.value
        ),
        "request_sha256": request.request_hash.value,
        "seed": seed_primitive(request.seed),
        "style_references": [
            asset_ref_primitive(item) for item in request.style_references
        ],
        "variation_index": request.variation_index,
    }


def patch_primitive(value: RepairPatch) -> dict[str, Any]:
    rebuilt = _rebuild_repair_patch(value)
    return {
        "after_parameters": parameters_primitive(rebuilt.after_parameters),
        "after_variation_index": rebuilt.after_variation_index,
        "before_parameters": parameters_primitive(rebuilt.before_parameters),
        "before_variation_index": rebuilt.before_variation_index,
    }


def decision_primitive(value: RepairDecision) -> dict[str, Any]:
    rebuilt = _rebuild_repair_decision(value)
    return {
        "action_id": rebuilt.action_id.value,
        "decision_id": rebuilt.decision_id.value,
        "patch": patch_primitive(rebuilt.patch),
        "policy_version": rebuilt.policy_version,
        "trigger_rule_id": rebuilt.trigger_rule_id.value,
    }


def no_action_primitive(value: NoAction | None) -> dict[str, Any] | None:
    if value is None:
        return None
    rebuilt = _rebuild_no_action(value)
    if rebuilt is None:  # pragma: no cover - defensive
        return None
    return {
        "blocked_action_ids": [item.value for item in rebuilt.blocked_action_ids],
        "blocked_rule_ids": [item.value for item in rebuilt.blocked_rule_ids],
        "decision_id": rebuilt.decision_id.value,
        "stop_reason": rebuilt.stop_reason.value,
    }


def threshold_primitive(
    value: CompiledThresholdBinding | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not CompiledThresholdBinding:
        raise DomainError("export invariant violation")
    return {
        "annotation_protocol_sha256": value.annotation_protocol_sha256.value,
        "calibration_dataset_sha256": value.calibration_dataset_sha256.value,
        "logical_name": value.logical_name,
        "metric_id": value.metric_id.value,
        "operator": value.operator,
        "profile_pin": pin_primitive(value.profile_pin),
        "production_approval_sha256": (
            None
            if value.production_approval_sha256 is None
            else value.production_approval_sha256.value
        ),
        "status": value.status,
        "validation_dataset_sha256": value.validation_dataset_sha256.value,
        "value": _finite(value.value),
    }


def _rule_primitive(rule: CompiledRule, definition: RuleDefinition) -> dict[str, Any]:
    if canonical_material(rule.definition) != canonical_material(definition):
        raise DomainError("export invariant violation")
    return {
        "affected_by_actions": [item.value for item in rule.affected_by_actions],
        "applicability": definition.applicability.value,
        "gate_policy": gate_policy_primitive(definition.gate_policy),
        "level": definition.level.value,
        "metric_id": None if rule.metric_id is None else rule.metric_id.value,
        "priority": rule.priority,
        "required": definition.required,
        "rule_id": definition.rule_id.value,
        "scope": definition.scope.value,
        "threshold": threshold_primitive(rule.threshold_binding),
        "verifier_pin": pin_primitive(rule.verifier_pin),
    }


def _result_primitive(value: RuleResult) -> dict[str, Any]:
    rebuilt = _rebuild_rule_result(value)
    return {
        "affected_artifact_ids": [item.value for item in rebuilt.affected_artifact_ids],
        "rule_id": rebuilt.rule_id.value,
        "score": None if rebuilt.score is None else _finite(rebuilt.score),
        "status": rebuilt.status.value,
    }


def report_primitive(
    report: VerificationReport, plan: CompiledVerificationPlan
) -> dict[str, Any]:
    """Build ``Report`` by joining each ``RuleDefinition`` and ``CompiledRule``."""
    rebuilt = rebuild_verification_report(report)
    by_id = {rule.definition.rule_id.value: rule for rule in plan.rules}
    applicable_ids = {
        rule.definition.rule_id.value
        for rule in plan.rules
        if rule.definition.applicability is StaticApplicability.APPLICABLE
    }
    if {rule.rule_id.value for rule in rebuilt.rules} != applicable_ids:
        raise DomainError("export invariant violation")
    rules = [
        _rule_primitive(by_id[definition.rule_id.value], definition)
        for definition in sorted(rebuilt.rules, key=lambda item: item.rule_id.value)
    ]
    results = [
        _result_primitive(item)
        for item in sorted(
            rebuilt.results,
            key=lambda item: (
                item.rule_id.value,
                tuple(affected.value for affected in item.affected_artifact_ids),
            ),
        )
    ]
    return {
        "artifacts": [artifact_ref_primitive(item) for item in rebuilt.artifacts],
        "results": results,
        "rules": rules,
    }


def verification_plan_primitive(plan: CompiledVerificationPlan) -> dict[str, Any]:
    if type(plan) is not CompiledVerificationPlan:
        raise DomainError("export invariant violation")
    return {
        "l3_plugin_pin": (
            None if plan.l3_plugin_pin is None else pin_primitive(plan.l3_plugin_pin)
        ),
        "l3_reason": plan.l3_reason,
        "l3_status": plan.l3_status,
        "l3_threshold_profile_pin": (
            None
            if plan.l3_threshold_profile_pin is None
            else pin_primitive(plan.l3_threshold_profile_pin)
        ),
        "output_profile_pin": pin_primitive(plan.output_profile_pin),
    }


def final_decision_primitive(decision: ArtifactDecision) -> dict[str, Any]:
    rebuilt = _rebuild_artifact_decision(decision)
    if rebuilt.repair_stop_reason is None:
        raise DomainError("export invariant violation") from None
    return {
        "accepted_with_override": rebuilt.accepted_with_override,
        "artifact_id": rebuilt.artifact_id.value,
        "artifact_status": rebuilt.artifact_status.value,
        "decision_reason": rebuilt.decision_reason.value,
        "repair_stop_reason": rebuilt.repair_stop_reason.value,
    }


def repair_round_primitive(
    *,
    index: int,
    parent_report: VerificationReport,
    decision: RepairDecision,
    request: GenerationRequest,
    artifact: GeneratedArtifact,
    report: VerificationReport,
    plan: CompiledVerificationPlan,
) -> dict[str, Any]:
    return {
        "attempt": attempt_primitive(request, artifact),
        "decision": decision_primitive(decision),
        "index": index,
        "parent_report": report_primitive(parent_report, plan),
        "report": report_primitive(report, plan),
    }


def manifest_item_primitive(
    *,
    history: RepairHistory,
    terminal: RepairTerminal,
    sequence_index: int | None,
    output_profile: str,
    plan: CompiledVerificationPlan,
    relative_path: str,
    content_size: int,
    artifact_sha256: Sha256,
) -> dict[str, Any]:
    initial = history.initial_attempt
    rounds = [
        repair_round_primitive(
            index=number,
            parent_report=attempt.parent_report,
            decision=attempt.decision,
            request=attempt.request,
            artifact=attempt.artifact,
            report=attempt.report,
            plan=plan,
        )
        for number, attempt in enumerate(history.repair_attempts, start=1)
    ]
    return {
        "final_artifact": {
            "artifact_id": terminal.artifact_decision.artifact_id.value,
            "relative_path": relative_path,
            "sha256": artifact_sha256.value,
            "size_bytes": content_size,
        },
        "final_decision": final_decision_primitive(terminal.artifact_decision),
        "initial_attempt": attempt_primitive(initial.request, initial.artifact),
        "initial_report": report_primitive(initial.report, plan),
        "input_asset": asset_ref_primitive(initial.request.source.source),
        "no_action": no_action_primitive(terminal.no_action),
        "output_profile": output_profile,
        "repair_rounds": rounds,
        "sequence_index": sequence_index,
    }


# --------------------------------------------------------------------------- #
# QA report assembly (§13.7)
# --------------------------------------------------------------------------- #


def _not_provided_metric() -> dict[str, Any]:
    return {
        "availability": "NOT_PROVIDED",
        "reason": "UPSTREAM_AGGREGATE_NOT_IN_CONTRACT",
        "value": None,
    }


def _metrics() -> dict[str, Any]:
    return {name: _not_provided_metric() for name in _METRIC_KEYS}


def build_qa_report(
    *,
    spec: dict[str, Any],
    cohorts: list[dict[str, Any]],
    job_id: str,
) -> dict[str, Any]:
    """Assemble the canonical ``qa_report.json`` with fixed NOT_PROVIDED metrics."""
    return {
        "cohorts": cohorts,
        "job_id": job_id,
        "metrics": _metrics(),
        "schema_version": QA_REPORT_SCHEMA_VERSION,
        "spec": spec,
    }
