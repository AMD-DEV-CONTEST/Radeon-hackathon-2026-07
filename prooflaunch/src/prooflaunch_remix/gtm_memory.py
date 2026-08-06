from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class MemoryPolicyError(ValueError):
    """A fail-closed memory policy decision."""


class ScopeLevel(str, Enum):
    ORG = "org"
    PROJECT = "project"
    CAMPAIGN = "campaign"


class MemoryKind(str, Enum):
    APPROVED_FACT = "approved_fact"
    OBSERVED_RESULT = "observed_result"
    WORKING_NOTE = "working_note"
    GENERATED_DRAFT = "generated_draft"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LONG_TERM_KINDS = {MemoryKind.APPROVED_FACT, MemoryKind.OBSERVED_RESULT}
_FORBIDDEN_PAYLOAD_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "private_reasoning",
    "scratchpad",
}


def _parse_time(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MemoryPolicyError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise MemoryPolicyError(f"{field_name} must include a timezone")
    return parsed


def _required(value: str, *, field_name: str) -> None:
    if not value or not value.strip():
        raise MemoryPolicyError(f"{field_name} is required")


def _json_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MemoryPolicyError("memory value must be JSON serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


def _has_forbidden_payload(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).casefold() in _FORBIDDEN_PAYLOAD_KEYS:
                return True
            if _has_forbidden_payload(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_forbidden_payload(child) for child in value)
    return False


@dataclass(frozen=True)
class MemoryScope:
    org_id: str
    project_id: str | None = None
    campaign_id: str | None = None

    def __post_init__(self) -> None:
        _required(self.org_id, field_name="org_id")
        if self.project_id is not None:
            _required(self.project_id, field_name="project_id")
        if self.campaign_id is not None:
            _required(self.campaign_id, field_name="campaign_id")
        if self.campaign_id is not None and self.project_id is None:
            raise MemoryPolicyError("campaign scope requires project_id")

    @property
    def level(self) -> ScopeLevel:
        if self.campaign_id is not None:
            return ScopeLevel.CAMPAIGN
        if self.project_id is not None:
            return ScopeLevel.PROJECT
        return ScopeLevel.ORG


@dataclass(frozen=True)
class MemorySource:
    uri: str
    sha256: str
    owner: str
    storage_allowed: bool

    def __post_init__(self) -> None:
        _required(self.uri, field_name="source.uri")
        _required(self.owner, field_name="source.owner")
        if not _SHA256.fullmatch(self.sha256):
            raise MemoryPolicyError("source.sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class MemoryEntry:
    entry_id: str
    key: str
    value: Any
    kind: MemoryKind
    scope: MemoryScope
    source: MemorySource
    owner: str
    valid_from: str
    valid_until: str | None
    approval_status: ApprovalStatus
    approved_by: str | None
    supersedes: tuple[str, ...] = ()
    temporary_run_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("entry_id", self.entry_id),
            ("key", self.key),
            ("owner", self.owner),
        ):
            _required(value, field_name=field_name)
        _json_digest(self.value)
        if _has_forbidden_payload(self.value):
            raise MemoryPolicyError("hidden reasoning cannot enter project memory")
        starts = _parse_time(self.valid_from, field_name="valid_from")
        if self.valid_until is not None:
            ends = _parse_time(self.valid_until, field_name="valid_until")
            if ends <= starts:
                raise MemoryPolicyError("valid_until must follow valid_from")
        if self.approval_status == ApprovalStatus.APPROVED:
            if not self.approved_by or not self.approved_by.strip():
                raise MemoryPolicyError("approved memory requires approved_by")
        elif self.approved_by is not None:
            raise MemoryPolicyError(
                "approved_by must be absent unless approval_status is approved"
            )
        if self.temporary_run_id is not None:
            _required(self.temporary_run_id, field_name="temporary_run_id")
        if self.entry_id in self.supersedes:
            raise MemoryPolicyError("memory cannot supersede itself")
        if len(self.supersedes) != len(set(self.supersedes)):
            raise MemoryPolicyError("supersedes values must be unique")

    @property
    def content_sha256(self) -> str:
        return _json_digest(asdict(self))

    def is_current(self, at: str) -> bool:
        now = _parse_time(at, field_name="at")
        if now < _parse_time(self.valid_from, field_name="valid_from"):
            return False
        return self.valid_until is None or now < _parse_time(
            self.valid_until, field_name="valid_until"
        )


@dataclass(frozen=True)
class CrossCampaignGrant:
    org_id: str
    project_id: str
    source_campaign_id: str
    target_campaign_id: str
    approved_by: str
    valid_from: str
    valid_until: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("org_id", self.org_id),
            ("project_id", self.project_id),
            ("source_campaign_id", self.source_campaign_id),
            ("target_campaign_id", self.target_campaign_id),
            ("approved_by", self.approved_by),
        ):
            _required(value, field_name=field_name)
        if self.source_campaign_id == self.target_campaign_id:
            raise MemoryPolicyError("cross-campaign grant must cross campaigns")
        starts = _parse_time(self.valid_from, field_name="valid_from")
        ends = _parse_time(self.valid_until, field_name="valid_until")
        if ends <= starts:
            raise MemoryPolicyError("grant valid_until must follow valid_from")

    def allows(
        self, source: MemoryScope, target: MemoryScope, *, at: str
    ) -> bool:
        now = _parse_time(at, field_name="at")
        return (
            source.org_id == target.org_id == self.org_id
            and source.project_id == target.project_id == self.project_id
            and source.campaign_id == self.source_campaign_id
            and target.campaign_id == self.target_campaign_id
            and _parse_time(self.valid_from, field_name="valid_from")
            <= now
            < _parse_time(self.valid_until, field_name="valid_until")
        )


@dataclass(frozen=True)
class MemoryEvent:
    sequence: int
    action: str
    entry_id: str
    actor: str
    entry_sha256: str


class ProjectMemory:
    """Scoped, provenance-preserving GTM memory with fail-closed retrieval.

    Run memory lives in a separate ephemeral map. Only approved facts and
    observed results can be promoted to the durable map. Cross-campaign reads
    need a current, explicit grant; no grant is inferred from shared projects.
    """

    def __init__(self) -> None:
        self._durable: dict[str, MemoryEntry] = {}
        self._run_entries: dict[str, MemoryEntry] = {}
        self._events: list[MemoryEvent] = []

    @property
    def durable_count(self) -> int:
        return len(self._durable)

    @property
    def temporary_count(self) -> int:
        return len(self._run_entries)

    @property
    def events(self) -> tuple[MemoryEvent, ...]:
        return tuple(self._events)

    def stage_run(self, entry: MemoryEntry) -> None:
        if entry.temporary_run_id is None:
            raise MemoryPolicyError("run memory requires temporary_run_id")
        self._assert_unique(entry.entry_id)
        stored = copy.deepcopy(entry)
        self._run_entries[entry.entry_id] = stored
        self._record("stage_run", stored, stored.owner)

    def remember(self, entry: MemoryEntry, *, actor: str) -> None:
        """Write a deliberately durable item after all gates pass."""

        _required(actor, field_name="actor")
        self._assert_unique(entry.entry_id)
        self._admit_long_term(entry)
        self._validate_supersedes(entry)
        stored = copy.deepcopy(entry)
        self._durable[entry.entry_id] = stored
        self._record("remember", stored, actor)

    def promote(self, entry_id: str, *, actor: str) -> MemoryEntry:
        """Promote one run item without ever copying working notes or drafts."""

        _required(actor, field_name="actor")
        try:
            staged = self._run_entries[entry_id]
        except KeyError as exc:
            raise MemoryPolicyError("temporary memory entry not found") from exc
        promoted = replace(staged, temporary_run_id=None)
        self._admit_long_term(promoted)
        self._validate_supersedes(promoted)
        stored = copy.deepcopy(promoted)
        self._durable[promoted.entry_id] = stored
        del self._run_entries[entry_id]
        self._record("promote", stored, actor)
        return copy.deepcopy(stored)

    def discard_run(self, run_id: str, *, actor: str) -> tuple[str, ...]:
        _required(run_id, field_name="run_id")
        _required(actor, field_name="actor")
        removed = tuple(
            sorted(
                entry_id
                for entry_id, entry in self._run_entries.items()
                if entry.temporary_run_id == run_id
            )
        )
        for entry_id in removed:
            entry = self._run_entries.pop(entry_id)
            self._record("discard_run", entry, actor)
        return removed

    def get(
        self,
        entry_id: str,
        *,
        target_scope: MemoryScope,
        at: str,
        grants: tuple[CrossCampaignGrant, ...] = (),
    ) -> MemoryEntry:
        """Read one durable entry, hiding temporary memory by construction."""

        try:
            entry = self._durable[entry_id]
        except KeyError as exc:
            raise MemoryPolicyError("memory unavailable") from exc
        if not self._scope_allowed(entry.scope, target_scope, at=at, grants=grants):
            raise MemoryPolicyError("memory access denied")
        self._assert_readable(entry, at=at)
        if any(
            entry.entry_id in candidate.supersedes
            and candidate.approval_status == ApprovalStatus.APPROVED
            and self._scope_allowed(
                candidate.scope, target_scope, at=at, grants=grants
            )
            and _parse_time(at, field_name="at")
            >= _parse_time(candidate.valid_from, field_name="valid_from")
            for candidate in self._durable.values()
        ):
            raise MemoryPolicyError("memory has been superseded")
        return copy.deepcopy(entry)

    def read(
        self,
        key: str,
        *,
        target_scope: MemoryScope,
        at: str,
        grants: tuple[CrossCampaignGrant, ...] = (),
    ) -> tuple[MemoryEntry, ...]:
        """Resolve a key, failing closed on stale, unapproved or conflicting truth."""

        _required(key, field_name="key")
        _parse_time(at, field_name="at")
        candidates = [
            entry
            for entry in self._durable.values()
            if entry.key == key
            and self._scope_allowed(entry.scope, target_scope, at=at, grants=grants)
        ]
        if not candidates:
            raise MemoryPolicyError("no authorized memory for key")

        # An approved supersession remains authoritative after it becomes
        # effective. If it later expires, older truth does not silently revive.
        effective_approved = [
            entry
            for entry in candidates
            if entry.approval_status == ApprovalStatus.APPROVED
            and _parse_time(at, field_name="at")
            >= _parse_time(entry.valid_from, field_name="valid_from")
        ]
        superseded = {
            predecessor
            for entry in effective_approved
            for predecessor in entry.supersedes
        }
        current = [
            entry
            for entry in candidates
            if entry.entry_id not in superseded
            and entry.approval_status == ApprovalStatus.APPROVED
            and entry.is_current(at)
        ]
        if not current:
            raise MemoryPolicyError("no current approved memory for key")

        values = {_json_digest(entry.value) for entry in current}
        if len(values) != 1:
            raise MemoryPolicyError("conflicting approved memory; resolution required")

        # Equivalent copies are deduplicated deterministically. The latest
        # valid_from wins, with entry_id as a stable tie-breaker.
        selected = max(current, key=lambda item: (item.valid_from, item.entry_id))
        return (copy.deepcopy(selected),)

    def _assert_unique(self, entry_id: str) -> None:
        if entry_id in self._durable or entry_id in self._run_entries:
            raise MemoryPolicyError("memory entry_id already exists")

    @staticmethod
    def _admit_long_term(entry: MemoryEntry) -> None:
        if entry.temporary_run_id is not None:
            raise MemoryPolicyError("temporary run memory cannot be written long-term")
        if entry.kind not in _LONG_TERM_KINDS:
            raise MemoryPolicyError(
                "only approved facts and observed results enter long-term memory"
            )
        if entry.approval_status != ApprovalStatus.APPROVED:
            raise MemoryPolicyError("long-term memory must be explicitly approved")
        if not entry.source.storage_allowed:
            raise MemoryPolicyError("source does not permit durable storage")

    def _validate_supersedes(self, entry: MemoryEntry) -> None:
        for predecessor_id in entry.supersedes:
            try:
                predecessor = self._durable[predecessor_id]
            except KeyError as exc:
                raise MemoryPolicyError("superseded memory entry not found") from exc
            if predecessor.key != entry.key:
                raise MemoryPolicyError("supersession must preserve semantic key")
            if predecessor.scope != entry.scope:
                raise MemoryPolicyError("supersession must remain in the same scope")

    @staticmethod
    def _assert_readable(entry: MemoryEntry, *, at: str) -> None:
        if entry.approval_status != ApprovalStatus.APPROVED:
            raise MemoryPolicyError("memory is not approved")
        if not entry.is_current(at):
            raise MemoryPolicyError("memory is not currently valid")

    @staticmethod
    def _scope_allowed(
        source: MemoryScope,
        target: MemoryScope,
        *,
        at: str,
        grants: tuple[CrossCampaignGrant, ...],
    ) -> bool:
        if source.org_id != target.org_id:
            return False
        if source.level == ScopeLevel.ORG:
            return True
        if source.project_id != target.project_id:
            return False
        if source.level == ScopeLevel.PROJECT:
            return True
        if source.campaign_id == target.campaign_id:
            return True
        if target.campaign_id is None:
            return False
        return any(grant.allows(source, target, at=at) for grant in grants)

    def _record(self, action: str, entry: MemoryEntry, actor: str) -> None:
        _required(actor, field_name="actor")
        self._events.append(
            MemoryEvent(
                sequence=len(self._events) + 1,
                action=action,
                entry_id=entry.entry_id,
                actor=actor,
                entry_sha256=entry.content_sha256,
            )
        )
