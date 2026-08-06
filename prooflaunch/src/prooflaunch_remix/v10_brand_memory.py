from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from .v10_contracts import V10ContractError, stable_digest


class MemoryKind(str, Enum):
    ENTITY = "entity"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    SYMBOLIC_RULE = "symbolic_rule"


class EntityKind(str, Enum):
    PRODUCT = "product"
    BRAND = "brand"
    AUDIENCE = "audience"
    CLAIM = "claim"
    CHANNEL = "channel"
    ASSET = "asset"
    CREATIVE_CONCEPT = "creative_concept"


class EdgeKind(str, Enum):
    EVIDENCE = "evidence"
    CONFLICT = "conflict"
    SUPERSEDE = "supersede"
    APPLIES_TO = "applies_to"
    PROHIBITED = "prohibited"


class PolicyAction(str, Enum):
    STORE = "store"
    RETRIEVE = "retrieve"
    UPDATE = "update"
    MERGE = "merge"
    DISCARD = "discard"
    SUMMARIZE = "summarize"
    REMEMBER = "remember"
    FORGET = "forget"


class PolicyVerdict(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    HUMAN_REVIEW = "human_review"


class PrivacyClass(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


_SHA256_LENGTH = 64
_FORBIDDEN_PAYLOAD_KEYS = {
    "chain_of_thought",
    "hidden_reasoning",
    "private_reasoning",
    "scratchpad",
}


def _parse_time(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise V10ContractError(f"{field_name} must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise V10ContractError(f"{field_name} must include a timezone")
    return parsed


def _payload_has_hidden_reasoning(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_PAYLOAD_KEYS:
                return True
            if _payload_has_hidden_reasoning(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_payload_has_hidden_reasoning(item) for item in value)
    return False


@dataclass(frozen=True)
class MemorySource:
    locator: str
    revision: str
    sha256: str
    rights_profile: str
    storage_allowed: bool
    training_allowed: bool

    def __post_init__(self) -> None:
        if not self.locator.strip() or not self.revision.strip():
            raise V10ContractError("memory source locator and revision are required")
        if len(self.sha256) != _SHA256_LENGTH or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise V10ContractError("memory source sha256 must be lowercase SHA-256")
        if not self.rights_profile.strip():
            raise V10ContractError("memory source rights profile is required")


@dataclass(frozen=True)
class MemoryAtom:
    atom_id: str
    kind: MemoryKind
    subject_id: str
    payload: Mapping[str, Any]
    source: MemorySource
    created_at: str
    valid_until: str | None
    confidence: float
    utility: float
    approved: bool
    version: int = 1
    entity_kind: EntityKind | None = None
    permanent: bool = False
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    access_roles: tuple[str, ...] = ("*",)
    token_cost: int = 1
    schema: str = "ProofLaunchMemoryAtomV1"

    def __post_init__(self) -> None:
        if not self.atom_id.strip() or not self.subject_id.strip():
            raise V10ContractError("memory atom id and subject id are required")
        if not self.payload:
            raise V10ContractError("memory atom payload cannot be empty")
        if _payload_has_hidden_reasoning(self.payload):
            raise V10ContractError("hidden reasoning cannot enter memory")
        if not 0 <= self.confidence <= 1 or not 0 <= self.utility <= 1:
            raise V10ContractError("memory confidence and utility must be in [0, 1]")
        if self.version < 1:
            raise V10ContractError("memory version must be positive")
        created = _parse_time(self.created_at, field_name="created_at")
        if self.valid_until is not None:
            expires = _parse_time(self.valid_until, field_name="valid_until")
            if expires <= created:
                raise V10ContractError("valid_until must follow created_at")
        if self.kind == MemoryKind.ENTITY and self.entity_kind is None:
            raise V10ContractError("entity memory requires an entity_kind")
        if self.kind != MemoryKind.ENTITY and self.entity_kind is not None:
            raise V10ContractError("only entity memory may declare entity_kind")
        if self.kind == MemoryKind.SYMBOLIC_RULE and not self.permanent:
            raise V10ContractError("symbolic rules belong to the permanent layer")
        if self.permanent and self.kind != MemoryKind.SYMBOLIC_RULE:
            raise V10ContractError("only symbolic rules may be permanent")
        try:
            privacy = PrivacyClass(self.privacy_class)
        except ValueError as error:
            raise V10ContractError("unknown privacy_class") from error
        if not self.access_roles or any(not role.strip() for role in self.access_roles):
            raise V10ContractError("access_roles must contain nonempty roles")
        if privacy in {PrivacyClass.CONFIDENTIAL, PrivacyClass.RESTRICTED} and (
            "*" in self.access_roles
        ):
            raise V10ContractError("confidential memory cannot grant wildcard access")
        if self.token_cost < 1:
            raise V10ContractError("memory token_cost must be positive")

    @property
    def content_sha256(self) -> str:
        return stable_digest(asdict(self))

    def expired(self, now: str) -> bool:
        return self.valid_until is not None and _parse_time(
            now, field_name="now"
        ) > _parse_time(self.valid_until, field_name="valid_until")


@dataclass(frozen=True)
class MemoryEdge:
    edge_id: str
    kind: EdgeKind
    source_atom_id: str
    target_atom_id: str
    source_locator: str
    approved: bool
    created_at: str
    resolution_atom_id: str | None = None
    approval_id: str | None = None
    schema: str = "ProofLaunchMemoryEdgeV1"

    def __post_init__(self) -> None:
        if not self.edge_id.strip():
            raise V10ContractError("memory edge id is required")
        if not self.source_atom_id.strip() or not self.target_atom_id.strip():
            raise V10ContractError("memory edge endpoints are required")
        if self.source_atom_id == self.target_atom_id:
            raise V10ContractError("memory edges cannot self-reference")
        if not self.source_locator.strip():
            raise V10ContractError("memory edge source locator is required")
        _parse_time(self.created_at, field_name="created_at")
        if (self.resolution_atom_id is None) != (self.approval_id is None):
            raise V10ContractError(
                "conflict resolution atom and approval id must be supplied together"
            )
        if self.resolution_atom_id is not None and self.kind != EdgeKind.CONFLICT:
            raise V10ContractError("only conflict edges may carry a resolution")

    @property
    def content_sha256(self) -> str:
        return stable_digest(asdict(self))


@dataclass(frozen=True)
class MemoryPolicyReceipt:
    action: PolicyAction
    verdict: PolicyVerdict
    atom_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    event_hash: str | None = None
    output_atom_id: str | None = None
    schema: str = "ProofLaunchMemoryPolicyReceiptV1"

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise V10ContractError("memory policy receipt needs reason codes")
        if any(not item.strip() for item in self.reason_codes):
            raise V10ContractError("memory policy reason codes cannot be empty")


@dataclass(frozen=True)
class MemoryEvent:
    sequence: int
    action: PolicyAction
    atom_ids: tuple[str, ...]
    previous_hash: str
    state_sha256: str
    event_hash: str
    occurred_at: str
    schema: str = "ProofLaunchMemoryEventV1"


class BrandGenomeMemory:
    """Versioned, rights-aware graph memory with deterministic policy receipts.

    The runtime stores only deployment-visible facts, labels and provenance. It
    deliberately excludes hidden chain-of-thought and never treats a conflict
    merge as truth without an explicit approved replacement.
    """

    def __init__(self) -> None:
        self._atoms: dict[str, MemoryAtom] = {}
        self._edges: dict[str, MemoryEdge] = {}
        self._tombstones: set[str] = set()
        self._quarantined: set[str] = set()
        self._events: list[MemoryEvent] = []
        self._snapshots: list[
            tuple[dict[str, MemoryAtom], dict[str, MemoryEdge], set[str], set[str]]
        ] = []
        self._event_states: dict[
            str,
            tuple[dict[str, MemoryAtom], dict[str, MemoryEdge], set[str], set[str]],
        ] = {}

    @property
    def atoms(self) -> tuple[MemoryAtom, ...]:
        return tuple(self._atoms[key] for key in sorted(self._atoms))

    @property
    def edges(self) -> tuple[MemoryEdge, ...]:
        return tuple(self._edges[key] for key in sorted(self._edges))

    @property
    def events(self) -> tuple[MemoryEvent, ...]:
        return tuple(self._events)

    @property
    def tombstones(self) -> frozenset[str]:
        return frozenset(self._tombstones)

    @property
    def quarantined(self) -> frozenset[str]:
        return frozenset(self._quarantined)

    @property
    def permanent_rules(self) -> tuple[MemoryAtom, ...]:
        return tuple(
            atom
            for atom in self.atoms
            if atom.kind == MemoryKind.SYMBOLIC_RULE
            and atom.permanent
            and atom.atom_id not in self._tombstones
        )

    def _copy_state(
        self,
    ) -> tuple[dict[str, MemoryAtom], dict[str, MemoryEdge], set[str], set[str]]:
        return (
            copy.deepcopy(self._atoms),
            copy.deepcopy(self._edges),
            set(self._tombstones),
            set(self._quarantined),
        )

    def _state_sha256(self) -> str:
        return stable_digest(
            {
                "atoms": [asdict(item) for item in self.atoms],
                "edges": [asdict(item) for item in self.edges],
                "tombstones": sorted(self._tombstones),
                "quarantined": sorted(self._quarantined),
            }
        )

    def _record(
        self,
        action: PolicyAction,
        atom_ids: Sequence[str],
        occurred_at: str,
    ) -> str:
        previous_hash = self._events[-1].event_hash if self._events else "0" * 64
        payload = {
            "sequence": len(self._events) + 1,
            "action": action.value,
            "atom_ids": tuple(atom_ids),
            "previous_hash": previous_hash,
            "state_sha256": self._state_sha256(),
            "occurred_at": occurred_at,
        }
        event_hash = stable_digest(payload)
        self._events.append(
            MemoryEvent(
                sequence=payload["sequence"],
                action=action,
                atom_ids=tuple(atom_ids),
                previous_hash=previous_hash,
                state_sha256=payload["state_sha256"],
                event_hash=event_hash,
                occurred_at=occurred_at,
            )
        )
        self._event_states[event_hash] = self._copy_state()
        return event_hash

    def _snapshot(self) -> None:
        self._snapshots.append(self._copy_state())

    @staticmethod
    def _admission(atom: MemoryAtom) -> tuple[PolicyVerdict, tuple[str, ...]]:
        if not atom.source.storage_allowed:
            return PolicyVerdict.REJECT, ("source_rights_block_storage",)
        if atom.kind == MemoryKind.SYMBOLIC_RULE and not atom.approved:
            return PolicyVerdict.HUMAN_REVIEW, (
                "permanent_rule_requires_approval",
            )
        if atom.entity_kind in {EntityKind.BRAND, EntityKind.CLAIM} and not atom.approved:
            return PolicyVerdict.HUMAN_REVIEW, (
                "high_impact_entity_requires_approval",
            )
        return PolicyVerdict.ACCEPT, ("source_bound_and_admitted",)

    def store(self, atom: MemoryAtom) -> MemoryPolicyReceipt:
        if atom.atom_id in self._atoms:
            return MemoryPolicyReceipt(
                PolicyAction.STORE,
                PolicyVerdict.REJECT,
                (atom.atom_id,),
                ("duplicate_atom_id",),
            )
        verdict, reason_codes = self._admission(atom)
        if verdict != PolicyVerdict.ACCEPT:
            return MemoryPolicyReceipt(
                PolicyAction.STORE,
                verdict,
                (atom.atom_id,),
                reason_codes,
            )
        self._snapshot()
        self._atoms[atom.atom_id] = atom
        event_hash = self._record(PolicyAction.STORE, (atom.atom_id,), atom.created_at)
        return MemoryPolicyReceipt(
            PolicyAction.STORE,
            PolicyVerdict.ACCEPT,
            (atom.atom_id,),
            reason_codes,
            event_hash,
            atom.atom_id,
        )

    def add_edge(self, edge: MemoryEdge, *, record_event: bool = True) -> str | None:
        if edge.edge_id in self._edges:
            raise V10ContractError("memory edge id already exists")
        if edge.source_atom_id not in self._atoms or edge.target_atom_id not in self._atoms:
            raise V10ContractError("memory edge endpoints must already exist")
        source = self._atoms[edge.source_atom_id]
        target = self._atoms[edge.target_atom_id]
        if edge.kind == EdgeKind.EVIDENCE and source.entity_kind != EntityKind.CLAIM:
            raise V10ContractError("evidence edges must originate from Claim entities")
        if edge.kind == EdgeKind.SUPERSEDE:
            if source.subject_id != target.subject_id or source.kind != target.kind:
                raise V10ContractError("supersede edges require the same subject and memory kind")
            if source.version >= target.version:
                raise V10ContractError("supersede edge must point from old to newer version")
        if edge.kind == EdgeKind.PROHIBITED and source.kind != MemoryKind.SYMBOLIC_RULE:
            raise V10ContractError("prohibited edges must originate from symbolic rules")
        if record_event:
            self._snapshot()
        if edge.kind == EdgeKind.CONFLICT:
            self._quarantined.update({edge.source_atom_id, edge.target_atom_id})
        self._edges[edge.edge_id] = edge
        if record_event:
            return self._record(
                PolicyAction.UPDATE,
                (edge.source_atom_id, edge.target_atom_id),
                edge.created_at,
            )
        return None

    def resolve_conflict(
        self,
        edge_id: str,
        *,
        winner_atom_id: str,
        approval_id: str,
        occurred_at: str,
    ) -> str:
        edge = self._edges.get(edge_id)
        if edge is None or edge.kind != EdgeKind.CONFLICT:
            raise V10ContractError("conflict resolution requires a known conflict edge")
        if winner_atom_id not in {edge.source_atom_id, edge.target_atom_id}:
            raise V10ContractError("conflict winner must be one of the edge endpoints")
        if not approval_id.strip():
            raise V10ContractError("conflict resolution requires approval")
        loser = (
            edge.target_atom_id
            if winner_atom_id == edge.source_atom_id
            else edge.source_atom_id
        )
        self._snapshot()
        self._edges[edge_id] = MemoryEdge(
            edge_id=edge.edge_id,
            kind=edge.kind,
            source_atom_id=edge.source_atom_id,
            target_atom_id=edge.target_atom_id,
            source_locator=edge.source_locator,
            approved=True,
            created_at=edge.created_at,
            resolution_atom_id=winner_atom_id,
            approval_id=approval_id,
        )
        self._quarantined.discard(winner_atom_id)
        self._quarantined.add(loser)
        return self._record(
            PolicyAction.UPDATE,
            (edge.source_atom_id, edge.target_atom_id, winner_atom_id),
            occurred_at,
        )

    @staticmethod
    def _privacy_allowed(
        atom: MemoryAtom,
        *,
        requester_role: str,
        maximum_privacy: PrivacyClass,
    ) -> bool:
        order = {
            PrivacyClass.PUBLIC: 0,
            PrivacyClass.INTERNAL: 1,
            PrivacyClass.CONFIDENTIAL: 2,
            PrivacyClass.RESTRICTED: 3,
        }
        privacy = PrivacyClass(atom.privacy_class)
        if order[privacy] > order[maximum_privacy]:
            return False
        return "*" in atom.access_roles or requester_role in atom.access_roles

    def retrieve(
        self,
        *,
        now: str,
        subject_ids: Sequence[str] = (),
        entity_kinds: Sequence[EntityKind] = (),
        kinds: Sequence[MemoryKind] = (),
        minimum_confidence: float = 0.0,
        requester_role: str = "worker",
        maximum_privacy: PrivacyClass = PrivacyClass.INTERNAL,
        max_context_tokens: int | None = None,
    ) -> tuple[MemoryAtom, ...]:
        _parse_time(now, field_name="now")
        if not 0 <= minimum_confidence <= 1:
            raise V10ContractError("minimum_confidence must be in [0, 1]")
        if not requester_role.strip():
            raise V10ContractError("requester_role is required")
        if max_context_tokens is not None and max_context_tokens < 1:
            raise V10ContractError("max_context_tokens must be positive")
        subjects = set(subject_ids)
        entities = set(entity_kinds)
        memory_kinds = set(kinds)
        superseded = {
            edge.source_atom_id
            for edge in self._edges.values()
            if edge.kind == EdgeKind.SUPERSEDE and edge.approved
        }
        found = []
        for atom in self.atoms:
            if atom.atom_id in self._tombstones | self._quarantined | superseded:
                continue
            if atom.expired(now) or not atom.approved or atom.confidence < minimum_confidence:
                continue
            if not self._privacy_allowed(
                atom,
                requester_role=requester_role,
                maximum_privacy=maximum_privacy,
            ):
                continue
            if subjects and atom.subject_id not in subjects:
                continue
            if entities and atom.entity_kind not in entities:
                continue
            if memory_kinds and atom.kind not in memory_kinds:
                continue
            found.append(atom)
        found.sort(
            key=lambda atom: (
                -(atom.utility * atom.confidence / math.sqrt(atom.token_cost)),
                atom.token_cost,
                atom.atom_id,
            )
        )
        if max_context_tokens is None:
            return tuple(found)
        selected: list[MemoryAtom] = []
        used = 0
        for atom in found:
            if used + atom.token_cost <= max_context_tokens:
                selected.append(atom)
                used += atom.token_cost
        return tuple(selected)

    def retrieve_entities(
        self,
        entity_kinds: Sequence[EntityKind],
        *,
        now: str,
        subject_ids: Sequence[str] = (),
        **kwargs: Any,
    ) -> tuple[MemoryAtom, ...]:
        return self.retrieve(
            now=now,
            subject_ids=subject_ids,
            entity_kinds=entity_kinds,
            kinds=(MemoryKind.ENTITY,),
            **kwargs,
        )

    def retrieve_symbolic(
        self,
        *,
        now: str,
        subject_ids: Sequence[str] = (),
        **kwargs: Any,
    ) -> tuple[MemoryAtom, ...]:
        return self.retrieve(
            now=now,
            subject_ids=subject_ids,
            kinds=(MemoryKind.SYMBOLIC_RULE,),
            **kwargs,
        )

    def retrieve_receipt(self, **query: Any) -> MemoryPolicyReceipt:
        found = self.retrieve(**query)
        return MemoryPolicyReceipt(
            PolicyAction.RETRIEVE,
            PolicyVerdict.ACCEPT,
            tuple(item.atom_id for item in found),
            ("active_approved_fresh_scoped",),
        )

    def update(self, old_atom_id: str, new_atom: MemoryAtom) -> MemoryPolicyReceipt:
        old = self._atoms.get(old_atom_id)
        if old is None:
            return MemoryPolicyReceipt(
                PolicyAction.UPDATE,
                PolicyVerdict.REJECT,
                (old_atom_id, new_atom.atom_id),
                ("unknown_previous_atom",),
            )
        if new_atom.subject_id != old.subject_id or new_atom.kind != old.kind:
            return MemoryPolicyReceipt(
                PolicyAction.UPDATE,
                PolicyVerdict.REJECT,
                (old_atom_id, new_atom.atom_id),
                ("subject_or_kind_changed",),
            )
        if new_atom.version != old.version + 1:
            return MemoryPolicyReceipt(
                PolicyAction.UPDATE,
                PolicyVerdict.REJECT,
                (old_atom_id, new_atom.atom_id),
                ("non_monotonic_version",),
            )
        if (
            new_atom.source.revision == old.source.revision
            and new_atom.source.sha256 == old.source.sha256
        ):
            return MemoryPolicyReceipt(
                PolicyAction.UPDATE,
                PolicyVerdict.REJECT,
                (old_atom_id, new_atom.atom_id),
                ("source_revision_not_advanced",),
            )
        if new_atom.atom_id in self._atoms:
            return MemoryPolicyReceipt(
                PolicyAction.UPDATE,
                PolicyVerdict.REJECT,
                (old_atom_id, new_atom.atom_id),
                ("duplicate_atom_id",),
            )
        verdict, reason_codes = self._admission(new_atom)
        if verdict != PolicyVerdict.ACCEPT:
            return MemoryPolicyReceipt(
                PolicyAction.UPDATE,
                verdict,
                (old_atom_id, new_atom.atom_id),
                reason_codes,
            )
        self._snapshot()
        self._atoms[new_atom.atom_id] = new_atom
        edge = MemoryEdge(
            edge_id=f"supersede:{old_atom_id}:{new_atom.atom_id}",
            kind=EdgeKind.SUPERSEDE,
            source_atom_id=old_atom_id,
            target_atom_id=new_atom.atom_id,
            source_locator=new_atom.source.locator,
            approved=new_atom.approved,
            created_at=new_atom.created_at,
        )
        self.add_edge(edge, record_event=False)
        event_hash = self._record(
            PolicyAction.UPDATE,
            (old_atom_id, new_atom.atom_id),
            new_atom.created_at,
        )
        return MemoryPolicyReceipt(
            PolicyAction.UPDATE,
            PolicyVerdict.ACCEPT,
            (old_atom_id, new_atom.atom_id),
            ("append_only_version_and_supersede_edge",),
            event_hash,
            new_atom.atom_id,
        )

    def merge(
        self,
        atom_ids: Sequence[str],
        merged_atom: MemoryAtom,
    ) -> MemoryPolicyReceipt:
        ids = tuple(dict.fromkeys(atom_ids))
        atoms = [self._atoms.get(item) for item in ids]
        if len(ids) < 2 or any(item is None for item in atoms):
            return MemoryPolicyReceipt(
                PolicyAction.MERGE,
                PolicyVerdict.REJECT,
                ids,
                ("merge_requires_two_known_atoms",),
            )
        concrete = [item for item in atoms if item is not None]
        if any(item.atom_id in self._quarantined for item in concrete):
            return MemoryPolicyReceipt(
                PolicyAction.MERGE,
                PolicyVerdict.HUMAN_REVIEW,
                ids,
                ("conflict_must_be_resolved_not_blended",),
            )
        if len({(item.subject_id, item.kind) for item in concrete}) != 1:
            return MemoryPolicyReceipt(
                PolicyAction.MERGE,
                PolicyVerdict.REJECT,
                ids,
                ("merge_scope_mismatch",),
            )
        if merged_atom.subject_id != concrete[0].subject_id or merged_atom.kind != concrete[0].kind:
            return MemoryPolicyReceipt(
                PolicyAction.MERGE,
                PolicyVerdict.REJECT,
                ids,
                ("merged_output_scope_mismatch",),
            )
        if merged_atom.atom_id in self._atoms:
            return MemoryPolicyReceipt(
                PolicyAction.MERGE,
                PolicyVerdict.REJECT,
                ids,
                ("duplicate_atom_id",),
            )
        verdict, reason_codes = self._admission(merged_atom)
        if verdict != PolicyVerdict.ACCEPT:
            return MemoryPolicyReceipt(
                PolicyAction.MERGE,
                verdict,
                ids,
                reason_codes,
            )
        self._snapshot()
        self._atoms[merged_atom.atom_id] = merged_atom
        event_hash = self._record(
            PolicyAction.MERGE,
            ids + (merged_atom.atom_id,),
            merged_atom.created_at,
        )
        return MemoryPolicyReceipt(
            PolicyAction.MERGE,
            PolicyVerdict.ACCEPT,
            ids,
            ("compatible_scope_preserved_with_member_lineage",),
            event_hash,
            merged_atom.atom_id,
        )

    def discard(
        self,
        atom_id: str,
        *,
        occurred_at: str,
        explicit_deletion_request: bool = False,
    ) -> MemoryPolicyReceipt:
        atom = self._atoms.get(atom_id)
        if atom is None:
            return MemoryPolicyReceipt(
                PolicyAction.DISCARD,
                PolicyVerdict.REJECT,
                (atom_id,),
                ("unknown_atom",),
            )
        if atom.permanent and not explicit_deletion_request:
            return MemoryPolicyReceipt(
                PolicyAction.DISCARD,
                PolicyVerdict.HUMAN_REVIEW,
                (atom_id,),
                ("permanent_rule_requires_explicit_review",),
            )
        incoming_evidence = any(
            edge.kind == EdgeKind.EVIDENCE
            and edge.target_atom_id == atom_id
            and edge.approved
            for edge in self._edges.values()
        )
        if incoming_evidence and not explicit_deletion_request:
            return MemoryPolicyReceipt(
                PolicyAction.DISCARD,
                PolicyVerdict.HUMAN_REVIEW,
                (atom_id,),
                ("referenced_evidence_requires_review",),
            )
        self._snapshot()
        self._tombstones.add(atom_id)
        event_hash = self._record(PolicyAction.DISCARD, (atom_id,), occurred_at)
        return MemoryPolicyReceipt(
            PolicyAction.DISCARD,
            PolicyVerdict.ACCEPT,
            (atom_id,),
            ("recoverable_tombstone_written",),
            event_hash,
        )

    def summarize(
        self,
        atom_ids: Sequence[str],
        summary_atom: MemoryAtom,
    ) -> MemoryPolicyReceipt:
        ids = tuple(dict.fromkeys(atom_ids))
        members = [self._atoms.get(item) for item in ids]
        if len(ids) < 2 or any(item is None for item in members):
            return MemoryPolicyReceipt(
                PolicyAction.SUMMARIZE,
                PolicyVerdict.REJECT,
                ids,
                ("summary_requires_two_known_members",),
            )
        if summary_atom.kind != MemoryKind.SEMANTIC:
            return MemoryPolicyReceipt(
                PolicyAction.SUMMARIZE,
                PolicyVerdict.REJECT,
                ids,
                ("summary_output_must_be_semantic",),
            )
        expected = sorted(item.content_sha256 for item in members if item is not None)
        if sorted(summary_atom.payload.get("member_sha256", ())) != expected:
            return MemoryPolicyReceipt(
                PolicyAction.SUMMARIZE,
                PolicyVerdict.REJECT,
                ids,
                ("summary_member_lineage_mismatch",),
            )
        if summary_atom.atom_id in self._atoms:
            return MemoryPolicyReceipt(
                PolicyAction.SUMMARIZE,
                PolicyVerdict.REJECT,
                ids,
                ("duplicate_atom_id",),
            )
        verdict, reason_codes = self._admission(summary_atom)
        if verdict != PolicyVerdict.ACCEPT:
            return MemoryPolicyReceipt(
                PolicyAction.SUMMARIZE,
                verdict,
                ids,
                reason_codes,
            )
        self._snapshot()
        self._atoms[summary_atom.atom_id] = summary_atom
        event_hash = self._record(
            PolicyAction.SUMMARIZE,
            ids + (summary_atom.atom_id,),
            summary_atom.created_at,
        )
        return MemoryPolicyReceipt(
            PolicyAction.SUMMARIZE,
            PolicyVerdict.ACCEPT,
            ids,
            ("visible_summary_with_content_addressed_members",),
            event_hash,
            summary_atom.atom_id,
        )

    def what_to_remember(self, atom: MemoryAtom) -> MemoryPolicyReceipt:
        if not atom.source.storage_allowed:
            verdict, codes = PolicyVerdict.REJECT, ("source_rights_block_storage",)
        elif atom.kind == MemoryKind.SYMBOLIC_RULE and not atom.approved:
            verdict, codes = PolicyVerdict.HUMAN_REVIEW, ("rule_requires_approval",)
        elif atom.confidence < 0.7:
            verdict, codes = PolicyVerdict.REJECT, ("confidence_below_memory_floor",)
        elif atom.utility < 0.6 and atom.kind == MemoryKind.EPISODIC:
            verdict, codes = PolicyVerdict.REJECT, ("transient_low_utility_episode",)
        else:
            verdict, codes = PolicyVerdict.ACCEPT, ("future_value_and_evidence_pass",)
        return MemoryPolicyReceipt(PolicyAction.REMEMBER, verdict, (atom.atom_id,), codes)

    def when_to_forget(
        self,
        atom_id: str,
        *,
        now: str,
        explicit_deletion_request: bool = False,
    ) -> MemoryPolicyReceipt:
        atom = self._atoms.get(atom_id)
        if atom is None:
            return MemoryPolicyReceipt(
                PolicyAction.FORGET,
                PolicyVerdict.REJECT,
                (atom_id,),
                ("unknown_atom",),
            )
        superseded = any(
            edge.kind == EdgeKind.SUPERSEDE
            and edge.source_atom_id == atom_id
            and edge.approved
            for edge in self._edges.values()
        )
        if atom.permanent and not explicit_deletion_request:
            verdict, codes = PolicyVerdict.HUMAN_REVIEW, ("permanent_rule_retained",)
        elif explicit_deletion_request:
            verdict, codes = PolicyVerdict.ACCEPT, ("explicit_deletion_request",)
        elif atom.expired(now):
            verdict, codes = PolicyVerdict.ACCEPT, ("validity_interval_expired",)
        elif superseded and atom.utility < 0.5:
            verdict, codes = PolicyVerdict.ACCEPT, ("superseded_low_utility",)
        else:
            verdict, codes = PolicyVerdict.REJECT, ("retention_value_remains",)
        return MemoryPolicyReceipt(PolicyAction.FORGET, verdict, (atom_id,), codes)

    def rollback_last(self) -> str:
        if not self._events or not self._snapshots:
            raise V10ContractError("no memory mutation is available to roll back")
        atoms, edges, tombstones, quarantined = self._snapshots.pop()
        self._atoms = atoms
        self._edges = edges
        self._tombstones = tombstones
        self._quarantined = quarantined
        removed = self._events.pop()
        self._event_states.pop(removed.event_hash, None)
        return self._state_sha256()

    def rollback_to_event(self, event_hash: str | None) -> str:
        if event_hash is None:
            if not self._events:
                return self._state_sha256()
            while self._events:
                self.rollback_last()
            return self._state_sha256()
        if event_hash not in self._event_states:
            raise V10ContractError("rollback target event is unknown")
        target_index = next(
            index
            for index, event in enumerate(self._events)
            if event.event_hash == event_hash
        )
        atoms, edges, tombstones, quarantined = self._event_states[event_hash]
        self._atoms = copy.deepcopy(atoms)
        self._edges = copy.deepcopy(edges)
        self._tombstones = set(tombstones)
        self._quarantined = set(quarantined)
        removed_events = self._events[target_index + 1 :]
        self._events = self._events[: target_index + 1]
        for event in removed_events:
            self._event_states.pop(event.event_hash, None)
        self._snapshots = self._snapshots[: target_index + 1]
        return self._state_sha256()

    def verify_event_chain(self) -> bool:
        previous = "0" * 64
        for event in self._events:
            if event.previous_hash != previous:
                return False
            payload = {
                "sequence": event.sequence,
                "action": event.action.value,
                "atom_ids": event.atom_ids,
                "previous_hash": event.previous_hash,
                "state_sha256": event.state_sha256,
                "occurred_at": event.occurred_at,
            }
            if stable_digest(payload) != event.event_hash:
                return False
            previous = event.event_hash
        return True


def build_policy_supervision_corpus() -> tuple[dict[str, Any], ...]:
    """Creates balanced, project-owned policy labels; it does not train a model."""

    rows: list[dict[str, Any]] = []
    reason_by_action = {
        PolicyAction.STORE: ("source_bound_and_admitted", "source_rights_block_storage"),
        PolicyAction.RETRIEVE: ("active_approved_fresh_scoped", "expired_or_quarantined"),
        PolicyAction.UPDATE: ("append_only_version_and_supersede_edge", "non_monotonic_version"),
        PolicyAction.MERGE: ("compatible_scope_preserved_with_member_lineage", "conflict_must_be_resolved_not_blended"),
        PolicyAction.DISCARD: ("recoverable_tombstone_written", "referenced_evidence_requires_review"),
        PolicyAction.SUMMARIZE: ("visible_summary_with_content_addressed_members", "summary_member_lineage_mismatch"),
        PolicyAction.REMEMBER: ("future_value_and_evidence_pass", "transient_low_utility_episode"),
        PolicyAction.FORGET: ("validity_interval_expired", "retention_value_remains"),
    }
    for action in PolicyAction:
        accept_reason, reject_reason = reason_by_action[action]
        for verdict, reason in (
            (PolicyVerdict.ACCEPT, accept_reason),
            (PolicyVerdict.REJECT, reject_reason),
        ):
            payload = {
                "schema": "ProofLaunchMemoryPolicySupervisionV1",
                "example_id": f"memory-policy:{action.value}:{verdict.value}",
                "input": {
                    "action": action.value,
                    "deployment_visible_state": f"fixture:{action.value}:{verdict.value}",
                    "hidden_reasoning_present": False,
                },
                "target": {
                    "verdict": verdict.value,
                    "reason_codes": [reason],
                },
                "rights_profile": "project_owned_synthetic",
                "training_allowed": True,
                "model_training_observed": False,
            }
            payload["content_sha256"] = stable_digest(payload)
            rows.append(payload)
    return tuple(rows)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
