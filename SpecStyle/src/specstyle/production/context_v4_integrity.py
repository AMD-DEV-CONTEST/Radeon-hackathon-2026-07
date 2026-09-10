"""Independent loader-issued integrity anchor for nested context v4 state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from specstyle.calibration.evidence_io import canonical_json
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes

_ANCHOR_SEAL = object()


def _pin(value: object) -> dict[str, str]:
    return {
        "id": value.id,  # type: ignore[union-attr]
        "revision": value.revision,  # type: ignore[union-attr]
        "sha256": value.sha256.value,  # type: ignore[union-attr]
    }


def _metric_binding(value: object) -> dict[str, Any]:
    return {
        "target_cell_sha256": value.target_cell_sha256.value,
        "study_id": value.study_id,
        "layer": value.layer,
        "observation_unit": value.observation_unit,
        "metric_id": value.metric_id.value,
        "operator": value.operator,
        "threshold": value.threshold,
        "implementation_pin": _pin(value.implementation_pin),
        "binding_pin": _pin(value.binding_pin),
        "verifier_pin": _pin(value.verifier_pin),
        "preprocessor_pin": _pin(value.preprocessor_pin),
        "prepared_evidence_sha256": value.prepared_evidence_sha256.value,
        "test_reveal_sha256": value.test_reveal_sha256.value,
        "annotation_protocol_sha256": value.annotation_protocol_sha256.value,
        "metric_approval_sha256": value.metric_approval_sha256.value,
    }


def _profile_approval(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "production_approval_sha256": value.production_approval_sha256.value,
        "target_cell_sha256": value.target_cell_sha256.value,
        "source": value.source,
        "threshold_profile_pin": _pin(value.threshold_profile_pin),
        "metric_approval_sha256s": [
            item.metric_approval_sha256.value for item in value.metrics
        ],
    }


def _profile(value: object) -> dict[str, Any]:
    return {
        "target_cell_sha256": value.target_cell_sha256.value,
        "pin": _pin(value.pin),
        "logical_name": value.logical_name,
        "source": value.source,
        "status": value.status,
        "style_pack_id": value.style_pack_id.value,
        "domain_profile": value.domain_profile,
        "binding_pin": _pin(value.binding_pin),
        "metrics": [
            {
                "metric_id": item.metric_id.value,
                "operator": item.operator,
                "value": item.value,
            }
            for item in value.metrics
        ],
        "calibration_dataset_sha256": value.calibration_dataset_sha256.value,
        "validation_dataset_sha256": value.validation_dataset_sha256.value,
        "annotation_protocol_sha256": value.annotation_protocol_sha256.value,
        "production_approval_sha256": None
        if value.production_approval_sha256 is None
        else value.production_approval_sha256.value,
        "metric_bindings": [_metric_binding(item) for item in value.metric_bindings],
        "profile_approval": _profile_approval(value.profile_approval),
    }


def _rule(value: object) -> dict[str, Any]:
    return {
        "rule_id": value.rule_id.value,
        "kind": value.kind,
        "level": value.level.value,
        "scope": value.scope.value,
        "requirement": value.requirement,
        "supported_domains": list(value.supported_domains),
        "supported_output_profiles": list(value.supported_output_profiles),
        "verifier_pin": _pin(value.verifier_pin),
        "threshold_source": value.threshold_source,
        "metric_id": None if value.metric_id is None else value.metric_id.value,
        "priority": value.priority,
        "affected_by_actions": [item.value for item in value.affected_by_actions],
    }


def _plugin(value: object) -> dict[str, Any]:
    return {
        "pin": _pin(value.pin),
        "domain_profile": value.domain_profile,
        "domain_verifier_version": value.domain_verifier_version,
        "supported_output_profiles": list(value.supported_output_profiles),
        "rules": [_rule(item) for item in value.rules],
    }


def _digest(
    target_cell_sha256: Sha256,
    profiles: tuple[object, ...],
    plugins: tuple[object, ...],
) -> Sha256:
    return hash_bytes(
        canonical_json(
            {
                "target_cell_sha256": target_cell_sha256.value,
                "threshold_profiles": [_profile(item) for item in profiles],
                "l3_plugins": [_plugin(item) for item in plugins],
            }
        )
    )


@dataclass(frozen=True, slots=True, init=False)
class FormalContextAnchor:
    sha256: Sha256
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("v4 formal context anchors are issued only by the loader")

    def __post_init__(self) -> None:
        if type(self.sha256) is not Sha256 or self._seal is not _ANCHOR_SEAL:
            raise DomainError("invalid v4 formal context anchor")


def issue_formal_context_anchor(
    target_cell_sha256: Sha256,
    profiles: tuple[object, ...],
    plugins: tuple[object, ...],
) -> FormalContextAnchor:
    issued = object.__new__(FormalContextAnchor)
    object.__setattr__(issued, "sha256", _digest(target_cell_sha256, profiles, plugins))
    object.__setattr__(issued, "_seal", _ANCHOR_SEAL)
    issued.__post_init__()
    return issued


def require_formal_context_anchor(
    anchor: object,
    target_cell_sha256: Sha256,
    profiles: tuple[object, ...],
    plugins: tuple[object, ...],
) -> None:
    if type(anchor) is not FormalContextAnchor:
        raise DomainError("invalid v4 formal context anchor")
    anchor.__post_init__()
    if anchor.sha256 != _digest(target_cell_sha256, profiles, plugins):
        raise DomainError("v4 formal context integrity drift")


__all__ = ()
