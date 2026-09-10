"""Strict formal threshold and structure-plugin bindings for context v4."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from specstyle.calibration.evidence_io import canonical_json
from specstyle.calibration.formal_approval import (
    ApprovedMetricBinding,
    MetricEvidenceChain,
    ValidatedProfileApproval,
    validate_metric_production_approval,
    validate_profile_approval,
)
from specstyle.calibration.target_cell import TargetCell, TargetMetric, load_target_cell
from specstyle.domain.enums import RuleLevel, RuleScope
from specstyle.domain.identifiers import Identifier, RuleId, Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes
from specstyle.production.context_v4_integrity import (
    FormalContextAnchor,
    issue_formal_context_anchor,
    require_formal_context_anchor,
)
from specstyle.spec.compiled_models import (
    L3PluginCapability,
    ResourcePin,
    RuleCapability,
    ThresholdMetricCapability,
)

V4_TOP_KEYS = {
    "schema_version",
    "compiler_pin",
    "model_support",
    "strength_mapping",
    "output_profiles",
    "rule_catalog",
    "threshold_profiles",
    "l3_plugins",
    "target_cell_sha256",
    "source_preprocess",
    "canny",
}
_PIN_KEYS = {"id", "revision", "sha256"}
_PROFILE_KEYS = {
    "pin",
    "logical_name",
    "source",
    "status",
    "style_pack_id",
    "domain_profile",
    "metrics",
    "production_approval_sha256",
}
_METRIC_KEYS = {
    "metric_id",
    "observation_unit",
    "operator",
    "value",
    "implementation_pin",
    "binding_pin",
    "verifier_pin",
    "preprocessor_pin",
    "calibration_dataset_sha256",
    "validation_dataset_sha256",
    "annotation_protocol_sha256",
    "formal_evidence",
}
_FORMAL_NAMES = (
    "study_plan",
    "annotation_protocol",
    "sample_manifest",
    "calibration_observations",
    "validation_observations",
    "test_commitment",
    "label_approval_receipt",
    "prepared_evidence",
    "test_observations",
    "reveal_authorization_receipt",
    "test_reveal",
    "metric_production_approval",
)
_FORMAL_KEYS = {f"{name}_sha256" for name in _FORMAL_NAMES}
_PLUGIN_KEYS = {
    "pin",
    "domain_profile",
    "domain_verifier_version",
    "supported_output_profiles",
    "rules",
}
_RULE_KEYS = {
    "rule_id",
    "kind",
    "scope",
    "requirement",
    "supported_domains",
    "supported_output_profiles",
    "verifier_pin",
    "threshold_source",
    "metric_id",
    "priority",
    "affected_by_actions",
}
_PROFILE_ORDER = ("l2", "l3")
_STATUS_VALUES = {"DRAFT", "CALIBRATED", "VALIDATED"}
_PROFILE_SEAL = object()

EvidenceReader = Callable[[Sha256], bytes]


def _exact(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise DomainError(f"invalid v4 {label}")
    return value


def _text(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(ord(character) <= 31 or ord(character) == 127 for character in value)
    ):
        raise DomainError(f"invalid v4 {label}")
    return value


def _pin(value: object, label: str) -> ResourcePin:
    raw = _exact(value, _PIN_KEYS, label)
    return ResourcePin(raw["id"], raw["revision"], Sha256(raw["sha256"]))


def _sha(value: object, label: str) -> Sha256:
    if type(value) is not str:
        raise DomainError(f"invalid v4 {label}")
    return Sha256(value)


def _tuple_strings(
    value: object, allowed: tuple[str, ...], label: str
) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise DomainError(f"invalid v4 {label}")
    result = tuple(value)
    if (
        any(type(item) is not str or item not in allowed for item in result)
        or len(set(result)) != len(result)
        or result != tuple(item for item in allowed if item in result)
    ):
        raise DomainError(f"invalid v4 {label}")
    return result


@dataclass(frozen=True, slots=True)
class _ParsedMetric:
    target: TargetMetric
    capability: ThresholdMetricCapability
    binding_pin: ResourcePin
    verifier_pin: ResourcePin
    preprocessor_pin: ResourcePin
    calibration_dataset_sha256: Sha256
    validation_dataset_sha256: Sha256
    annotation_protocol_sha256: Sha256
    approved_binding: ApprovedMetricBinding | None


@dataclass(frozen=True, slots=True, init=False)
class FormalThresholdProfileConfig:
    target_cell_sha256: Sha256
    pin: ResourcePin
    logical_name: str
    source: str
    status: str
    style_pack_id: Identifier
    domain_profile: str
    binding_pin: ResourcePin
    metrics: tuple[ThresholdMetricCapability, ...]
    calibration_dataset_sha256: Sha256
    validation_dataset_sha256: Sha256
    annotation_protocol_sha256: Sha256
    production_approval_sha256: Sha256 | None
    metric_bindings: tuple[ApprovedMetricBinding, ...]
    profile_approval: ValidatedProfileApproval | None
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("v4 threshold profiles are issued only by the loader")

    def __post_init__(self) -> None:
        if (
            type(self.target_cell_sha256) is not Sha256
            or type(self.pin) is not ResourcePin
            or self.source not in _PROFILE_ORDER
            or self.status not in _STATUS_VALUES
            or type(self.style_pack_id) is not Identifier
            or self.domain_profile != "structure_only"
            or type(self.binding_pin) is not ResourcePin
            or type(self.metrics) is not tuple
            or not self.metrics
            or any(type(item) is not ThresholdMetricCapability for item in self.metrics)
            or any(
                type(item) is not Sha256
                for item in (
                    self.calibration_dataset_sha256,
                    self.validation_dataset_sha256,
                    self.annotation_protocol_sha256,
                )
            )
            or self._seal is not _PROFILE_SEAL
        ):
            raise DomainError("invalid v4 threshold profile")
        for metric in self.metrics:
            metric.__post_init__()
        validated = self.status == "VALIDATED"
        if validated != (
            type(self.production_approval_sha256) is Sha256
            and bool(self.metric_bindings)
            and type(self.profile_approval) is ValidatedProfileApproval
        ):
            raise DomainError("invalid v4 threshold profile approval")
        if not validated and (
            self.production_approval_sha256 is not None
            or self.metric_bindings
            or self.profile_approval is not None
        ):
            raise DomainError("invalid v4 nonvalidated threshold profile")
        if validated:
            _validated_profile_integrity(self)


def _validated_profile_integrity(profile: FormalThresholdProfileConfig) -> None:
    approval = profile.profile_approval
    bindings = profile.metric_bindings
    if (
        type(approval) is not ValidatedProfileApproval
        or type(profile.production_approval_sha256) is not Sha256
        or type(bindings) is not tuple
        or len(bindings) != len(profile.metrics)
        or any(type(item) is not ApprovedMetricBinding for item in bindings)
    ):
        raise DomainError("invalid v4 threshold profile approval")
    approval.__post_init__()
    for binding in bindings:
        binding.__post_init__()
    if (
        approval.production_approval_sha256 != profile.production_approval_sha256
        or approval.target_cell_sha256 != profile.target_cell_sha256
        or approval.source != profile.source
        or approval.threshold_profile_pin != profile.pin
        or approval.metrics != bindings
        or tuple(item.metric_id for item in bindings)
        != tuple(item.metric_id for item in profile.metrics)
        or any(
            item.target_cell_sha256 != profile.target_cell_sha256
            or item.layer != profile.source.upper()
            or item.binding_pin != profile.binding_pin
            or item.operator != {">=": "gte", "<=": "lte"}[metric.operator]
            or item.threshold != metric.value
            for item, metric in zip(bindings, profile.metrics, strict=True)
        )
    ):
        raise DomainError("invalid v4 threshold profile approval")


@dataclass(frozen=True, slots=True)
class FormalContextBindings:
    target: TargetCell
    threshold_profiles: tuple[FormalThresholdProfileConfig, ...]
    l3_plugins: tuple[L3PluginCapability, ...]
    integrity_anchor: FormalContextAnchor


def _issue_profile(
    *,
    target: TargetCell,
    pin: ResourcePin,
    logical_name: str,
    source: str,
    status: str,
    binding_pin: ResourcePin,
    metrics: tuple[ThresholdMetricCapability, ...],
    calibration_dataset_sha256: Sha256,
    validation_dataset_sha256: Sha256,
    annotation_protocol_sha256: Sha256,
    metric_bindings: tuple[ApprovedMetricBinding, ...],
    approval: ValidatedProfileApproval | None,
) -> FormalThresholdProfileConfig:
    issued = object.__new__(FormalThresholdProfileConfig)
    values = {
        "target_cell_sha256": target.sha256,
        "pin": pin,
        "logical_name": logical_name,
        "source": source,
        "status": status,
        "style_pack_id": Identifier(target.style_pack_id.value),
        "domain_profile": target.domain_profile,
        "binding_pin": binding_pin,
        "metrics": metrics,
        "calibration_dataset_sha256": calibration_dataset_sha256,
        "validation_dataset_sha256": validation_dataset_sha256,
        "annotation_protocol_sha256": annotation_protocol_sha256,
        "production_approval_sha256": None
        if approval is None
        else approval.production_approval_sha256,
        "metric_bindings": metric_bindings,
        "profile_approval": approval,
        "_seal": _PROFILE_SEAL,
    }
    for name, value in values.items():
        object.__setattr__(issued, name, value)
    issued.__post_init__()
    return issued


def _formal_chain(raw: dict[str, Any], read: EvidenceReader) -> MetricEvidenceChain:
    values = {
        name: read(_sha(raw[f"{name}_sha256"], f"{name} sha256"))
        for name in _FORMAL_NAMES
    }
    return MetricEvidenceChain(
        study_plan=values["study_plan"],
        annotation_protocol=values["annotation_protocol"],
        sample_manifest=values["sample_manifest"],
        calibration_observations=values["calibration_observations"],
        validation_observations=values["validation_observations"],
        test_commitment=values["test_commitment"],
        label_approval_receipt=values["label_approval_receipt"],
        prepared_evidence=values["prepared_evidence"],
        test_observations=values["test_observations"],
        reveal_authorization_receipt=values["reveal_authorization_receipt"],
        test_reveal=values["test_reveal"],
    )


def _metric_pins(raw: dict[str, Any], target: TargetMetric) -> tuple[ResourcePin, ...]:
    pins = tuple(
        _pin(raw[name], name)
        for name in (
            "implementation_pin",
            "binding_pin",
            "verifier_pin",
            "preprocessor_pin",
        )
    )
    expected = (
        target.implementation_pin,
        target.binding_pin,
        target.verifier_pin,
        target.preprocessor_pin,
    )
    if pins != expected:
        raise DomainError("v4 metric pin drift")
    return pins


def _metric(
    value: object,
    source: str,
    status: str,
    target_cell: bytes,
    target: TargetCell,
    read: EvidenceReader,
) -> _ParsedMetric:
    raw = _exact(value, _METRIC_KEYS, "threshold metric")
    target_metric = target.require_metric(raw["metric_id"])
    operator = {">=": "gte", "<=": "lte"}.get(raw["operator"])
    threshold = raw["value"]
    if (
        target_metric.layer != source.upper()
        or raw["observation_unit"] != target_metric.observation_unit
        or operator != target_metric.operator
        or type(threshold) is not float
        or not isfinite(threshold)
    ):
        raise DomainError("v4 threshold metric drift")
    implementation, binding, verifier, preprocessor = _metric_pins(raw, target_metric)
    digests = tuple(
        _sha(raw[name], name)
        for name in (
            "calibration_dataset_sha256",
            "validation_dataset_sha256",
            "annotation_protocol_sha256",
        )
    )
    for digest in digests:
        read(digest)
    formal = raw["formal_evidence"]
    approved: ApprovedMetricBinding | None = None
    if status == "VALIDATED":
        formal_raw = _exact(formal, _FORMAL_KEYS, "formal metric evidence")
        if (
            digests[0]
            != _sha(
                formal_raw["calibration_observations_sha256"],
                "calibration observations sha256",
            )
            or digests[1]
            != _sha(
                formal_raw["validation_observations_sha256"],
                "validation observations sha256",
            )
            or digests[2]
            != _sha(
                formal_raw["annotation_protocol_sha256"],
                "annotation protocol sha256",
            )
        ):
            raise DomainError("v4 metric evidence drift")
        chain = _formal_chain(formal_raw, read)
        approval = read(
            _sha(
                formal_raw["metric_production_approval_sha256"],
                "metric production approval sha256",
            )
        )
        approved = validate_metric_production_approval(target_cell, chain, approval)
        if approved.threshold != threshold:
            raise DomainError("v4 metric threshold drift")
    elif formal is not None:
        raise DomainError("v4 nonvalidated metric has formal evidence")
    return _ParsedMetric(
        target_metric,
        ThresholdMetricCapability(
            Identifier(raw["metric_id"]), raw["operator"], threshold
        ),
        binding,
        verifier,
        preprocessor,
        *digests,
        approved,
    )


def _aggregate(metrics: tuple[_ParsedMetric, ...], field: str) -> Sha256:
    values = [getattr(item, field).value for item in metrics]
    return hash_bytes(canonical_json(values))


def _profile(
    value: object,
    target_cell: bytes,
    target: TargetCell,
    read: EvidenceReader,
) -> FormalThresholdProfileConfig:
    raw = _exact(value, _PROFILE_KEYS, "threshold profile")
    source = raw["source"]
    status = raw["status"]
    if source not in _PROFILE_ORDER or status not in _STATUS_VALUES:
        raise DomainError("invalid v4 threshold profile")
    if type(raw["metrics"]) is not list or not raw["metrics"]:
        raise DomainError("invalid v4 threshold metrics")
    metrics = tuple(
        _metric(item, source, status, target_cell, target, read)
        for item in raw["metrics"]
    )
    expected = tuple(
        item.metric_id.value for item in target.metrics if item.layer == source.upper()
    )
    actual = tuple(item.target.metric_id.value for item in metrics)
    binding_pins = {item.binding_pin for item in metrics}
    if actual != expected or len(binding_pins) != 1:
        raise DomainError("invalid v4 threshold metric set")
    profile_pin = _pin(raw["pin"], "threshold profile pin")
    approval_sha = raw["production_approval_sha256"]
    approval: ValidatedProfileApproval | None = None
    approved_bindings = tuple(
        item.approved_binding for item in metrics if item.approved_binding is not None
    )
    if status == "VALIDATED":
        digest = _sha(approval_sha, "profile production approval sha256")
        approval = validate_profile_approval(
            target_cell,
            approved_bindings,
            read(digest),
            profile_pin,
        )
        if approval.production_approval_sha256 != digest:
            raise DomainError("v4 profile approval digest drift")
    elif approval_sha is not None or approved_bindings:
        raise DomainError("invalid v4 nonvalidated profile approval")
    if (
        raw["style_pack_id"] != target.style_pack_id.value
        or raw["domain_profile"] != target.domain_profile
    ):
        raise DomainError("v4 threshold profile target drift")
    return _issue_profile(
        target=target,
        pin=profile_pin,
        logical_name=_text(raw["logical_name"], "threshold profile name"),
        source=source,
        status=status,
        binding_pin=next(iter(binding_pins)),
        metrics=tuple(item.capability for item in metrics),
        calibration_dataset_sha256=_aggregate(metrics, "calibration_dataset_sha256"),
        validation_dataset_sha256=_aggregate(metrics, "validation_dataset_sha256"),
        annotation_protocol_sha256=_aggregate(metrics, "annotation_protocol_sha256"),
        metric_bindings=approved_bindings,
        approval=approval,
    )


def _rule(value: object, target_metric: TargetMetric) -> RuleCapability:
    raw = _exact(value, _RULE_KEYS, "structure rule")
    outputs = _tuple_strings(
        raw["supported_output_profiles"], ("xhs_grid",), "rule outputs"
    )
    domains = _tuple_strings(
        raw["supported_domains"], ("structure_only",), "rule domains"
    )
    if (
        raw["kind"] != "L3_DOMAIN_FIDELITY"
        or raw["scope"] != "ITEM"
        or raw["requirement"] != "fidelity_required"
        or raw["threshold_source"] != "l3"
        or raw["metric_id"] != target_metric.metric_id.value
        or _pin(raw["verifier_pin"], "structure verifier pin")
        != target_metric.verifier_pin
        or type(raw["affected_by_actions"]) is not list
    ):
        raise DomainError("invalid v4 structure rule")
    return RuleCapability(
        RuleId(raw["rule_id"]),
        raw["kind"],
        RuleLevel.L3,
        RuleScope.ITEM,
        raw["requirement"],
        domains,
        outputs,
        target_metric.verifier_pin,
        raw["threshold_source"],
        Identifier(raw["metric_id"]),
        raw["priority"],
        tuple(Identifier(item) for item in raw["affected_by_actions"]),
    )


def _plugin(value: object, target: TargetCell) -> L3PluginCapability:
    raw = _exact(value, _PLUGIN_KEYS, "structure plugin")
    target_metric = target.require_metric("structure_edge_similarity")
    outputs = _tuple_strings(
        raw["supported_output_profiles"], ("xhs_grid",), "plugin outputs"
    )
    if type(raw["rules"]) is not list or len(raw["rules"]) != 1:
        raise DomainError("invalid v4 structure plugin rules")
    plugin = L3PluginCapability(
        _pin(raw["pin"], "structure plugin pin"),
        raw["domain_profile"],
        _text(raw["domain_verifier_version"], "domain verifier version"),
        outputs,
        (_rule(raw["rules"][0], target_metric),),
    )
    if (
        plugin.pin != target_metric.binding_pin
        or plugin.domain_profile != target.domain_profile
        or plugin.domain_verifier_version != target.domain_verifier_version
        or plugin.supported_output_profiles != (target.output_profile,)
    ):
        raise DomainError("v4 structure plugin target drift")
    return plugin


def _require_formal_context_structure(
    target_cell_sha256: object,
    threshold_profiles: object,
    l2_threshold_profile: object,
    l3_plugins: object,
    *,
    require_validated: bool,
) -> None:
    """Revalidate nested v4 state at every public runtime boundary."""
    if (
        type(target_cell_sha256) is not Sha256
        or type(threshold_profiles) is not tuple
        or len(threshold_profiles) != 2
        or any(
            type(item) is not FormalThresholdProfileConfig
            for item in threshold_profiles
        )
        or l2_threshold_profile is not threshold_profiles[0]
        or type(l3_plugins) is not tuple
        or len(l3_plugins) != 1
        or type(l3_plugins[0]) is not L3PluginCapability
        or type(require_validated) is not bool
    ):
        raise DomainError("invalid v4 formal context")
    for profile in threshold_profiles:
        profile.__post_init__()
    if (
        tuple(profile.source for profile in threshold_profiles) != _PROFILE_ORDER
        or any(
            profile.target_cell_sha256 != target_cell_sha256
            for profile in threshold_profiles
        )
        or (
            require_validated
            and any(profile.status != "VALIDATED" for profile in threshold_profiles)
        )
    ):
        raise DomainError("invalid v4 formal context")
    plugin = l3_plugins[0]
    plugin.__post_init__()
    for rule in plugin.rules:
        rule.__post_init__()
    _require_plugin_integrity(threshold_profiles[0], threshold_profiles[1], plugin)


def _require_plugin_integrity(
    l2: FormalThresholdProfileConfig,
    l3: FormalThresholdProfileConfig,
    plugin: L3PluginCapability,
) -> None:
    l3_binding = l3.metric_bindings[0] if l3.metric_bindings else None
    if (
        tuple(metric.metric_id.value for metric in l2.metrics)
        != ("batch_style_consistency", "reference_style_statistics_similarity")
        or tuple(metric.metric_id.value for metric in l3.metrics)
        != ("structure_edge_similarity",)
        or plugin.pin != l3.binding_pin
        or plugin.domain_profile != "structure_only"
        or plugin.supported_output_profiles != ("xhs_grid",)
        or (
            l3_binding is not None
            and (
                len(plugin.rules) != 1
                or plugin.rules[0].metric_id != l3_binding.metric_id
                or plugin.rules[0].verifier_pin != l3_binding.verifier_pin
            )
        )
    ):
        raise DomainError("invalid v4 formal context")


def require_formal_context_integrity(
    integrity_anchor: object,
    target_cell_sha256: object,
    threshold_profiles: object,
    l2_threshold_profile: object,
    l3_plugins: object,
    *,
    require_validated: bool,
) -> None:
    """Normalize every nested-state failure to a domain rejection."""
    try:
        _require_formal_context_structure(
            target_cell_sha256,
            threshold_profiles,
            l2_threshold_profile,
            l3_plugins,
            require_validated=require_validated,
        )
        require_formal_context_anchor(
            integrity_anchor,
            target_cell_sha256,
            threshold_profiles,
            l3_plugins,
        )
    except (AttributeError, DomainError, IndexError, KeyError, TypeError):
        raise DomainError("invalid v4 formal context") from None


def load_formal_context_bindings(
    document: dict[str, Any], read: EvidenceReader
) -> FormalContextBindings:
    """Load and cross-bind the complete formal portion of context v4."""
    raw = _exact(document, V4_TOP_KEYS, "context document")
    target_sha = _sha(raw["target_cell_sha256"], "target cell sha256")
    target_data = read(target_sha)
    target = load_target_cell(target_data)
    if target.sha256 != target_sha:
        raise DomainError("v4 target cell digest drift")
    if type(raw["threshold_profiles"]) is not list:
        raise DomainError("invalid v4 threshold profiles")
    profiles = tuple(
        _profile(item, target_data, target, read) for item in raw["threshold_profiles"]
    )
    if tuple(item.source for item in profiles) != _PROFILE_ORDER:
        raise DomainError("invalid v4 threshold profile set")
    if type(raw["l3_plugins"]) is not list or len(raw["l3_plugins"]) != 1:
        raise DomainError("invalid v4 structure plugins")
    plugins = (_plugin(raw["l3_plugins"][0], target),)
    if profiles[1].binding_pin != plugins[0].pin:
        raise DomainError("v4 L3 profile plugin drift")
    _require_formal_context_structure(
        target.sha256,
        profiles,
        profiles[0],
        plugins,
        require_validated=False,
    )
    anchor = issue_formal_context_anchor(target.sha256, profiles, plugins)
    return FormalContextBindings(target, profiles, plugins, anchor)


__all__ = ()
