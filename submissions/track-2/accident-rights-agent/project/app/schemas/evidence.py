"""Typed evidence contracts shared by every agent.

The raw source file is immutable. Derived nodes and facts always point back to
that source through stable IDs and machine-readable locators.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceKind(str, Enum):
    PDF = "pdf"
    IMAGE = "image"
    VIDEO = "video"


class SourceRole(str, Enum):
    ACCIDENT_DETERMINATION = "accident_determination"
    DELIVERY_INFORMATION = "delivery_information"
    APPRAISAL_REPORT = "appraisal_report"
    VEHICLE_DOCUMENT = "vehicle_document"
    VEHICLE_REGISTRATION = "vehicle_registration"
    VEHICLE_CERTIFICATE_CCC = "vehicle_certificate_ccc"
    VEHICLE_TECHNICAL_PARAMETERS = "vehicle_technical_parameters"
    SCENE_PHOTO = "scene_photo"
    DASHCAM_VIDEO = "dashcam_video"
    ROAD_SIGNAL_EVIDENCE = "road_signal_evidence"
    INQUIRY_RECORD = "inquiry_record"
    MEDICAL_RECORD = "medical_record"
    REPAIR_RECORD = "repair_record"
    INSURANCE_POLICY = "insurance_policy"
    OTHER = "other"


class ProcessingStatus(str, Enum):
    REGISTERED = "registered"
    PROCESSING = "processing"
    PARSED = "parsed"
    FAILED = "failed"


class FactStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    DISPUTED = "disputed"


@dataclass(frozen=True)
class SourceFile:
    source_id: str
    case_id: str
    original_name: str
    stored_path: str
    media_type: str
    kind: SourceKind
    role: SourceRole
    sha256: str
    size_bytes: int
    created_at: str = field(default_factory=utc_now)
    status: ProcessingStatus = ProcessingStatus.REGISTERED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceNode:
    node_id: str
    case_id: str
    source_id: str
    node_type: str
    locator: dict[str, Any]
    content: str | None = None
    content_sha256: str | None = None
    confidence: float = 1.0
    extraction_method: str = "deterministic"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Fact:
    fact_id: str
    case_id: str
    statement: str
    subject: str
    predicate: str
    value: str
    source_node_ids: tuple[str, ...]
    confidence: float
    status: FactStatus = FactStatus.UNVERIFIED
    extraction_method: str = "local_vlm"
    model: str | None = None
    uncertainty: str = ""
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_node_ids"] = list(self.source_node_ids)
        return payload


@dataclass(frozen=True)
class TimelineEvent:
    event_id: str
    case_id: str
    label: str
    relative_order: int
    source_node_ids: tuple[str, ...]
    timestamp_seconds: float | None = None
    confidence: float = 0.5
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_node_ids"] = list(self.source_node_ids)
        return payload


@dataclass(frozen=True)
class EvidenceConflict:
    conflict_id: str
    case_id: str
    subject: str
    predicate: str
    fact_ids: tuple[str, ...]
    description: str
    severity: str = "review"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fact_ids"] = list(self.fact_ids)
        return payload
