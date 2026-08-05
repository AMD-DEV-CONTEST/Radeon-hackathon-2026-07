"""Approval replay and staleness verifier.

CLAUDE_APPROVAL_REPLAY_AND_STALENESS_LOCK_001 — rung 3 of the IDE
authority and claims hygiene campaign.

The verifier holds an in-memory ledger of previously-consumed
approval_ids (the nonce). Each new packet must:

  * be well-formed
  * use a fresh approval_id (no replay)
  * be within the policy freshness window
  * be bound to the expected workspace, patch body, verifier ref,
    and rollback snapshot ref

The ledger is an in-memory dict by default; a production caller
may pass a persistent ledger if it implements the same
``__contains__``/``add`` shape. We keep the ledger inside the
verifier instance so two independent verifier objects do not share
state by accident.

This module DOES NOT mutate any approval packet. It DOES NOT
emit a packet. It DOES NOT touch the network or the workspace.
"""

from __future__ import annotations

import time
from typing import Protocol

from .approval_replay_and_staleness_record import (
    APPROVAL_REPLAY_AND_STALENESS_STATUS_TOKENS,
    ApprovalPacket,
    ApprovalReplayAndStalenessRecord,
)

# Default policy: 24 hour freshness window.
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


class NonceLedger(Protocol):
    def __contains__(self, key: str) -> bool: ...
    def add(self, key: str) -> None: ...


class InMemoryNonceLedger:
    """Simple set-backed ledger. Not persistent."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def __contains__(self, key: str) -> bool:
        return key in self._seen

    def add(self, key: str) -> None:
        self._seen.add(key)

    def __len__(self) -> int:
        return len(self._seen)


class ApprovalReplayAndStalenessVerifier:
    def __init__(
        self,
        *,
        ledger: NonceLedger | None = None,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
        now_fn=time.time,
    ) -> None:
        self._ledger: NonceLedger = ledger if ledger is not None else InMemoryNonceLedger()
        self._max_age_seconds = int(max_age_seconds)
        self._now_fn = now_fn

    @property
    def ledger(self) -> NonceLedger:
        return self._ledger

    @property
    def max_age_seconds(self) -> int:
        return self._max_age_seconds

    def verify(
        self,
        *,
        packet: ApprovalPacket | None,
        expected_workspace_identity_hash: str,
        expected_canonical_patch_body_hash: str,
        expected_verifier_ref: str,
        expected_rollback_snapshot_ref: str,
        commit_on_pass: bool = True,
    ) -> ApprovalReplayAndStalenessRecord:
        if packet is None or not packet.is_well_formed:
            return self._block(
                "APPROVAL_REPLAY_BLOCKED_MALFORMED_PACKET",
                packet=packet,
                age=0,
                note="packet is missing or not well-formed",
            )

        now = int(self._now_fn())
        age = max(0, now - int(packet.timestamp_epoch_s))

        if packet.approval_id in self._ledger:
            return self._block(
                "APPROVAL_REPLAY_BLOCKED_REUSED_NONCE",
                packet=packet,
                age=age,
                note=(
                    f"approval_id={packet.approval_id!r} has already "
                    "been consumed by this verifier; replay refused"
                ),
            )

        if age > self._max_age_seconds:
            return self._block(
                "APPROVAL_REPLAY_BLOCKED_STALE_APPROVAL",
                packet=packet,
                age=age,
                note=(
                    f"packet age={age}s > max_age={self._max_age_seconds}s; "
                    "approval is stale and cannot be honored"
                ),
            )

        if packet.workspace_identity_hash != expected_workspace_identity_hash:
            return self._block(
                "APPROVAL_REPLAY_BLOCKED_WORKSPACE_MISMATCH",
                packet=packet,
                age=age,
                note=("packet.workspace_identity_hash does not match expected"),
            )

        if packet.canonical_patch_body_hash != expected_canonical_patch_body_hash:
            return self._block(
                "APPROVAL_REPLAY_BLOCKED_PATCH_BODY_MISMATCH",
                packet=packet,
                age=age,
                note=("packet.canonical_patch_body_hash does not match expected"),
            )

        if packet.verifier_ref != expected_verifier_ref:
            return self._block(
                "APPROVAL_REPLAY_BLOCKED_VERIFIER_REF_MISMATCH",
                packet=packet,
                age=age,
                note="packet.verifier_ref does not match expected",
            )

        if packet.rollback_snapshot_ref != expected_rollback_snapshot_ref:
            return self._block(
                "APPROVAL_REPLAY_BLOCKED_SNAPSHOT_REF_MISMATCH",
                packet=packet,
                age=age,
                note="packet.rollback_snapshot_ref does not match expected",
            )

        # All checks passed — commit the nonce (atomic-with-decision).
        if commit_on_pass:
            self._ledger.add(packet.approval_id)

        return ApprovalReplayAndStalenessRecord(
            decision="APPROVAL_REPLAY_STALENESS_PASSED",
            approval_id=packet.approval_id,
            workspace_identity_hash=packet.workspace_identity_hash,
            canonical_patch_body_hash=packet.canonical_patch_body_hash,
            verifier_ref=packet.verifier_ref,
            rollback_snapshot_ref=packet.rollback_snapshot_ref,
            age_seconds=age,
            max_age_seconds=self._max_age_seconds,
            source_mutation_authorized=False,
            training_eligible=False,
            notes=(
                "approval packet fresh, non-replayed, bound to expected refs",
                "approval_id added to verifier ledger; subsequent use refused",
                "does not authorize source mutation; apply gate decides",
            ),
        )

    def _block(
        self,
        decision: str,
        *,
        packet: ApprovalPacket | None,
        age: int,
        note: str,
    ) -> ApprovalReplayAndStalenessRecord:
        return ApprovalReplayAndStalenessRecord(
            decision=decision,
            approval_id=getattr(packet, "approval_id", "") if packet else "",
            workspace_identity_hash=getattr(packet, "workspace_identity_hash", "")
            if packet
            else "",
            canonical_patch_body_hash=getattr(packet, "canonical_patch_body_hash", "")
            if packet
            else "",
            verifier_ref=getattr(packet, "verifier_ref", "") if packet else "",
            rollback_snapshot_ref=getattr(packet, "rollback_snapshot_ref", "") if packet else "",
            age_seconds=age,
            max_age_seconds=self._max_age_seconds,
            source_mutation_authorized=False,
            training_eligible=False,
            notes=(note,),
        )


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "InMemoryNonceLedger",
    "NonceLedger",
    "ApprovalReplayAndStalenessVerifier",
    "APPROVAL_REPLAY_AND_STALENESS_STATUS_TOKENS",
    "ApprovalPacket",
    "ApprovalReplayAndStalenessRecord",
]
