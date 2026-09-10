"""L2 threshold profile loader with DRAFT/VALIDATED/REVOKED status."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes

ThresholdStatus = Literal["DRAFT", "VALIDATED", "REVOKED"]
MetricOperator = Literal["gte", "lte"]


@dataclass(frozen=True, slots=True)
class MetricThreshold:
    metric_id: str
    operator: MetricOperator
    value: float

    def __post_init__(self) -> None:
        if type(self.metric_id) is not str or not self.metric_id:
            raise DomainError("invalid metric threshold")
        if type(self.operator) is not str or self.operator not in ("gte", "lte"):
            raise DomainError("invalid metric operator")
        if type(self.value) is not float or self.value != self.value:
            raise DomainError("invalid metric value")
        import math

        if not math.isfinite(self.value):
            raise DomainError("invalid metric value")


@dataclass(frozen=True, slots=True)
class ThresholdProfile:
    profile_id: str
    revision: str
    status: ThresholdStatus
    style_pack_id: str
    domain_profile: str
    encoder_id: str
    encoder_revision: str
    preprocessing_version: str
    calibration_dataset_sha256: Sha256
    validation_dataset_sha256: Sha256
    thresholds: tuple[MetricThreshold, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in (
            "DRAFT",
            "VALIDATED",
            "REVOKED",
        ):
            raise DomainError("invalid threshold status")
        for name in (
            "profile_id",
            "revision",
            "style_pack_id",
            "domain_profile",
            "encoder_id",
            "encoder_revision",
            "preprocessing_version",
        ):
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise DomainError("invalid threshold profile field")
        if type(self.thresholds) is not tuple or not self.thresholds:
            raise DomainError("thresholds required")
        if any(type(t) is not MetricThreshold for t in self.thresholds):
            raise DomainError("invalid thresholds")
        if type(self.calibration_dataset_sha256) is not Sha256:
            raise DomainError("invalid calibration hash")
        if type(self.validation_dataset_sha256) is not Sha256:
            raise DomainError("invalid validation hash")

    def require_for_gate(self) -> None:
        if self.status is not None and self.status != "VALIDATED":
            raise DomainError("required gate needs VALIDATED threshold profile")
        if self.status != "VALIDATED":
            raise DomainError("required gate needs VALIDATED threshold profile")


_KEYS = {
    "profile_id",
    "revision",
    "status",
    "style_pack_id",
    "domain_profile",
    "encoder_id",
    "encoder_revision",
    "preprocessing_version",
    "calibration_dataset_sha256",
    "validation_dataset_sha256",
    "thresholds",
}


def load_threshold_profile(data: bytes) -> ThresholdProfile:
    if type(data) is not bytes:
        raise DomainError("invalid threshold profile")
    try:
        primitive = json.loads(data)
    except json.JSONDecodeError:
        raise DomainError("invalid threshold profile") from None
    if type(primitive) is not dict or set(primitive) != _KEYS:
        raise DomainError("invalid threshold profile")
    raw_thresholds = primitive["thresholds"]
    if type(raw_thresholds) is not list or not raw_thresholds:
        raise DomainError("invalid threshold profile")
    thresholds: list[MetricThreshold] = []
    for item in raw_thresholds:
        if type(item) is not dict or set(item) != {"metric_id", "operator", "value"}:
            raise DomainError("invalid threshold profile")
        value = item["value"]
        if type(value) is int and not isinstance(value, bool):
            value = float(value)
        thresholds.append(MetricThreshold(item["metric_id"], item["operator"], value))
    return ThresholdProfile(
        primitive["profile_id"],
        primitive["revision"],
        primitive["status"],
        primitive["style_pack_id"],
        primitive["domain_profile"],
        primitive["encoder_id"],
        primitive["encoder_revision"],
        primitive["preprocessing_version"],
        Sha256(primitive["calibration_dataset_sha256"]),
        Sha256(primitive["validation_dataset_sha256"]),
        tuple(thresholds),
    )


def dump_threshold_profile(profile: ThresholdProfile) -> bytes:
    if type(profile) is not ThresholdProfile:
        raise DomainError("invalid threshold profile")
    primitive = {
        "profile_id": profile.profile_id,
        "revision": profile.revision,
        "status": profile.status,
        "style_pack_id": profile.style_pack_id,
        "domain_profile": profile.domain_profile,
        "encoder_id": profile.encoder_id,
        "encoder_revision": profile.encoder_revision,
        "preprocessing_version": profile.preprocessing_version,
        "calibration_dataset_sha256": profile.calibration_dataset_sha256.value,
        "validation_dataset_sha256": profile.validation_dataset_sha256.value,
        "thresholds": [
            {
                "metric_id": t.metric_id,
                "operator": t.operator,
                "value": t.value,
            }
            for t in profile.thresholds
        ],
    }
    return json.dumps(primitive, sort_keys=True, separators=(",", ":")).encode("utf-8")


def profile_content_hash(profile: ThresholdProfile) -> Sha256:
    return hash_bytes(dump_threshold_profile(profile))
