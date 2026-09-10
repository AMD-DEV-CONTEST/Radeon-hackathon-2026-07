"""Strict immutable inputs and outputs for the pure SPEC-003 compiler."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from specstyle.domain.enums import RuleLevel, RuleScope, StaticApplicability
from specstyle.domain.identifiers import Identifier, RuleId, Sha256
from specstyle.errors import DomainError
from specstyle.spec.models import StyleSpec, StyleSpecV1, StyleSpecV11
from specstyle.verification.rule_models import RuleDefinition

DomainProfile = Literal["product_instance", "face_identity", "structure_only"]
OutputProfile = Literal["xhs_grid", "talking_head_cover", "background_sequence"]
GenerationProfile = Literal["preview", "production"]
Pipeline = Literal["sdxl_turbo", "lcm", "sdxl_base"]
ModelRole = Literal["base", "ip_adapter", "controlnet"]
RuleKind = Literal[
    "L1_TECHNICAL",
    "L2_STYLE_FIDELITY",
    "L2_BATCH_CONSISTENCY",
    "L3_DOMAIN_FIDELITY",
    "L3_DIAGNOSTIC",
]
RequirementMode = Literal["always_required", "always_advisory", "fidelity_required"]
ThresholdSource = Literal["none", "l2", "l3"]
ThresholdStatus = Literal["DRAFT", "CALIBRATED", "VALIDATED", "REVOKED"]
ThresholdOperator = Literal[">=", "<="]
L3PlanStatus = Literal["APPLICABLE", "NOT_APPLICABLE"]
L3NotApplicableReason = Literal["NO_L3_CONFIG", "NO_APPLICABLE_RULE"]

_DOMAINS = {"product_instance", "face_identity", "structure_only"}
_OUTPUTS = {"xhs_grid", "talking_head_cover", "background_sequence"}
_PIPELINES = {"sdxl_turbo", "lcm", "sdxl_base"}
_DTYPES = {"float16", "bfloat16"}
_KINDS = {
    "L1_TECHNICAL",
    "L2_STYLE_FIDELITY",
    "L2_BATCH_CONSISTENCY",
    "L3_DOMAIN_FIDELITY",
    "L3_DIAGNOSTIC",
}


def _text(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 2048
        or value != value.strip()
        or any(ord(c) <= 31 or ord(c) == 127 for c in value)
    ):
        raise DomainError(f"{name} must be SafeText")


def _choice(value: object, choices: set[str], name: str) -> None:
    if type(value) is not str or value not in choices:
        raise DomainError(f"invalid {name}")


def _tuple(value: object, name: str, *, nonempty: bool = False) -> tuple[object, ...]:
    if type(value) is not tuple or (nonempty and not value):
        raise DomainError(f"{name} must be {'nonempty ' if nonempty else ''}tuple")
    return value


def _unique(values: tuple[object, ...], name: str) -> None:
    try:
        duplicate = len(set(values)) != len(values)
    except TypeError as exc:
        raise DomainError(f"{name} members must be hashable") from exc
    if duplicate:
        raise DomainError(f"{name} must be unique")


def _finite(value: object, name: str, *, unit: bool = False) -> None:
    if (
        type(value) is not float
        or not math.isfinite(value)
        or (unit and not 0 <= value <= 1)
    ):
        raise DomainError(f"{name} must be {'[0,1] ' if unit else ''}finite float")


def _identifier(value: object, name: str, cls: type[Identifier] = Identifier) -> None:
    if type(value) is not cls:
        raise DomainError(f"{name} must be {cls.__name__}")


@dataclass(frozen=True, slots=True)
class ResourcePin:
    id: str
    revision: str
    sha256: Sha256

    def __post_init__(self) -> None:
        _text(self.id, "id")
        _text(self.revision, "revision")
        if type(self.sha256) is not Sha256:
            raise DomainError("sha256 must be Sha256")


@dataclass(frozen=True, slots=True)
class RuntimeCapability:
    pin: ResourcePin
    backend: Literal["rocm"]
    rocm_version: str
    torch_version: str
    diffusers_version: str
    dtype: Literal["float16", "bfloat16"]

    def __post_init__(self) -> None:
        if type(self.pin) is not ResourcePin:
            raise DomainError("runtime pin must be ResourcePin")
        _choice(self.backend, {"rocm"}, "backend")
        for name in ("rocm_version", "torch_version", "diffusers_version"):
            _text(getattr(self, name), name)
        _choice(self.dtype, _DTYPES, "dtype")


@dataclass(frozen=True, slots=True)
class ModelCapability:
    role: ModelRole
    pin: ResourcePin
    controlnet_type: Literal["canny", "depth", "pose"] | None
    supported_pipelines: tuple[Pipeline, ...]
    supported_dtypes: tuple[Literal["float16", "bfloat16"], ...]
    supported_runtime_hashes: tuple[Sha256, ...]

    def __post_init__(self) -> None:
        _choice(self.role, {"base", "ip_adapter", "controlnet"}, "model role")
        if type(self.pin) is not ResourcePin:
            raise DomainError("model pin must be ResourcePin")
        if (self.role == "controlnet") != (self.controlnet_type is not None):
            raise DomainError("controlnet role/type mismatch")
        if self.controlnet_type is not None:
            _choice(self.controlnet_type, {"canny", "depth", "pose"}, "controlnet type")
        for value, name, choices in (
            (self.supported_pipelines, "pipelines", _PIPELINES),
            (self.supported_dtypes, "dtypes", _DTYPES),
        ):
            values = _tuple(value, name, nonempty=True)
            _unique(values, name)
            for member in values:
                _choice(member, choices, name)
        hashes = _tuple(self.supported_runtime_hashes, "runtime hashes", nonempty=True)
        _unique(hashes, "runtime hashes")
        if any(type(item) is not Sha256 for item in hashes):
            raise DomainError("runtime hashes must contain Sha256")


@dataclass(frozen=True, slots=True)
class EncoderCapability:
    pin: ResourcePin
    preprocessing_version: str
    layer: str
    distance_function: str
    supported_runtime_hashes: tuple[Sha256, ...]

    def __post_init__(self) -> None:
        if type(self.pin) is not ResourcePin:
            raise DomainError("encoder pin must be ResourcePin")
        for name in ("preprocessing_version", "layer", "distance_function"):
            _text(getattr(self, name), name)
        hashes = _tuple(self.supported_runtime_hashes, "runtime hashes", nonempty=True)
        _unique(hashes, "runtime hashes")
        if any(type(item) is not Sha256 for item in hashes):
            raise DomainError("runtime hashes must contain Sha256")


@dataclass(frozen=True, slots=True)
class StrengthMappingEntry:
    user_strength: float
    preview_ip_adapter_scale: float
    production_ip_adapter_scale: float

    def __post_init__(self) -> None:
        _finite(self.user_strength, "user_strength", unit=True)
        _finite(self.preview_ip_adapter_scale, "preview scale", unit=True)
        _finite(self.production_ip_adapter_scale, "production scale", unit=True)


@dataclass(frozen=True, slots=True)
class StrengthMappingCapability:
    pin: ResourcePin
    preset_id: Identifier
    entries: tuple[StrengthMappingEntry, ...]

    def __post_init__(self) -> None:
        if type(self.pin) is not ResourcePin:
            raise DomainError("mapping pin must be ResourcePin")
        _identifier(self.preset_id, "preset_id")
        entries = _tuple(self.entries, "mapping entries", nonempty=True)
        if len(entries) < 2 or any(
            type(entry) is not StrengthMappingEntry for entry in entries
        ):
            raise DomainError("mapping must have at least two entries")
        strengths = tuple(entry.user_strength for entry in entries)
        if (
            strengths[0] != 0.0
            or strengths[-1] != 1.0
            or any(a >= b for a, b in zip(strengths, strengths[1:]))
        ):
            raise DomainError("mapping strengths must strictly cover 0.0..1.0")
        for field_name in ("preview_ip_adapter_scale", "production_ip_adapter_scale"):
            values = tuple(getattr(entry, field_name) for entry in entries)
            if any(a > b for a, b in zip(values, values[1:])):
                raise DomainError("mapping scales must be nondecreasing")


@dataclass(frozen=True, slots=True)
class OutputRenderContract:
    final_resolution: tuple[int, int]
    fit: Literal["contain_pad", "contain_pad_center", "cover_center"]
    resampling: Literal["lanczos"]
    background: tuple[int, int, int]
    overlay: Literal["disabled"]
    sequence_semantics: Literal["single_static", "single_item_sequence_index_zero"]
    native_resolution: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        resolution = _tuple(
            self.final_resolution, "final output resolution", nonempty=True
        )
        background = _tuple(self.background, "output background", nonempty=True)
        native = self.native_resolution
        if (
            len(resolution) != 2
            or any(type(item) is not int or item < 1 for item in resolution)
            or len(background) != 3
            or any(type(item) is not int or not 0 <= item <= 255 for item in background)
        ):
            raise DomainError("invalid output render contract")
        if native is not None:
            native = _tuple(native, "native output resolution", nonempty=True)
            if len(native) != 2 or any(
                type(item) is not int or item < 1 for item in native
            ):
                raise DomainError("invalid output render contract")
        _choice(
            self.fit,
            {"contain_pad", "contain_pad_center", "cover_center"},
            "output fit",
        )
        _choice(self.resampling, {"lanczos"}, "output resampling")
        _choice(self.overlay, {"disabled"}, "output overlay")
        _choice(
            self.sequence_semantics,
            {"single_static", "single_item_sequence_index_zero"},
            "output sequence semantics",
        )


@dataclass(frozen=True, slots=True)
class OutputProfileCapability:
    pin: ResourcePin
    profile: OutputProfile
    supported_domains: tuple[DomainProfile, ...]
    supported_generation_profiles: tuple[GenerationProfile, ...]
    render_contract: OutputRenderContract | None = None

    def __post_init__(self) -> None:
        if type(self.pin) is not ResourcePin:
            raise DomainError("output pin must be ResourcePin")
        if (
            self.render_contract is not None
            and type(self.render_contract) is not OutputRenderContract
        ):
            raise DomainError("output render contract must be OutputRenderContract")
        _choice(self.profile, _OUTPUTS, "output profile")
        for values, name, choices in (
            (self.supported_domains, "domains", _DOMAINS),
            (
                self.supported_generation_profiles,
                "generation profiles",
                {"preview", "production"},
            ),
        ):
            items = _tuple(values, name, nonempty=True)
            _unique(items, name)
            for item in items:
                _choice(item, choices, name)


@dataclass(frozen=True, slots=True)
class ThresholdMetricCapability:
    metric_id: Identifier
    operator: ThresholdOperator
    value: float

    def __post_init__(self) -> None:
        _identifier(self.metric_id, "metric_id")
        _choice(self.operator, {">=", "<="}, "operator")
        _finite(self.value, "threshold value")


@dataclass(frozen=True, slots=True)
class ThresholdProfileCapability:
    pin: ResourcePin
    logical_name: str
    source: Literal["l2", "l3"]
    status: ThresholdStatus
    style_pack_id: Identifier
    domain_profile: DomainProfile
    encoder_pin: ResourcePin | None
    plugin_pin: ResourcePin | None
    metrics: tuple[ThresholdMetricCapability, ...]
    calibration_dataset_sha256: Sha256
    validation_dataset_sha256: Sha256
    annotation_protocol_sha256: Sha256
    production_approval_sha256: Sha256 | None = None

    def __post_init__(self) -> None:
        if type(self.pin) is not ResourcePin:
            raise DomainError("threshold pin must be ResourcePin")
        _text(self.logical_name, "logical_name")
        _choice(self.source, {"l2", "l3"}, "threshold source")
        _choice(
            self.status,
            {"DRAFT", "CALIBRATED", "VALIDATED", "REVOKED"},
            "threshold status",
        )
        _identifier(self.style_pack_id, "style_pack_id")
        _choice(self.domain_profile, _DOMAINS, "domain profile")
        if self.source == "l2" and (
            type(self.encoder_pin) is not ResourcePin or self.plugin_pin is not None
        ):
            raise DomainError("L2 threshold requires encoder pin only")
        if self.source == "l3" and (
            self.encoder_pin is not None or type(self.plugin_pin) is not ResourcePin
        ):
            raise DomainError("L3 threshold requires plugin pin only")
        metrics = _tuple(self.metrics, "threshold metrics", nonempty=True)
        if any(type(metric) is not ThresholdMetricCapability for metric in metrics):
            raise DomainError(
                "threshold metrics must contain ThresholdMetricCapability"
            )
        _unique(tuple(metric.metric_id for metric in metrics), "threshold metric ids")
        if any(
            type(item) is not Sha256
            for item in (
                self.calibration_dataset_sha256,
                self.validation_dataset_sha256,
                self.annotation_protocol_sha256,
            )
        ):
            raise DomainError("threshold dataset hashes must be Sha256")
        if (
            self.production_approval_sha256 is not None
            and type(self.production_approval_sha256) is not Sha256
        ):
            raise DomainError("threshold approval hash must be Sha256")


@dataclass(frozen=True, slots=True)
class RuleCapability:
    rule_id: RuleId
    kind: RuleKind
    level: RuleLevel
    scope: RuleScope
    requirement: RequirementMode
    supported_domains: tuple[DomainProfile, ...]
    supported_output_profiles: tuple[OutputProfile, ...]
    verifier_pin: ResourcePin
    threshold_source: ThresholdSource
    metric_id: Identifier | None
    priority: int
    affected_by_actions: tuple[Identifier, ...]

    def __post_init__(self) -> None:
        _identifier(self.rule_id, "rule_id", RuleId)
        _choice(self.kind, _KINDS, "rule kind")
        if type(self.level) is not RuleLevel or type(self.scope) is not RuleScope:
            raise DomainError("rule level/scope must be domain enums")
        _choice(
            self.requirement,
            {"always_required", "always_advisory", "fidelity_required"},
            "requirement",
        )
        for values, name, choices in (
            (self.supported_domains, "rule domains", _DOMAINS),
            (self.supported_output_profiles, "rule outputs", _OUTPUTS),
        ):
            items = _tuple(values, name, nonempty=True)
            _unique(items, name)
            for item in items:
                _choice(item, choices, name)
        if type(self.verifier_pin) is not ResourcePin:
            raise DomainError("verifier pin must be ResourcePin")
        _choice(self.threshold_source, {"none", "l2", "l3"}, "threshold source")
        if (self.threshold_source == "none") != (self.metric_id is None):
            raise DomainError("metric/source mismatch")
        if self.metric_id is not None:
            _identifier(self.metric_id, "metric_id")
        if (
            type(self.priority) is not int
            or isinstance(self.priority, bool)
            or self.priority < 0
        ):
            raise DomainError("priority must be nonnegative int")
        actions = _tuple(self.affected_by_actions, "affected actions")
        if any(type(action) is not Identifier for action in actions):
            raise DomainError("affected actions must contain Identifier")
        _unique(actions, "affected actions")
        fixed = {
            "L2_STYLE_FIDELITY": (RuleLevel.L2, RuleScope.ITEM),
            "L2_BATCH_CONSISTENCY": (RuleLevel.L2, RuleScope.BATCH),
            "L1_TECHNICAL": (RuleLevel.L1, None),
        }
        if self.kind in fixed and (
            self.level != fixed[self.kind][0]
            or (fixed[self.kind][1] is not None and self.scope != fixed[self.kind][1])
        ):
            raise DomainError("rule kind/level/scope mismatch")
        if self.kind.startswith("L3_") and self.level is not RuleLevel.L3:
            raise DomainError("L3 rule must be L3")
        if self.threshold_source != "none" and (
            (self.threshold_source == "l2" and self.level is not RuleLevel.L2)
            or (self.threshold_source == "l3" and self.level is not RuleLevel.L3)
        ):
            raise DomainError("threshold source/level mismatch")


@dataclass(frozen=True, slots=True)
class RuleCatalogCapability:
    ruleset_version: str
    pin: ResourcePin
    rules: tuple[RuleCapability, ...]

    def __post_init__(self) -> None:
        _text(self.ruleset_version, "ruleset_version")
        if type(self.pin) is not ResourcePin:
            raise DomainError("ruleset pin must be ResourcePin")
        rules = _tuple(self.rules, "catalog rules", nonempty=True)
        if any(type(rule) is not RuleCapability for rule in rules):
            raise DomainError("catalog rules must contain RuleCapability")
        _unique(tuple(rule.rule_id for rule in rules), "catalog rule ids")


@dataclass(frozen=True, slots=True)
class L3PluginCapability:
    pin: ResourcePin
    domain_profile: DomainProfile
    domain_verifier_version: str
    supported_output_profiles: tuple[OutputProfile, ...]
    rules: tuple[RuleCapability, ...]

    def __post_init__(self) -> None:
        if type(self.pin) is not ResourcePin:
            raise DomainError("plugin pin must be ResourcePin")
        _choice(self.domain_profile, _DOMAINS, "domain profile")
        _text(self.domain_verifier_version, "domain verifier version")
        outputs = _tuple(
            self.supported_output_profiles, "plugin outputs", nonempty=True
        )
        _unique(outputs, "plugin outputs")
        if any(type(item) is not str or item not in _OUTPUTS for item in outputs):
            raise DomainError("invalid plugin output")
        rules = _tuple(self.rules, "plugin rules", nonempty=True)
        if any(
            type(rule) is not RuleCapability or rule.level is not RuleLevel.L3
            for rule in rules
        ):
            raise DomainError("plugin rules must be L3 RuleCapability")
        _unique(tuple(rule.rule_id for rule in rules), "plugin rule ids")


@dataclass(frozen=True, slots=True)
class CompilerContext:
    compiler_pin: ResourcePin
    runtime_capabilities: tuple[RuntimeCapability, ...]
    model_capabilities: tuple[ModelCapability, ...]
    encoder_capabilities: tuple[EncoderCapability, ...]
    strength_mappings: tuple[StrengthMappingCapability, ...]
    output_profile_capabilities: tuple[OutputProfileCapability, ...]
    rule_catalogs: tuple[RuleCatalogCapability, ...]
    threshold_profiles: tuple[ThresholdProfileCapability, ...]
    l3_plugins: tuple[L3PluginCapability, ...]

    def __post_init__(self) -> None:
        if type(self.compiler_pin) is not ResourcePin:
            raise DomainError("compiler pin must be ResourcePin")
        for values, name, item_type in (
            (self.runtime_capabilities, "runtime capabilities", RuntimeCapability),
            (self.model_capabilities, "model capabilities", ModelCapability),
            (self.encoder_capabilities, "encoder capabilities", EncoderCapability),
            (self.strength_mappings, "strength mappings", StrengthMappingCapability),
            (
                self.output_profile_capabilities,
                "output profile capabilities",
                OutputProfileCapability,
            ),
            (self.rule_catalogs, "rule catalogs", RuleCatalogCapability),
            (self.threshold_profiles, "threshold profiles", ThresholdProfileCapability),
            (self.l3_plugins, "l3 plugins", L3PluginCapability),
        ):
            items = _tuple(values, name)
            if any(type(item) is not item_type for item in items):
                raise DomainError(f"{name} have invalid item")


@dataclass(frozen=True, slots=True)
class ResolvedRuntime:
    pin: ResourcePin
    backend: Literal["rocm"]
    rocm_version: str
    torch_version: str
    diffusers_version: str
    dtype: Literal["float16", "bfloat16"]

    def __post_init__(self) -> None:
        RuntimeCapability(
            self.pin,
            self.backend,
            self.rocm_version,
            self.torch_version,
            self.diffusers_version,
            self.dtype,
        )


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    role: ModelRole
    pin: ResourcePin
    controlnet_type: Literal["canny", "depth", "pose"] | None

    def __post_init__(self) -> None:
        _choice(self.role, {"base", "ip_adapter", "controlnet"}, "model role")
        if type(self.pin) is not ResourcePin:
            raise DomainError("model pin must be ResourcePin")
        if (self.role == "controlnet") != (self.controlnet_type is not None):
            raise DomainError("controlnet role/type mismatch")
        if self.controlnet_type is not None:
            _choice(self.controlnet_type, {"canny", "depth", "pose"}, "controlnet type")


@dataclass(frozen=True, slots=True)
class ResolvedEncoder:
    pin: ResourcePin
    preprocessing_version: str
    layer: str
    distance_function: str

    def __post_init__(self) -> None:
        if type(self.pin) is not ResourcePin:
            raise DomainError("encoder pin must be ResourcePin")
        for name in ("preprocessing_version", "layer", "distance_function"):
            _text(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class CompiledThresholdBinding:
    profile_pin: ResourcePin
    logical_name: str
    status: ThresholdStatus
    metric_id: Identifier
    operator: ThresholdOperator
    value: float
    calibration_dataset_sha256: Sha256
    validation_dataset_sha256: Sha256
    annotation_protocol_sha256: Sha256
    production_approval_sha256: Sha256 | None = None

    def __post_init__(self) -> None:
        if type(self.profile_pin) is not ResourcePin:
            raise DomainError("threshold profile pin must be ResourcePin")
        _text(self.logical_name, "logical_name")
        _choice(
            self.status,
            {"DRAFT", "CALIBRATED", "VALIDATED", "REVOKED"},
            "threshold status",
        )
        _identifier(self.metric_id, "metric_id")
        _choice(self.operator, {">=", "<="}, "operator")
        _finite(self.value, "threshold value")
        if any(
            type(item) is not Sha256
            for item in (
                self.calibration_dataset_sha256,
                self.validation_dataset_sha256,
                self.annotation_protocol_sha256,
            )
        ):
            raise DomainError("threshold dataset hashes must be Sha256")
        if (
            self.production_approval_sha256 is not None
            and type(self.production_approval_sha256) is not Sha256
        ):
            raise DomainError("threshold approval hash must be Sha256")


@dataclass(frozen=True, slots=True)
class CompiledRule:
    definition: RuleDefinition
    verifier_pin: ResourcePin
    metric_id: Identifier | None
    threshold_binding: CompiledThresholdBinding | None
    priority: int
    affected_by_actions: tuple[Identifier, ...]

    def __post_init__(self) -> None:
        if (
            type(self.definition) is not RuleDefinition
            or type(self.verifier_pin) is not ResourcePin
        ):
            raise DomainError("compiled rule has invalid definition or verifier pin")
        if self.metric_id is not None:
            _identifier(self.metric_id, "metric_id")
        if (
            self.threshold_binding is not None
            and type(self.threshold_binding) is not CompiledThresholdBinding
        ):
            raise DomainError("threshold binding must be CompiledThresholdBinding")
        if self.metric_id is None and self.threshold_binding is not None:
            raise DomainError("threshold binding requires metric id")
        if (
            self.definition.applicability is StaticApplicability.NOT_APPLICABLE
            and self.threshold_binding is not None
        ):
            raise DomainError("not applicable rule cannot have threshold binding")
        if (
            self.threshold_binding is not None
            and self.metric_id != self.threshold_binding.metric_id
        ):
            raise DomainError("threshold binding metric must match rule metric")
        if (
            self.definition.applicability is StaticApplicability.APPLICABLE
            and self.metric_id is not None
            and self.threshold_binding is None
        ):
            raise DomainError("applicable metric rule requires threshold binding")
        if (
            type(self.priority) is not int
            or isinstance(self.priority, bool)
            or self.priority < 0
        ):
            raise DomainError("priority must be nonnegative int")
        actions = _tuple(self.affected_by_actions, "affected actions")
        if any(type(item) is not Identifier for item in actions):
            raise DomainError("affected actions must contain Identifier")
        _unique(actions, "affected actions")


@dataclass(frozen=True, slots=True)
class CompiledExecutionGraph:
    generation_profile: GenerationProfile
    output_profile: OutputProfile
    output_profile_pin: ResourcePin
    pipeline: Pipeline
    resolution: tuple[int, int]
    steps: int
    guidance_scale: float
    scheduler: str | None
    runtime: ResolvedRuntime
    base_model: ResolvedModel
    ip_adapter: ResolvedModel
    controlnet: ResolvedModel
    style_reference_hashes: tuple[Sha256, ...]
    preset_id: Identifier
    user_strength: float
    strength_mapping_pin: ResourcePin
    ip_adapter_scale: float
    img2img_strength: float
    controlnet_scale: float
    seed_policy: Literal["per_asset_deterministic"]
    batch_execution: Literal["sequential"]
    render_contract: OutputRenderContract | None = None

    def __post_init__(self) -> None:
        _choice(
            self.generation_profile, {"preview", "production"}, "generation profile"
        )
        _choice(self.output_profile, _OUTPUTS, "output profile")
        if type(self.output_profile_pin) is not ResourcePin:
            raise DomainError("output profile pin must be ResourcePin")
        if (
            self.render_contract is not None
            and type(self.render_contract) is not OutputRenderContract
        ):
            raise DomainError("graph render contract must be OutputRenderContract")
        _choice(self.pipeline, _PIPELINES, "pipeline")
        resolution = _tuple(self.resolution, "resolution", nonempty=True)
        if len(resolution) != 2 or any(
            type(item) is not int or isinstance(item, bool) for item in resolution
        ):
            raise DomainError("resolution must be two exact ints")
        if (
            self.generation_profile == "production"
            and self.render_contract is not None
            and self.render_contract.native_resolution is not None
            and self.resolution != self.render_contract.native_resolution
        ):
            raise DomainError("graph native output resolution mismatch")
        if (
            type(self.steps) is not int
            or isinstance(self.steps, bool)
            or self.steps < 1
        ):
            raise DomainError("steps must be positive int")
        _finite(self.guidance_scale, "guidance scale")
        if (self.generation_profile == "preview") != (self.scheduler is None):
            raise DomainError("preview scheduler must be None")
        if self.scheduler is not None:
            _text(self.scheduler, "scheduler")
        if any(
            type(item) is not expected
            for item, expected in (
                (self.runtime, ResolvedRuntime),
                (self.base_model, ResolvedModel),
                (self.ip_adapter, ResolvedModel),
                (self.controlnet, ResolvedModel),
                (self.strength_mapping_pin, ResourcePin),
            )
        ):
            raise DomainError("graph contains invalid resolved capability")
        hashes = _tuple(self.style_reference_hashes, "style hashes", nonempty=True)
        if any(type(item) is not Sha256 for item in hashes):
            raise DomainError("style hashes must contain Sha256")
        _identifier(self.preset_id, "preset_id")
        for value, name in (
            (self.user_strength, "user strength"),
            (self.ip_adapter_scale, "adapter scale"),
            (self.img2img_strength, "img2img strength"),
            (self.controlnet_scale, "controlnet scale"),
        ):
            _finite(value, name, unit=True)
        _choice(self.seed_policy, {"per_asset_deterministic"}, "seed policy")
        _choice(self.batch_execution, {"sequential"}, "batch execution")

    @property
    def final_output_resolution(self) -> tuple[int, int]:
        if self.render_contract is None:
            return self.resolution
        return self.render_contract.final_resolution


@dataclass(frozen=True, slots=True)
class CompiledVerificationPlan:
    output_profile: OutputProfile
    output_profile_pin: ResourcePin
    rules: tuple[CompiledRule, ...]
    l3_status: L3PlanStatus
    l3_reason: L3NotApplicableReason | None
    l3_plugin_pin: ResourcePin | None
    l3_threshold_profile_pin: ResourcePin | None

    def __post_init__(self) -> None:
        _choice(self.output_profile, _OUTPUTS, "output profile")
        if type(self.output_profile_pin) is not ResourcePin:
            raise DomainError("output profile pin must be ResourcePin")
        rules = _tuple(self.rules, "compiled rules", nonempty=True)
        if any(type(rule) is not CompiledRule for rule in rules):
            raise DomainError("compiled rules must contain CompiledRule")
        _unique(tuple(rule.definition.rule_id for rule in rules), "compiled rule ids")
        _choice(self.l3_status, {"APPLICABLE", "NOT_APPLICABLE"}, "L3 status")
        l3_rules = tuple(
            rule for rule in rules if rule.definition.level is RuleLevel.L3
        )
        applicable_l3 = tuple(
            rule
            for rule in l3_rules
            if rule.definition.applicability is StaticApplicability.APPLICABLE
        )
        if self.l3_status == "APPLICABLE" and (
            self.l3_reason is not None
            or type(self.l3_plugin_pin) is not ResourcePin
            or type(self.l3_threshold_profile_pin) is not ResourcePin
            or not applicable_l3
        ):
            raise DomainError("applicable L3 plan requires pins and no reason")
        if self.l3_status == "NOT_APPLICABLE":
            if self.l3_reason == "NO_L3_CONFIG" and (
                self.l3_plugin_pin is not None
                or self.l3_threshold_profile_pin is not None
                or l3_rules
            ):
                raise DomainError("NO_L3_CONFIG cannot retain L3 state")
            if self.l3_reason == "NO_APPLICABLE_RULE" and (
                type(self.l3_plugin_pin) is not ResourcePin
                or type(self.l3_threshold_profile_pin) is not ResourcePin
                or not l3_rules
                or applicable_l3
            ):
                raise DomainError(
                    "NO_APPLICABLE_RULE requires only N/A L3 rules and pins"
                )
            if self.l3_reason not in {"NO_L3_CONFIG", "NO_APPLICABLE_RULE"}:
                raise DomainError("not applicable L3 plan requires reason")

    @property
    def applicable_rule_definitions(self) -> tuple[RuleDefinition, ...]:
        return tuple(
            sorted(
                (
                    rule.definition
                    for rule in self.rules
                    if rule.definition.applicability is StaticApplicability.APPLICABLE
                ),
                key=lambda definition: definition.rule_id.value,
            )
        )


@dataclass(frozen=True, slots=True)
class CompiledStyleSpec:
    source_spec: StyleSpec
    compiler_pin: ResourcePin
    ruleset_pin: ResourcePin
    l2_encoder: ResolvedEncoder
    preview_graphs: tuple[CompiledExecutionGraph, ...]
    production_graphs: tuple[CompiledExecutionGraph, ...]
    verification_plans: tuple[CompiledVerificationPlan, ...]
    compiled_spec_hash: Sha256 = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.source_spec) not in (StyleSpecV1, StyleSpecV11)
            or type(self.compiler_pin) is not ResourcePin
            or type(self.ruleset_pin) is not ResourcePin
            or type(self.l2_encoder) is not ResolvedEncoder
        ):
            raise DomainError("compiled spec has invalid source or resolution")
        for values, name, item_type in (
            (self.preview_graphs, "preview graphs", CompiledExecutionGraph),
            (self.production_graphs, "production graphs", CompiledExecutionGraph),
            (self.verification_plans, "verification plans", CompiledVerificationPlan),
        ):
            items = _tuple(values, name, nonempty=True)
            if any(type(item) is not item_type for item in items):
                raise DomainError(f"{name} contain invalid item")
        object.__setattr__(self, "compiled_spec_hash", _canonical_hash(self))


def _canonical_hash(compiled: CompiledStyleSpec) -> Sha256:
    payload = {
        "hash_schema": "specstyle.compiled.v1",
        "source_spec": compiled.source_spec.model_dump(mode="json", round_trip=True),
        "compiler_pin": compiled.compiler_pin,
        "ruleset_pin": compiled.ruleset_pin,
        "l2_encoder": compiled.l2_encoder,
        "preview_graphs": compiled.preview_graphs,
        "production_graphs": compiled.production_graphs,
        "verification_plans": compiled.verification_plans,
    }
    encoded = json.dumps(
        _primitive(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return Sha256(hashlib.sha256(encoded).hexdigest())


def _primitive(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Identifier, Sha256)):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _primitive(getattr(value, item.name))
            for item in dataclasses.fields(value)
            if item.init
            and not (
                type(value) is CompiledExecutionGraph
                and item.name == "render_contract"
                and value.render_contract is None
            )
            and not (
                type(value) is OutputRenderContract
                and item.name == "native_resolution"
                and value.native_resolution is None
            )
            and not (
                type(value) is CompiledThresholdBinding
                and item.name == "production_approval_sha256"
                and value.production_approval_sha256 is None
            )
        }
    if isinstance(value, tuple):
        return [_primitive(item) for item in value]
    if isinstance(value, list):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if type(value) is float:
        if not math.isfinite(value):
            raise DomainError("non-finite value cannot be hashed")
        return 0.0 if value == 0.0 else value
    return value
