"""Verified production compiler-context configuration composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import os
import stat
from typing import Any

from specstyle.calibration.production_evidence import (
    ProductionThresholdExpectation,
    ValidatedEvidenceBinding,
    require_runtime_evidence_binding,
    validate_production_threshold_evidence,
)
from specstyle.domain.enums import RuleLevel, RuleScope
from specstyle.domain.identifiers import Identifier, RuleId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.canny_contracts import CannyProcessorConfig
from specstyle.generation.model_registry import ModelDescriptor
from specstyle.generation.pipeline_factory import PipelineGraph
from specstyle.observability.environment import EnvironmentSnapshot, hash_environment
from specstyle.production._fd_ownership import (
    _OwnedFileDescriptors,
    _duplicate_directory_fd,
)
from specstyle.production.config_io import _load_json_document_from_owned_root
from specstyle.production.context_v4 import (
    FormalContextBindings,
    FormalThresholdProfileConfig,
    V4_TOP_KEYS,
    load_formal_context_bindings,
    require_formal_context_integrity,
)
from specstyle.production.context_v4_integrity import FormalContextAnchor
from specstyle.production.output_profile_config import (
    copy_output_profile,
    parse_legacy_output_profile,
    parse_output_profiles_v2,
)
from specstyle.spec.compiled_models import (
    CompilerContext,
    EncoderCapability,
    L3PluginCapability,
    ModelCapability,
    OutputProfileCapability,
    ResourcePin,
    RuleCapability,
    RuleCatalogCapability,
    RuntimeCapability,
    StrengthMappingCapability,
    StrengthMappingEntry,
    ThresholdMetricCapability,
    ThresholdProfileCapability,
)
from specstyle.verification.l1.production_bindings import (
    production_l1_rule_bindings,
)

__all__ = (
    "ProductionContextConfig",
    "load_production_context_config",
    "make_production_compiler_context_factory",
    "require_model_pipeline_support",
    "require_validated_production_threshold",
)

_SCHEMA_V1 = "specstyle.production.context.v1"
_SCHEMA_V2 = "specstyle.production.context.v2"
_SCHEMA_V3 = "specstyle.production.context.v3"
_SCHEMA_V4 = "specstyle.production.context.v4"
_CONFIG_BYTES = 1024 * 1024
_EVIDENCE_BYTES = 16 * 1024 * 1024
_EVIDENCE_TOTAL_BYTES = 48 * 1024 * 1024
_READ_BYTES = 1024 * 1024
_CONFIG_SEAL = object()
_TOP_KEYS_V1 = {
    "schema_version",
    "compiler_pin",
    "model_support",
    "strength_mapping",
    "output_profile",
    "rule_catalog",
    "l2_threshold_profile",
    "source_preprocess",
    "canny",
}
_TOP_KEYS_V2 = (_TOP_KEYS_V1 - {"output_profile"}) | {"output_profiles"}
_PIN_KEYS = {"id", "revision", "sha256"}
_MODEL_SUPPORT_KEYS = {"role", "supported_pipelines"}
_MAPPING_KEYS = {"pin", "preset_id", "entries"}
_MAPPING_ENTRY_KEYS = {
    "user_strength",
    "preview_ip_adapter_scale",
    "production_ip_adapter_scale",
}
_CATALOG_KEYS = {
    "ruleset_version",
    "pin",
    "l1_rules",
    "l2_item_rule",
    "l2_batch_rule",
}
_L1_RULE_KEYS = {"rule_id", "verifier_pin", "priority", "affected_by_actions"}
_L2_RULE_KEYS = _L1_RULE_KEYS | {"metric_id"}
_L1_RULE_V2_KEYS = _L1_RULE_KEYS | {"supported_output_profiles"}
_L2_RULE_V2_KEYS = _L2_RULE_KEYS | {"supported_output_profiles"}
_THRESHOLD_KEYS = {
    "pin",
    "logical_name",
    "status",
    "style_pack_id",
    "metric",
    "evidence",
}
_THRESHOLD_METRICS_KEYS = (_THRESHOLD_KEYS - {"metric"}) | {"metrics"}
_METRIC_KEYS = {"metric_id", "operator", "value"}
_METRIC_V3_KEYS = _METRIC_KEYS | {"implementation_pin"}
_EVIDENCE_KEYS = {
    "calibration_dataset_sha256",
    "validation_dataset_sha256",
    "annotation_protocol_sha256",
}
_EVIDENCE_V3_KEYS = _EVIDENCE_KEYS | {"production_approval_sha256"}
_SOURCE_KEYS = {"processor_pin", "resize_mode", "background"}
_CANNY_KEYS = {"low_threshold", "high_threshold", "aperture_size", "l2_gradient"}
_MODEL_ROLES = ("base", "ip_adapter", "controlnet")
_PIPELINES = ("sdxl_turbo", "lcm", "sdxl_base")
_L2_METRIC = "reference_style_statistics_similarity"
_L2_BATCH_METRIC = "batch_style_consistency"


@dataclass(frozen=True, slots=True)
class _ModelSupport:
    role: str
    supported_pipelines: tuple[str, ...]

    def __post_init__(self) -> None:
        pipelines = self.supported_pipelines
        if (
            self.role not in _MODEL_ROLES
            or type(pipelines) is not tuple
            or not pipelines
            or "sdxl_base" not in pipelines
            or pipelines != tuple(item for item in _PIPELINES if item in pipelines)
        ):
            raise DomainError("invalid production model support")


@dataclass(frozen=True, slots=True)
class _ThresholdEvidence:
    calibration_dataset_sha256: Sha256
    validation_dataset_sha256: Sha256
    annotation_protocol_sha256: Sha256
    production_approval_sha256: Sha256 | None


@dataclass(frozen=True, slots=True)
class _L2ThresholdProfile:
    pin: ResourcePin
    logical_name: str
    status: str
    style_pack_id: Identifier
    metrics: tuple[ThresholdMetricCapability, ...]
    metric_implementation_pin: ResourcePin | None
    evidence: _ThresholdEvidence
    production_binding: ValidatedEvidenceBinding | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        metrics = self.metrics
        expected = (
            (_L2_METRIC, ">=", -1.0, 1.0),
            (_L2_BATCH_METRIC, "<=", 0.0, float("inf")),
        )
        if (
            type(self.logical_name) is not str
            or not 1 <= len(self.logical_name) <= 2048
            or self.logical_name != self.logical_name.strip()
            or any(
                ord(character) <= 31 or ord(character) == 127
                for character in self.logical_name
            )
            or self.status not in {"DRAFT", "CALIBRATED", "VALIDATED"}
            or type(metrics) is not tuple
            or not metrics
            or tuple(metric.metric_id.value for metric in metrics)
            != tuple(item[0] for item in expected[: len(metrics)])
            or any(
                metric.operator != operator or not lower <= metric.value <= upper
                for metric, (_, operator, lower, upper) in zip(
                    metrics, expected[: len(metrics)], strict=True
                )
            )
        ):
            raise DomainError("invalid production L2 threshold profile")

    @property
    def metric(self) -> ThresholdMetricCapability:
        if len(self.metrics) != 1:
            raise DomainError("production L2 threshold has multiple metrics")
        return self.metrics[0]


@dataclass(frozen=True, slots=True)
class _SourcePreprocess:
    processor_pin: ResourcePin
    resize_mode: str
    background: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            type(self.background) is not tuple
            or len(self.background) != 3
            or any(type(value) is not int for value in self.background)
            or any(not 0 <= value <= 255 for value in self.background)
            or self.resize_mode not in {"contain_pad", "cover_center"}
        ):
            raise DomainError("invalid production source background")


@dataclass(frozen=True, slots=True, init=False)
class ProductionContextConfig:
    schema_version: str
    compiler_pin: ResourcePin
    model_support: tuple[_ModelSupport, ...]
    strength_mapping: StrengthMappingCapability
    output_profiles: tuple[OutputProfileCapability, ...]
    rule_catalog: RuleCatalogCapability
    l2_threshold_profile: _L2ThresholdProfile | FormalThresholdProfileConfig
    threshold_profiles: tuple[_L2ThresholdProfile | FormalThresholdProfileConfig, ...]
    l3_plugins: tuple[L3PluginCapability, ...]
    target_cell_sha256: Sha256 | None
    _v4_integrity_anchor: FormalContextAnchor | None
    source_preprocess: _SourcePreprocess
    canny: CannyProcessorConfig
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("production context configs are issued only by the loader")

    @property
    def output_profile(self) -> OutputProfileCapability:
        if len(self.output_profiles) != 1:
            raise DomainError("production context has multiple output profiles")
        return self.output_profiles[0]


def require_model_pipeline_support(
    config: ProductionContextConfig, pipeline: str, roles: tuple[str, ...], /
) -> None:
    """Require an explicit compiler capability for every requested model role."""
    if (
        type(config) is not ProductionContextConfig
        or getattr(config, "_seal", None) is not _CONFIG_SEAL
        or type(pipeline) is not str
        or pipeline not in _PIPELINES
        or type(roles) is not tuple
        or not roles
        or len(set(roles)) != len(roles)
        or any(type(role) is not str or role not in _MODEL_ROLES for role in roles)
    ):
        raise DomainError("invalid model pipeline support query")
    supported = {item.role: item.supported_pipelines for item in config.model_support}
    if any(pipeline not in supported.get(role, ()) for role in roles):
        raise DomainError("required model pipeline support unavailable")


def require_validated_production_threshold(config: object, /) -> None:
    """Fail closed unless the loader issued every required Production approval."""
    if (
        type(config) is not ProductionContextConfig
        or getattr(config, "_seal", None) is not _CONFIG_SEAL
    ):
        raise DomainError("PRODUCTION_THRESHOLD_NOT_VALIDATED")
    if config.schema_version == _SCHEMA_V3:
        if (
            config.l2_threshold_profile.status != "VALIDATED"
            or type(config.l2_threshold_profile) is not _L2ThresholdProfile
            or type(config.l2_threshold_profile.production_binding)
            is not ValidatedEvidenceBinding
        ):
            raise DomainError("PRODUCTION_THRESHOLD_NOT_VALIDATED")
        return
    if config.schema_version == _SCHEMA_V4:
        try:
            require_formal_context_integrity(
                config._v4_integrity_anchor,
                config.target_cell_sha256,
                config.threshold_profiles,
                config.l2_threshold_profile,
                config.l3_plugins,
                require_validated=True,
            )
        except DomainError:
            pass
        else:
            return
    raise DomainError("PRODUCTION_THRESHOLD_NOT_VALIDATED")


def _exact(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise DomainError(f"invalid production context {label}")
    return value


def _pin(value: object) -> ResourcePin:
    raw = _exact(value, _PIN_KEYS, "pin")
    return ResourcePin(raw["id"], raw["revision"], Sha256(raw["sha256"]))


def _actions(value: object) -> tuple[Identifier, ...]:
    if type(value) is not list:
        raise DomainError("invalid production context actions")
    return tuple(Identifier(item) for item in value)


def _configured_outputs(value: object) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise DomainError("invalid production context rule outputs")
    outputs = tuple(value)
    allowed = ("xhs_grid", "talking_head_cover", "background_sequence")
    if (
        any(type(item) is not str or item not in allowed for item in outputs)
        or len(set(outputs)) != len(outputs)
        or outputs != tuple(item for item in allowed if item in outputs)
    ):
        raise DomainError("invalid production context rule outputs")
    return outputs


def _rule(
    value: object,
    *,
    kind: str,
    scope: RuleScope,
    outputs: tuple[str, ...] | None,
    domains: tuple[str, ...] = ("product_instance",),
    requirement: str | None = None,
):
    keys = (
        (_L1_RULE_V2_KEYS if kind == "L1_TECHNICAL" else _L2_RULE_V2_KEYS)
        if outputs is None
        else (_L1_RULE_KEYS if kind == "L1_TECHNICAL" else _L2_RULE_KEYS)
    )
    raw = _exact(value, keys, "rule")
    supported = (
        _configured_outputs(raw["supported_output_profiles"])
        if outputs is None
        else outputs
    )
    metric = None if kind == "L1_TECHNICAL" else Identifier(raw["metric_id"])
    return RuleCapability(
        RuleId(raw["rule_id"]),
        kind,
        RuleLevel.L1 if kind == "L1_TECHNICAL" else RuleLevel.L2,
        scope,
        requirement
        if requirement is not None
        else "always_required"
        if kind == "L1_TECHNICAL"
        else "always_advisory",
        domains,
        supported,
        _pin(raw["verifier_pin"]),
        "none" if metric is None else "l2",
        metric,
        raw["priority"],
        _actions(raw["affected_by_actions"]),
    )


def _catalog(value: object, schema_version: str) -> RuleCatalogCapability:
    raw = _exact(value, _CATALOG_KEYS, "rule catalog")
    if type(raw["l1_rules"]) is not list:
        raise DomainError("invalid production context rule catalog")
    v2 = schema_version in {_SCHEMA_V2, _SCHEMA_V3, _SCHEMA_V4}
    domains = (
        ("structure_only",) if schema_version == _SCHEMA_V4 else ("product_instance",)
    )
    l1 = tuple(
        _rule(
            item,
            kind="L1_TECHNICAL",
            scope=RuleScope.ITEM,
            outputs=None if v2 else ("xhs_grid",),
            domains=domains,
        )
        for item in raw["l1_rules"]
    )
    if tuple(rule.rule_id for rule in l1) != tuple(
        binding.rule_id for binding in production_l1_rule_bindings()
    ):
        raise DomainError("invalid production L1 rule catalog")
    item = _rule(
        raw["l2_item_rule"],
        kind="L2_STYLE_FIDELITY",
        scope=RuleScope.ITEM,
        outputs=None if v2 else ("xhs_grid",),
        domains=domains,
    )
    if item.metric_id != Identifier(_L2_METRIC):
        raise DomainError("invalid production L2 item metric")
    batch = _rule(
        raw["l2_batch_rule"],
        kind="L2_BATCH_CONSISTENCY",
        scope=RuleScope.BATCH,
        outputs=None if v2 else ("background_sequence",),
        domains=domains,
        requirement="always_required" if schema_version == _SCHEMA_V4 else None,
    )
    if batch.metric_id != Identifier(_L2_BATCH_METRIC):
        raise DomainError("invalid production L2 batch metric")
    return RuleCatalogCapability(
        raw["ruleset_version"], _pin(raw["pin"]), l1 + (item, batch)
    )


def _mapping(value: object) -> StrengthMappingCapability:
    raw = _exact(value, _MAPPING_KEYS, "strength mapping")
    if type(raw["entries"]) is not list:
        raise DomainError("invalid production context strength mapping")
    entries = tuple(
        StrengthMappingEntry(
            entry["user_strength"],
            entry["preview_ip_adapter_scale"],
            entry["production_ip_adapter_scale"],
        )
        for entry in (
            _exact(item, _MAPPING_ENTRY_KEYS, "strength mapping entry")
            for item in raw["entries"]
        )
    )
    return StrengthMappingCapability(
        _pin(raw["pin"]), Identifier(raw["preset_id"]), entries
    )


def _threshold(value: object, schema_version: str) -> _L2ThresholdProfile:
    allowed = (
        (_THRESHOLD_KEYS,)
        if schema_version == _SCHEMA_V1
        else (_THRESHOLD_KEYS, _THRESHOLD_METRICS_KEYS)
        if schema_version == _SCHEMA_V2
        else (_THRESHOLD_METRICS_KEYS,)
    )
    if type(value) is not dict or set(value) not in allowed:
        raise DomainError("invalid production context threshold")
    raw = value
    metric_values = raw.get("metrics", [raw.get("metric")])
    if type(metric_values) is not list or not metric_values:
        raise DomainError("invalid production context threshold metrics")
    metric_keys = _METRIC_V3_KEYS if schema_version == _SCHEMA_V3 else _METRIC_KEYS
    metrics = tuple(
        _exact(item, metric_keys, "threshold metric") for item in metric_values
    )
    evidence_keys = (
        _EVIDENCE_V3_KEYS if schema_version == _SCHEMA_V3 else _EVIDENCE_KEYS
    )
    evidence = _exact(raw["evidence"], evidence_keys, "threshold evidence")
    status = raw["status"]
    if status == "VALIDATED" and schema_version != _SCHEMA_V3:
        raise DomainError("VALIDATED threshold requires production context v3")
    approval_value = evidence.get("production_approval_sha256")
    if schema_version == _SCHEMA_V3 and (
        (status == "VALIDATED" and type(approval_value) is not str)
        or (status != "VALIDATED" and approval_value is not None)
    ):
        raise DomainError("invalid production threshold approval")
    if schema_version == _SCHEMA_V3 and (len(metrics) != 1 or len(metric_values) != 1):
        raise DomainError("v3 threshold requires one metric")
    return _L2ThresholdProfile(
        _pin(raw["pin"]),
        raw["logical_name"],
        status,
        Identifier(raw["style_pack_id"]),
        tuple(
            ThresholdMetricCapability(
                Identifier(metric["metric_id"]),
                metric["operator"],
                metric["value"],
            )
            for metric in metrics
        ),
        None
        if schema_version != _SCHEMA_V3
        else _pin(metrics[0]["implementation_pin"]),
        _ThresholdEvidence(
            Sha256(evidence["calibration_dataset_sha256"]),
            Sha256(evidence["validation_dataset_sha256"]),
            Sha256(evidence["annotation_protocol_sha256"]),
            None if approval_value is None else Sha256(approval_value),
        ),
    )


def _model_support(value: object) -> tuple[_ModelSupport, ...]:
    if type(value) is not list:
        raise DomainError("invalid production model support")
    raw = tuple(_exact(entry, _MODEL_SUPPORT_KEYS, "model support") for entry in value)
    if any(type(item["supported_pipelines"]) is not list for item in raw):
        raise DomainError("invalid production model support")
    supported = tuple(
        _ModelSupport(item["role"], tuple(item["supported_pipelines"])) for item in raw
    )
    if tuple(item.role for item in supported) != _MODEL_ROLES:
        raise DomainError("invalid production model support")
    return supported


def _source(value: object) -> _SourcePreprocess:
    raw = _exact(value, _SOURCE_KEYS, "source")
    return _SourcePreprocess(
        _pin(raw["processor_pin"]), raw["resize_mode"], tuple(raw["background"])
    )


def _canny(value: object) -> CannyProcessorConfig:
    raw = _exact(value, _CANNY_KEYS, "canny")
    return CannyProcessorConfig(
        raw["low_threshold"],
        raw["high_threshold"],
        raw["aperture_size"],
        raw["l2_gradient"],
    )


def _open_flags(*, directory: bool) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _evidence_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _evidence_stat(fd: int, label: str) -> os.stat_result:
    try:
        return os.fstat(fd)
    except OSError as exc:
        raise InfrastructureError(
            f"production context evidence metadata unavailable: {label}"
        ) from exc


def _validate_evidence_directory(fd: int, label: str) -> int:
    value = _evidence_stat(fd, label)
    if not stat.S_ISDIR(value.st_mode):
        raise InfrastructureError("production context evidence directory refused")
    if value.st_uid != os.geteuid() or value.st_mode & 0o022:
        raise InfrastructureError("production context evidence directory untrusted")
    return fd


def _open_evidence_directory(
    parent_fd: int, name: str, owned: _OwnedFileDescriptors
) -> int:
    def open_directory() -> int:
        try:
            return os.open(name, _open_flags(directory=True), dir_fd=parent_fd)
        except (OSError, ValueError) as exc:
            raise InfrastructureError(
                "production context evidence directory refused"
            ) from exc

    opened = owned.acquire(open_directory, f"evidence directory {name}")
    return _validate_evidence_directory(opened, name)


def _open_evidence_file(
    parent_fd: int, digest: Sha256, owned: _OwnedFileDescriptors
) -> int:
    def open_file() -> int:
        try:
            return os.open(digest.value, _open_flags(directory=False), dir_fd=parent_fd)
        except (OSError, ValueError) as exc:
            raise InfrastructureError(
                "production context evidence file refused"
            ) from exc

    return owned.acquire(open_file, "evidence file")


def _read_evidence_file(file_fd: int, digest: Sha256) -> bytes:
    before = _evidence_stat(file_fd, digest.value)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
    ):
        raise InfrastructureError("production context evidence file untrusted")
    if not 1 <= before.st_size <= _EVIDENCE_BYTES:
        raise InfrastructureError("production context evidence size refused")
    calculated = hashlib.sha256()
    bytes_read = 0
    chunks: list[bytes] = []
    while bytes_read <= before.st_size:
        request = min(_READ_BYTES, before.st_size - bytes_read + 1)
        try:
            chunk = os.read(file_fd, request)
        except OSError as exc:
            raise InfrastructureError(
                "production context evidence unavailable"
            ) from exc
        if not chunk:
            break
        calculated.update(chunk)
        chunks.append(chunk)
        bytes_read += len(chunk)
    after = _evidence_stat(file_fd, digest.value)
    if bytes_read != before.st_size or _evidence_identity(before) != _evidence_identity(
        after
    ):
        raise InfrastructureError("production context evidence file changed")
    if calculated.hexdigest() != digest.value:
        raise InfrastructureError("production context evidence digest mismatch")
    return b"".join(chunks)


def _read_evidence(
    root_fd: object, digest: Sha256, owned: _OwnedFileDescriptors
) -> bytes:
    if type(root_fd) is not int or root_fd < 0:
        raise DomainError("invalid production evidence root fd")
    sha_fd = _open_evidence_directory(root_fd, "sha256", owned)
    prefix_fd = _open_evidence_directory(sha_fd, digest.value[:2], owned)
    file_fd = _open_evidence_file(prefix_fd, digest, owned)
    return _read_evidence_file(file_fd, digest)


def _issue(document: dict[str, Any]) -> ProductionContextConfig:
    schema_version = document["schema_version"]
    threshold = _threshold(document["l2_threshold_profile"], schema_version)
    mapping = _mapping(document["strength_mapping"])
    if threshold.style_pack_id != mapping.preset_id:
        raise DomainError("invalid production threshold style pack")
    issued = object.__new__(ProductionContextConfig)
    outputs = (
        (parse_legacy_output_profile(document["output_profile"]),)
        if schema_version == _SCHEMA_V1
        else parse_output_profiles_v2(document["output_profiles"])
    )
    catalog = _catalog(document["rule_catalog"], schema_version)
    profiles = {item.profile for item in outputs}
    expected_metrics = tuple(
        rule.metric_id
        for rule in catalog.rules
        if rule.level is RuleLevel.L2
        and profiles.intersection(rule.supported_output_profiles)
    )
    if any(
        rule.level is RuleLevel.L1
        and not profiles.issubset(rule.supported_output_profiles)
        for rule in catalog.rules
    ):
        raise DomainError("production output lacks required L1 coverage")
    if tuple(metric.metric_id for metric in threshold.metrics) != expected_metrics:
        raise DomainError("production output lacks L2 threshold coverage")
    values = (
        ("schema_version", document["schema_version"]),
        ("compiler_pin", _pin(document["compiler_pin"])),
        ("model_support", _model_support(document["model_support"])),
        ("strength_mapping", mapping),
        ("output_profiles", outputs),
        ("rule_catalog", catalog),
        ("l2_threshold_profile", threshold),
        ("threshold_profiles", (threshold,)),
        ("l3_plugins", ()),
        ("target_cell_sha256", None),
        ("_v4_integrity_anchor", None),
        ("source_preprocess", _source(document["source_preprocess"])),
        ("canny", _canny(document["canny"])),
        ("_seal", _CONFIG_SEAL),
    )
    for name, value in values:
        object.__setattr__(issued, name, value)
    return issued


def _structure_output(value: OutputProfileCapability) -> OutputProfileCapability:
    return OutputProfileCapability(
        _copy_pin(value.pin),
        value.profile,
        ("structure_only",),
        tuple(value.supported_generation_profiles),
        value.render_contract,
    )


def _issue_v4(
    document: dict[str, Any], formal: FormalContextBindings
) -> ProductionContextConfig:
    mapping = _mapping(document["strength_mapping"])
    outputs = tuple(
        _structure_output(item)
        for item in parse_output_profiles_v2(document["output_profiles"])
    )
    catalog = _catalog(document["rule_catalog"], _SCHEMA_V4)
    target = formal.target
    expected_l2 = {
        rule.metric_id
        for rule in catalog.rules
        if rule.level is RuleLevel.L2
        and target.output_profile in rule.supported_output_profiles
    }
    actual_l2 = {item.metric_id for item in formal.threshold_profiles[0].metrics}
    if (
        target.domain_profile != "structure_only"
        or target.output_profile != "xhs_grid"
        or _pin(document["compiler_pin"]) != target.compiler_pin
        or mapping.preset_id != target.style_pack_id
        or mapping.pin != target.style_pack_pin
        or len(outputs) != 1
        or outputs[0].profile != target.output_profile
        or outputs[0].pin != target.output_profile_pin
        or catalog.pin != target.rule_catalog_pin
        or expected_l2 != actual_l2
    ):
        raise DomainError("v4 context target drift")
    source = _source(document["source_preprocess"])
    expected_preprocessor = target.require_metric(_L2_METRIC).preprocessor_pin
    if source.processor_pin != expected_preprocessor:
        raise DomainError("v4 source preprocessor drift")
    issued = object.__new__(ProductionContextConfig)
    values = (
        ("schema_version", _SCHEMA_V4),
        ("compiler_pin", target.compiler_pin),
        ("model_support", _model_support(document["model_support"])),
        ("strength_mapping", mapping),
        ("output_profiles", outputs),
        ("rule_catalog", catalog),
        ("l2_threshold_profile", formal.threshold_profiles[0]),
        ("threshold_profiles", formal.threshold_profiles),
        ("l3_plugins", formal.l3_plugins),
        ("target_cell_sha256", target.sha256),
        ("_v4_integrity_anchor", formal.integrity_anchor),
        ("source_preprocess", source),
        ("canny", _canny(document["canny"])),
        ("_seal", _CONFIG_SEAL),
    )
    for name, value in values:
        object.__setattr__(issued, name, value)
    require_formal_context_integrity(
        issued._v4_integrity_anchor,
        issued.target_cell_sha256,
        issued.threshold_profiles,
        issued.l2_threshold_profile,
        issued.l3_plugins,
        require_validated=False,
    )
    return issued


def _load_v4(
    document: dict[str, Any],
    evidence_root_fd: int,
    owned: _OwnedFileDescriptors,
) -> ProductionContextConfig:
    cache: dict[Sha256, bytes] = {}
    evidence_total = 0

    def read(digest: Sha256) -> bytes:
        nonlocal evidence_total
        if type(digest) is not Sha256:
            raise DomainError("invalid v4 evidence digest")
        if digest not in cache:
            content = _read_evidence(evidence_root_fd, digest, owned)
            evidence_total += len(content)
            if evidence_total > _EVIDENCE_TOTAL_BYTES:
                raise InfrastructureError(
                    "production context evidence total size refused"
                )
            cache[digest] = content
        return cache[digest]

    formal = load_formal_context_bindings(document, read)
    return _issue_v4(document, formal)


def _bind_validated_evidence(
    config: ProductionContextConfig, evidence_objects: tuple[bytes, ...]
) -> None:
    threshold = config.l2_threshold_profile
    if threshold.status != "VALIDATED":
        if len(evidence_objects) != 3 or threshold.production_binding is not None:
            raise DomainError("invalid nonvalidated production threshold evidence")
        return
    if (
        config.schema_version != _SCHEMA_V3
        or len(config.output_profiles) != 1
        or len(threshold.metrics) != 1
        or type(threshold.metric_implementation_pin) is not ResourcePin
        or len(evidence_objects) != 4
    ):
        raise DomainError("invalid validated production threshold evidence")
    output = config.output_profiles[0]
    metric = threshold.metrics[0]
    expectation = ProductionThresholdExpectation(
        Identifier(threshold.style_pack_id.value),
        "product_instance",
        output.profile,
        _copy_pin(output.pin),
        _copy_pin(threshold.pin),
        Identifier(metric.metric_id.value),
        _copy_pin(threshold.metric_implementation_pin),
        metric.operator,
        metric.value,
    )
    binding = validate_production_threshold_evidence(
        evidence_objects[0],
        evidence_objects[1],
        evidence_objects[2],
        evidence_objects[3],
        expectation,
    )
    object.__setattr__(threshold, "production_binding", binding)


def load_production_context_config(
    config_root_fd: int, evidence_root_fd: int, /
) -> ProductionContextConfig:
    """Load context after a consecutive, non-atomic snapshot of both caller fds.

    The caller must keep both descriptors stable until both duplicates complete.
    """
    with _OwnedFileDescriptors("production context descriptors") as owned:
        owned_config_root_fd = owned.acquire(
            lambda: _duplicate_directory_fd(
                config_root_fd,
                "invalid production config root fd",
                "production config root unavailable",
            ),
            "config root",
        )
        owned_evidence_root_fd = owned.acquire(
            lambda: _duplicate_directory_fd(
                evidence_root_fd,
                "invalid production evidence root fd",
                "production context evidence root unavailable",
            ),
            "evidence root",
        )
        _validate_evidence_directory(owned_evidence_root_fd, "root")
        document = _load_json_document_from_owned_root(
            owned_config_root_fd, "context.json", _CONFIG_BYTES, owned
        )
        try:
            if type(document) is not dict:
                raise DomainError("invalid production context document")
            schema_version = document.get("schema_version")
            if schema_version not in (
                _SCHEMA_V1,
                _SCHEMA_V2,
                _SCHEMA_V3,
                _SCHEMA_V4,
            ):
                raise DomainError("invalid production context schema")
            if schema_version == _SCHEMA_V4:
                document = _exact(document, V4_TOP_KEYS, "document")
                return _load_v4(document, owned_evidence_root_fd, owned)
            document = _exact(
                document,
                _TOP_KEYS_V1 if schema_version == _SCHEMA_V1 else _TOP_KEYS_V2,
                "document",
            )
            issued = _issue(document)
        except DomainError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
            raise DomainError("invalid production context config") from exc
        evidence_digests = [
            issued.l2_threshold_profile.evidence.calibration_dataset_sha256,
            issued.l2_threshold_profile.evidence.validation_dataset_sha256,
            issued.l2_threshold_profile.evidence.annotation_protocol_sha256,
        ]
        approval_digest = (
            issued.l2_threshold_profile.evidence.production_approval_sha256
        )
        if approval_digest is not None:
            evidence_digests.append(approval_digest)
        evidence_objects: list[bytes] = []
        evidence_total = 0
        for digest in evidence_digests:
            content = _read_evidence(owned_evidence_root_fd, digest, owned)
            evidence_objects.append(content)
            evidence_total += len(content)
            if evidence_total > _EVIDENCE_TOTAL_BYTES:
                raise InfrastructureError(
                    "production context evidence total size refused"
                )
        _bind_validated_evidence(issued, tuple(evidence_objects))
        return issued


def _copy_pin(value: ResourcePin) -> ResourcePin:
    return ResourcePin(str(value.id), str(value.revision), Sha256(value.sha256.value))


def _copy_mapping(value: StrengthMappingCapability) -> StrengthMappingCapability:
    return StrengthMappingCapability(
        _copy_pin(value.pin),
        Identifier(value.preset_id.value),
        tuple(
            StrengthMappingEntry(
                item.user_strength,
                item.preview_ip_adapter_scale,
                item.production_ip_adapter_scale,
            )
            for item in value.entries
        ),
    )


def _copy_rule(value: RuleCapability) -> RuleCapability:
    return RuleCapability(
        RuleId(value.rule_id.value),
        str(value.kind),
        value.level,
        value.scope,
        str(value.requirement),
        tuple(str(item) for item in value.supported_domains),
        tuple(str(item) for item in value.supported_output_profiles),
        _copy_pin(value.verifier_pin),
        str(value.threshold_source),
        None if value.metric_id is None else Identifier(value.metric_id.value),
        value.priority,
        tuple(Identifier(item.value) for item in value.affected_by_actions),
    )


def _copy_catalog(value: RuleCatalogCapability) -> RuleCatalogCapability:
    return RuleCatalogCapability(
        str(value.ruleset_version),
        _copy_pin(value.pin),
        tuple(_copy_rule(item) for item in value.rules),
    )


def _copy_threshold(
    value: _L2ThresholdProfile, encoder_pin: ResourcePin
) -> ThresholdProfileCapability:
    return ThresholdProfileCapability(
        _copy_pin(value.pin),
        str(value.logical_name),
        "l2",
        str(value.status),
        Identifier(value.style_pack_id.value),
        "product_instance",
        _copy_pin(encoder_pin),
        None,
        tuple(
            ThresholdMetricCapability(
                Identifier(metric.metric_id.value),
                str(metric.operator),
                metric.value,
            )
            for metric in value.metrics
        ),
        Sha256(value.evidence.calibration_dataset_sha256.value),
        Sha256(value.evidence.validation_dataset_sha256.value),
        Sha256(value.evidence.annotation_protocol_sha256.value),
        None
        if value.evidence.production_approval_sha256 is None
        else Sha256(value.evidence.production_approval_sha256.value),
    )


def _copy_formal_threshold(
    value: FormalThresholdProfileConfig,
) -> ThresholdProfileCapability:
    return ThresholdProfileCapability(
        _copy_pin(value.pin),
        str(value.logical_name),
        value.source,
        value.status,
        Identifier(value.style_pack_id.value),
        "structure_only",
        _copy_pin(value.binding_pin) if value.source == "l2" else None,
        _copy_pin(value.binding_pin) if value.source == "l3" else None,
        tuple(
            ThresholdMetricCapability(
                Identifier(metric.metric_id.value), metric.operator, metric.value
            )
            for metric in value.metrics
        ),
        Sha256(value.calibration_dataset_sha256.value),
        Sha256(value.validation_dataset_sha256.value),
        Sha256(value.annotation_protocol_sha256.value),
        None
        if value.production_approval_sha256 is None
        else Sha256(value.production_approval_sha256.value),
    )


def _copy_l3_plugin(value: L3PluginCapability) -> L3PluginCapability:
    return L3PluginCapability(
        _copy_pin(value.pin),
        value.domain_profile,
        str(value.domain_verifier_version),
        tuple(value.supported_output_profiles),
        tuple(_copy_rule(rule) for rule in value.rules),
    )


def _available_runtime(environment: EnvironmentSnapshot) -> tuple[str, str, str]:
    observations = tuple(
        getattr(environment, name)
        for name in (
            "rocm_version",
            "hip_version",
            "pytorch_version",
            "diffusers_version",
        )
    )
    devices = environment.hip_devices
    if (
        any(
            item.status != "AVAILABLE"
            or type(item.value) is not str
            or item.reason is not None
            for item in observations
        )
        or devices.status != "AVAILABLE"
        or devices.reason is not None
        or not devices.devices
        or any(
            device.name.status != "AVAILABLE"
            or type(device.name.value) is not str
            or device.name.reason is not None
            or device.gfx_arch.status != "AVAILABLE"
            or type(device.gfx_arch.value) is not str
            or device.gfx_arch.reason is not None
            or device.total_memory_bytes.status != "AVAILABLE"
            or type(device.total_memory_bytes.value) is not int
            or device.total_memory_bytes.value <= 0
            or device.total_memory_bytes.reason is not None
            for device in devices.devices
        )
    ):
        raise DomainError("invalid production runtime environment")
    return (
        observations[0].value,
        observations[2].value,
        observations[3].value,
    )


def _validate_factory_inputs(
    config: object, environment: object, graph: object
) -> tuple[str, str, str]:
    if (
        type(config) is not ProductionContextConfig
        or getattr(config, "_seal", None) is not _CONFIG_SEAL
        or type(environment) is not EnvironmentSnapshot
        or type(graph) is not PipelineGraph
    ):
        raise DomainError("invalid production context factory input")
    models = (graph.base, graph.ip_adapter, graph.controlnet)
    if (
        graph.profile != "production"
        or graph.preview_adapter is not None
        or any(type(item) is not ModelDescriptor for item in models)
        or tuple(item.role for item in models) != _MODEL_ROLES
        or len({item.family for item in models}) != 1
        or tuple(item.role for item in config.model_support) != _MODEL_ROLES
    ):
        raise DomainError("invalid production pipeline graph")
    if config.schema_version == _SCHEMA_V4:
        require_formal_context_integrity(
            config._v4_integrity_anchor,
            config.target_cell_sha256,
            config.threshold_profiles,
            config.l2_threshold_profile,
            config.l3_plugins,
            require_validated=False,
        )
        l2 = config.l2_threshold_profile
        if type(l2) is not FormalThresholdProfileConfig or any(
            graph.ip_adapter.model_id != binding.binding_pin.id
            or graph.ip_adapter.revision != binding.binding_pin.revision
            or graph.ip_adapter.expected_sha256 != binding.binding_pin.sha256
            or binding.preprocessor_pin != config.source_preprocess.processor_pin
            for binding in l2.metric_bindings
        ):
            raise DomainError("production runtime evidence binding mismatch")
    else:
        threshold = config.l2_threshold_profile
        if type(threshold) is not _L2ThresholdProfile:
            raise DomainError("invalid production threshold profile")
        binding = threshold.production_binding
        if threshold.status == "VALIDATED":
            if (
                binding is None
                or graph.ip_adapter.model_id != binding.verifier_pin.id
                or graph.ip_adapter.revision != binding.verifier_pin.revision
                or graph.ip_adapter.expected_sha256 != binding.verifier_pin.sha256
            ):
                raise DomainError("production runtime evidence binding mismatch")
        elif binding is not None:
            raise DomainError("invalid nonvalidated production evidence binding")
    return _available_runtime(environment)


def _context(
    config: ProductionContextConfig,
    environment: EnvironmentSnapshot,
    graph: PipelineGraph,
    versions: tuple[str, str, str],
    preprocessing_version: str,
) -> CompilerContext:
    runtime_hash = hash_environment(environment)
    runtime_pin = ResourcePin("production-runtime", "environment-v1", runtime_hash)
    models = (graph.base, graph.ip_adapter, graph.controlnet)
    model_capabilities = tuple(
        ModelCapability(
            role,
            ResourcePin(
                model.model_id,
                model.revision,
                Sha256(model.expected_sha256.value),
            ),
            "canny" if role == "controlnet" else None,
            tuple(str(item) for item in support.supported_pipelines),
            ("float16",),
            (runtime_hash,),
        )
        for role, model, support in zip(
            _MODEL_ROLES, models, config.model_support, strict=True
        )
    )
    encoder_pin = model_capabilities[1].pin
    if config.schema_version == _SCHEMA_V4:
        require_formal_context_integrity(
            config._v4_integrity_anchor,
            config.target_cell_sha256,
            config.threshold_profiles,
            config.l2_threshold_profile,
            config.l3_plugins,
            require_validated=False,
        )
        l2 = config.l2_threshold_profile
        if type(l2) is not FormalThresholdProfileConfig:
            raise DomainError("invalid v4 L2 threshold profile")
        if l2.status == "VALIDATED" and any(
            binding.binding_pin != encoder_pin
            or binding.preprocessor_pin != config.source_preprocess.processor_pin
            or binding.preprocessor_pin.revision != preprocessing_version
            for binding in l2.metric_bindings
        ):
            raise DomainError("production runtime evidence binding mismatch")
    else:
        threshold = config.l2_threshold_profile
        if type(threshold) is not _L2ThresholdProfile:
            raise DomainError("invalid production threshold profile")
        binding = threshold.production_binding
        if threshold.status == "VALIDATED":
            if binding is None:
                raise DomainError("validated production evidence binding missing")
            require_runtime_evidence_binding(
                binding, encoder_pin, preprocessing_version
            )
        elif binding is not None:
            raise DomainError("invalid nonvalidated production evidence binding")
    threshold_profiles = (
        tuple(_copy_formal_threshold(profile) for profile in config.threshold_profiles)
        if config.schema_version == _SCHEMA_V4
        else (_copy_threshold(threshold, encoder_pin),)
    )
    return CompilerContext(
        _copy_pin(config.compiler_pin),
        (RuntimeCapability(runtime_pin, "rocm", *versions, "float16"),),
        model_capabilities,
        (
            EncoderCapability(
                _copy_pin(encoder_pin),
                preprocessing_version,
                "hidden_states[-2]",
                "median_cosine_patch_mean_std_v1",
                (runtime_hash,),
            ),
        ),
        (_copy_mapping(config.strength_mapping),),
        tuple(copy_output_profile(item) for item in config.output_profiles),
        (_copy_catalog(config.rule_catalog),),
        threshold_profiles,
        tuple(_copy_l3_plugin(plugin) for plugin in config.l3_plugins),
    )


def make_production_compiler_context_factory(
    config: ProductionContextConfig,
    environment: EnvironmentSnapshot,
    graph: PipelineGraph,
    /,
) -> Callable[[str], CompilerContext]:
    versions = _validate_factory_inputs(config, environment, graph)

    def build(preprocessing_version: str) -> CompilerContext:
        return _context(config, environment, graph, versions, preprocessing_version)

    return build
