"""Content-addressed formal calibration target-cell contract."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.calibration.evidence_io import (
    _exact,
    _load_canonical,
    _pin,
    _text,
    evidence_sha256,
)
from specstyle.domain.identifiers import Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import ResourcePin

_TARGET_KEYS = {
    "schema_version",
    "style_pack_id",
    "style_pack_pin",
    "domain_profile",
    "domain_verifier_version",
    "output_profile",
    "output_profile_pin",
    "generation_profile",
    "compiler_pin",
    "rule_catalog_pin",
    "metrics",
}
_METRIC_KEYS = {
    "layer",
    "observation_unit",
    "metric_id",
    "operator",
    "implementation_pin",
    "binding_pin",
    "verifier_pin",
    "preprocessor_pin",
}
_DOMAINS = {"product_instance", "face_identity", "structure_only"}
_OUTPUTS = {"xhs_grid", "talking_head_cover", "background_sequence"}
_FORMAL_METRICS = (
    ("L2", "batch", "batch_style_consistency", "lte"),
    ("L2", "item", "reference_style_statistics_similarity", "gte"),
    ("L3", "item", "structure_edge_similarity", "gte"),
)


def _resource_pin(value: object, name: str) -> ResourcePin:
    raw = _pin(value, name)
    return ResourcePin(raw["id"], raw["revision"], Sha256(raw["sha256"]))


@dataclass(frozen=True, slots=True)
class TargetMetric:
    layer: str
    observation_unit: str
    metric_id: Identifier
    operator: str
    implementation_pin: ResourcePin
    binding_pin: ResourcePin
    verifier_pin: ResourcePin
    preprocessor_pin: ResourcePin

    def __post_init__(self) -> None:
        if (
            self.layer not in {"L2", "L3"}
            or self.observation_unit not in {"item", "batch"}
            or self.operator not in {"gte", "lte"}
            or (self.layer == "L3" and self.observation_unit != "item")
            or type(self.metric_id) is not Identifier
            or any(
                type(pin) is not ResourcePin
                for pin in (
                    self.implementation_pin,
                    self.binding_pin,
                    self.verifier_pin,
                    self.preprocessor_pin,
                )
            )
        ):
            raise DomainError("invalid target cell metric")


@dataclass(frozen=True, slots=True)
class TargetCell:
    sha256: Sha256
    style_pack_id: Identifier
    style_pack_pin: ResourcePin
    domain_profile: str
    domain_verifier_version: str
    output_profile: str
    output_profile_pin: ResourcePin
    compiler_pin: ResourcePin
    rule_catalog_pin: ResourcePin
    metrics: tuple[TargetMetric, ...]

    def __post_init__(self) -> None:
        ordered = tuple((item.layer, item.metric_id.value) for item in self.metrics)
        contract = tuple(
            (
                item.layer,
                item.observation_unit,
                item.metric_id.value,
                item.operator,
            )
            for item in self.metrics
        )
        if (
            type(self.sha256) is not Sha256
            or type(self.style_pack_id) is not Identifier
            or type(self.style_pack_pin) is not ResourcePin
            or self.domain_profile not in _DOMAINS
            or not self.domain_verifier_version
            or self.output_profile not in _OUTPUTS
            or any(
                type(pin) is not ResourcePin
                for pin in (
                    self.output_profile_pin,
                    self.compiler_pin,
                    self.rule_catalog_pin,
                )
            )
            or not self.metrics
            or any(type(item) is not TargetMetric for item in self.metrics)
            or ordered != tuple(sorted(ordered))
            or len(set(ordered)) != len(ordered)
            or contract != _FORMAL_METRICS
        ):
            raise DomainError("invalid target cell")

    def require_metric(self, metric_id: str) -> TargetMetric:
        matches = tuple(
            item for item in self.metrics if item.metric_id.value == metric_id
        )
        if len(matches) != 1:
            raise DomainError("target cell metric unavailable")
        return matches[0]


def _metric(value: object) -> TargetMetric:
    raw = _exact(value, _METRIC_KEYS, "target cell metric")
    return TargetMetric(
        raw["layer"],
        raw["observation_unit"],
        Identifier(raw["metric_id"]),
        raw["operator"],
        _resource_pin(raw["implementation_pin"], "metric implementation pin"),
        _resource_pin(raw["binding_pin"], "metric binding pin"),
        _resource_pin(raw["verifier_pin"], "metric verifier pin"),
        _resource_pin(raw["preprocessor_pin"], "metric preprocessor pin"),
    )


def load_target_cell(data: bytes) -> TargetCell:
    """Load one canonical immutable Production target cell."""
    raw = _exact(_load_canonical(data), _TARGET_KEYS, "target cell")
    if (
        raw["schema_version"] != "specstyle.production.target_cell.v1"
        or raw["generation_profile"] != "production"
        or type(raw["metrics"]) is not list
        or not raw["metrics"]
    ):
        raise DomainError("invalid target cell")
    return TargetCell(
        evidence_sha256(data),
        Identifier(raw["style_pack_id"]),
        _resource_pin(raw["style_pack_pin"], "style pack pin"),
        raw["domain_profile"],
        _text(raw["domain_verifier_version"], "domain verifier version"),
        raw["output_profile"],
        _resource_pin(raw["output_profile_pin"], "output profile pin"),
        _resource_pin(raw["compiler_pin"], "compiler pin"),
        _resource_pin(raw["rule_catalog_pin"], "rule catalog pin"),
        tuple(_metric(item) for item in raw["metrics"]),
    )


__all__ = ("TargetCell", "TargetMetric", "load_target_cell")
