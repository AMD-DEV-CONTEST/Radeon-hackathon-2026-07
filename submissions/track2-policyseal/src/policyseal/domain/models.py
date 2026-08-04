from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from policyseal.domain.enums import (
    Action,
    ApprovalStatus,
    Channel,
    Classification,
    ContentCategory,
    DecisionOrigin,
    FileKind,
    Purpose,
    RecipientProfile,
    RevisionStatus,
)
from policyseal.domain.errors import InvalidContextError, InvalidDecisionError


@dataclass(frozen=True, slots=True)
class DisclosureContext:
    recipient: RecipientProfile
    organization: str
    recipient_id: str
    purpose: Purpose
    channel: Channel
    classification: Classification
    policy_version: str

    def __post_init__(self) -> None:
        for field_name in ("organization", "recipient_id", "policy_version"):
            if not getattr(self, field_name).strip():
                raise InvalidContextError(f"{field_name} must not be blank")

    @property
    def sha256(self) -> str:
        payload = {
            "channel": self.channel.value,
            "classification": self.classification.value,
            "organization": self.organization,
            "policy_version": self.policy_version,
            "purpose": self.purpose.value,
            "recipient": self.recipient.value,
            "recipient_id": self.recipient_id,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    def with_channel(self, channel: Channel) -> DisclosureContext:
        return DisclosureContext(
            recipient=self.recipient,
            organization=self.organization,
            recipient_id=self.recipient_id,
            purpose=self.purpose,
            channel=channel,
            classification=self.classification,
            policy_version=self.policy_version,
        )

    @classmethod
    def supplier_bidder_corporate_email(cls) -> DisclosureContext:
        return cls(
            recipient=RecipientProfile.SUPPLIER_BIDDER_A,
            organization="supplier-a.example",
            recipient_id="bidder-a@corp.example",
            purpose=Purpose.SUPPLIER_BID_FEEDBACK,
            channel=Channel.CORPORATE_EMAIL,
            classification=Classification.CONFIDENTIAL,
            policy_version="1.0.0",
        )

    @classmethod
    def incident_responder_secure_exchange(cls) -> DisclosureContext:
        return cls(
            recipient=RecipientProfile.EXTERNAL_INCIDENT_RESPONDER,
            organization="response-partner.example",
            recipient_id="incident-team@response-partner.example",
            purpose=Purpose.INCIDENT_RESPONSE_INVESTIGATION,
            channel=Channel.SECURE_FILE_EXCHANGE,
            classification=Classification.STRICTLY_CONFIDENTIAL,
            policy_version="1.0.0",
        )

    @classmethod
    def candidate_supplier_corporate_email(cls) -> DisclosureContext:
        return cls(
            recipient=RecipientProfile.CANDIDATE_SUPPLIER,
            organization="candidate-supplier.example",
            recipient_id="contracts@candidate-supplier.example",
            purpose=Purpose.CONTRACT_TERMS_PREVIEW,
            channel=Channel.CORPORATE_EMAIL,
            classification=Classification.CONFIDENTIAL,
            policy_version="1.0.0",
        )


@dataclass(frozen=True, slots=True)
class DocumentRegion:
    id: str
    file_kind: FileKind
    location: str
    order: int
    text: str
    category: ContentCategory = ContentCategory.UNCLASSIFIED
    owner_id: str | None = None
    semantic_reason_code: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.location.strip():
            raise ValueError("region id and location must not be blank")
        if self.order < 0:
            raise ValueError("region order must be non-negative")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    region_id: str
    category: ContentCategory
    action: Action
    rule_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason_code: str
    reason: str
    policy_version: str
    policy_sha256: str
    origin: DecisionOrigin = DecisionOrigin.DETERMINISTIC
    transform: str | None = None

    def __post_init__(self) -> None:
        if not self.region_id.strip() or not self.policy_version.strip():
            raise InvalidDecisionError("region_id and policy_version must not be blank")
        if not self.rule_ids or any(not rule_id.strip() for rule_id in self.rule_ids):
            raise InvalidDecisionError("every decision must cite at least one rule")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise InvalidDecisionError("every decision must cite at least one evidence record")
        if not self.reason_code.strip():
            raise InvalidDecisionError("every decision must include a reason code")
        if not self.reason.strip():
            raise InvalidDecisionError("every decision must include a reason")
        if len(self.policy_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.policy_sha256
        ):
            raise InvalidDecisionError("policy_sha256 must be a lowercase hexadecimal digest")


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")

    @classmethod
    def from_bytes(cls, data: bytes) -> SourceFingerprint:
        return cls(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))


@dataclass(frozen=True, slots=True)
class RevisionStageEvent:
    revision_id: str
    sequence: int
    stage: str
    status: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if not self.revision_id.strip() or not self.stage.strip() or not self.status.strip():
            raise ValueError("revision stage fields must not be blank")
        if self.sequence < 1:
            raise ValueError("revision stage sequence must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("revision stage timestamps must be timezone aware")


@dataclass(frozen=True, slots=True)
class StoredArtifactRecord:
    task_id: str
    revision_id: str | None
    namespace: str
    storage_id: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.task_id, self.namespace, self.storage_id)):
            raise ValueError("stored artifact fields must not be blank")
        if self.revision_id is not None and not self.revision_id.strip():
            raise ValueError("artifact revision ID must not be blank")


@dataclass(frozen=True, slots=True)
class DeletionTombstone:
    id: str
    task_id: str
    revision_count: int
    source_sha256: str
    deletion_fingerprint: str
    actor_hmac: str
    policy_version: str
    deleted_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("id", "task_id", "policy_version"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        if self.revision_count < 0:
            raise ValueError("revision_count must not be negative")
        for field_name in ("source_sha256", "deletion_fingerprint", "actor_hmac"):
            digest = getattr(self, field_name)
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"{field_name} must be a lowercase digest")
        if self.deleted_at.tzinfo is None:
            raise ValueError("deleted_at must be timezone aware")


@dataclass(frozen=True, slots=True)
class RevisionIdentity:
    task_id: str
    revision_id: str
    revision_number: int
    source_sha256: str
    policy_version: str
    policy_sha256: str

    def __post_init__(self) -> None:
        if self.revision_number < 1:
            raise ValueError("revision_number must be at least one")
        for field_name in ("task_id", "revision_id", "policy_version"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        for digest_name in ("source_sha256", "policy_sha256"):
            digest = getattr(self, digest_name)
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"{digest_name} must be a lowercase hexadecimal digest")


@dataclass(frozen=True, slots=True)
class DisclosureTask:
    id: str
    requester_id: str
    file_kind: FileKind
    source: SourceFingerprint
    source_storage_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("id", "requester_id", "source_storage_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone aware")


@dataclass(frozen=True, slots=True)
class DisclosureRevision:
    id: str
    task_id: str
    revision_number: int
    requester_id: str
    context: DisclosureContext
    status: RevisionStatus
    source_sha256: str
    policy_sha256: str
    created_at: datetime
    output_storage_id: str | None = None
    output_sha256: str | None = None
    decision_manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.revision_number < 1:
            raise ValueError("revision_number must be at least one")
        for field_name in ("id", "task_id", "requester_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        for digest_name in ("source_sha256", "policy_sha256"):
            _validate_optional_digest(digest_name, getattr(self, digest_name), required=True)
        _validate_optional_digest("output_sha256", self.output_sha256)
        _validate_optional_digest("decision_manifest_sha256", self.decision_manifest_sha256)
        if (self.output_storage_id is None) != (self.output_sha256 is None):
            raise ValueError("output storage ID and checksum must be set together")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone aware")

    @property
    def identity(self) -> RevisionIdentity:
        return RevisionIdentity(
            task_id=self.task_id,
            revision_id=self.id,
            revision_number=self.revision_number,
            source_sha256=self.source_sha256,
            policy_version=self.context.policy_version,
            policy_sha256=self.policy_sha256,
        )

    @property
    def created_at_utc(self) -> datetime:
        return self.created_at.astimezone(UTC)


def _validate_optional_digest(name: str, value: str | None, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase hexadecimal digest")


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    id: str
    revision_id: str
    requester_id: str
    status: ApprovalStatus
    binding_sha256: str
    source_sha256: str
    context_sha256: str
    policy_sha256: str
    output_sha256: str
    decision_manifest_sha256: str
    expires_at: datetime
    created_at: datetime
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None
    consumed: bool = False
    reason_code: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("id", "revision_id", "requester_id"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        for digest_name in (
            "binding_sha256",
            "source_sha256",
            "context_sha256",
            "policy_sha256",
            "output_sha256",
            "decision_manifest_sha256",
        ):
            _validate_optional_digest(digest_name, getattr(self, digest_name), required=True)
        if self.expires_at.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("approval timestamps must be timezone aware")
        if self.reviewed_at is not None and self.reviewed_at.tzinfo is None:
            raise ValueError("reviewed_at must be timezone aware")
        if self.reviewer_id is not None and not self.reviewer_id.strip():
            raise ValueError("reviewer_id must not be blank")
