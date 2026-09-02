"""Tests for CLAUDE_APPROVAL_REPLAY_AND_STALENESS_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ars = importlib.import_module("repair.approval_replay_and_staleness")
ars_rec = importlib.import_module("repair.approval_replay_and_staleness_record")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / ("CLAUDE_APPROVAL_REPLAY_AND_STALENESS_LOCK_001.json")
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / ("claude_approval_replay_and_staleness")
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


WS_HASH = "a" * 64
BODY_HASH = "b" * 64
V_REF = "PATCH_VERIFIER_PASSED_TEMP_ONLY"
SNAP_REF = "snap-1"


def _packet(**overrides):
    base = dict(
        approval_id="nonce-1",
        timestamp_epoch_s=1_700_000_000,
        trace_id="t-1",
        workspace_identity_hash=WS_HASH,
        canonical_patch_body_hash=BODY_HASH,
        verifier_ref=V_REF,
        rollback_snapshot_ref=SNAP_REF,
    )
    base.update(overrides)
    return ars_rec.ApprovalPacket(**base)


def _verifier(now=1_700_000_010, max_age=60):
    return ars.ApprovalReplayAndStalenessVerifier(
        max_age_seconds=max_age,
        now_fn=lambda: now,
    )


def _verify(v, packet=None, **expected_overrides):
    expected = dict(
        expected_workspace_identity_hash=WS_HASH,
        expected_canonical_patch_body_hash=BODY_HASH,
        expected_verifier_ref=V_REF,
        expected_rollback_snapshot_ref=SNAP_REF,
    )
    expected.update(expected_overrides)
    return v.verify(packet=packet, **expected)


# ---------------------------------------------------------------------------
# Status tokens
# ---------------------------------------------------------------------------
def test_status_tokens_exact():
    assert set(ars_rec.APPROVAL_REPLAY_AND_STALENESS_STATUS_TOKENS) == {
        "APPROVAL_REPLAY_STALENESS_PASSED",
        "APPROVAL_REPLAY_BLOCKED_REUSED_NONCE",
        "APPROVAL_REPLAY_BLOCKED_STALE_APPROVAL",
        "APPROVAL_REPLAY_BLOCKED_WORKSPACE_MISMATCH",
        "APPROVAL_REPLAY_BLOCKED_PATCH_BODY_MISMATCH",
        "APPROVAL_REPLAY_BLOCKED_VERIFIER_REF_MISMATCH",
        "APPROVAL_REPLAY_BLOCKED_SNAPSHOT_REF_MISMATCH",
        "APPROVAL_REPLAY_BLOCKED_MALFORMED_PACKET",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_fresh_packet_passes():
    v = _verifier()
    rec = _verify(v, _packet())
    assert rec.is_passed, rec.notes
    assert rec.source_mutation_authorized is False
    assert rec.training_eligible is False
    assert rec.age_seconds == 10
    assert rec.max_age_seconds == 60


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def test_same_approval_id_replayed_blocks():
    v = _verifier()
    first = _verify(v, _packet(approval_id="nonce-A"))
    assert first.is_passed
    # Same packet a second time on the same verifier — replay.
    second = _verify(v, _packet(approval_id="nonce-A"))
    assert second.decision == "APPROVAL_REPLAY_BLOCKED_REUSED_NONCE"
    assert second.is_blocked


def test_distinct_nonces_both_pass():
    v = _verifier()
    a = _verify(v, _packet(approval_id="nonce-A"))
    b = _verify(v, _packet(approval_id="nonce-B"))
    assert a.is_passed
    assert b.is_passed


def test_replay_on_different_patch_still_blocks():
    """A previously-valid approval cannot be replayed even if the
    caller swaps in a different patch body — the nonce ledger
    catches it before the bind checks even run."""
    v = _verifier()
    a = _verify(v, _packet(approval_id="nonce-A"))
    assert a.is_passed
    b = _verify(
        v,
        _packet(approval_id="nonce-A", canonical_patch_body_hash="c" * 64),
        expected_canonical_patch_body_hash="c" * 64,
    )
    assert b.decision == "APPROVAL_REPLAY_BLOCKED_REUSED_NONCE"


def test_commit_on_pass_false_does_not_record_nonce():
    v = _verifier()
    first = _verify(
        v,
        _packet(approval_id="nonce-PROBE"),
    )
    assert first.is_passed
    # The nonce IS recorded on default behaviour. Now verify
    # opt-out works: a probe with commit_on_pass=False on a fresh
    # nonce should NOT mark it consumed.
    res = v.verify(
        packet=_packet(approval_id="nonce-PROBE-2"),
        expected_workspace_identity_hash=WS_HASH,
        expected_canonical_patch_body_hash=BODY_HASH,
        expected_verifier_ref=V_REF,
        expected_rollback_snapshot_ref=SNAP_REF,
        commit_on_pass=False,
    )
    assert res.is_passed
    # The same nonce can now be replayed because we didn't commit.
    res2 = _verify(v, _packet(approval_id="nonce-PROBE-2"))
    assert res2.is_passed


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------
def test_packet_exactly_at_max_age_passes():
    v = _verifier(now=1_700_000_000 + 60, max_age=60)
    rec = _verify(v, _packet())
    assert rec.is_passed


def test_packet_over_max_age_blocks():
    v = _verifier(now=1_700_000_000 + 61, max_age=60)
    rec = _verify(v, _packet())
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_STALE_APPROVAL"


def test_future_timestamp_is_age_zero_and_passes():
    """A packet timestamped slightly in the future (clock skew)
    is treated as age=0, not stale."""
    v = _verifier(now=1_700_000_000, max_age=60)
    rec = _verify(v, _packet(timestamp_epoch_s=1_700_000_005))
    assert rec.is_passed
    assert rec.age_seconds == 0


# ---------------------------------------------------------------------------
# Mismatches
# ---------------------------------------------------------------------------
def test_workspace_mismatch_blocks():
    v = _verifier()
    rec = _verify(v, _packet(workspace_identity_hash="z" * 64))
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_WORKSPACE_MISMATCH"


def test_patch_body_mismatch_blocks():
    v = _verifier()
    rec = _verify(v, _packet(canonical_patch_body_hash="z" * 64))
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_PATCH_BODY_MISMATCH"


def test_verifier_ref_mismatch_blocks():
    v = _verifier()
    rec = _verify(v, _packet(verifier_ref="WRONG"))
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_VERIFIER_REF_MISMATCH"


def test_snapshot_ref_mismatch_blocks():
    v = _verifier()
    rec = _verify(v, _packet(rollback_snapshot_ref="other-snap"))
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_SNAPSHOT_REF_MISMATCH"


# ---------------------------------------------------------------------------
# Malformed
# ---------------------------------------------------------------------------
def test_none_packet_blocks():
    v = _verifier()
    rec = _verify(v, None)
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_MALFORMED_PACKET"


def test_empty_approval_id_blocks():
    v = _verifier()
    rec = _verify(v, _packet(approval_id=""))
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_MALFORMED_PACKET"


def test_nul_in_approval_id_blocks():
    v = _verifier()
    rec = _verify(v, _packet(approval_id="nonce\x00bad"))
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_MALFORMED_PACKET"


def test_negative_timestamp_blocks():
    v = _verifier()
    rec = _verify(v, _packet(timestamp_epoch_s=-1))
    assert rec.decision == "APPROVAL_REPLAY_BLOCKED_MALFORMED_PACKET"


# ---------------------------------------------------------------------------
# Aggregate attack scenario
# ---------------------------------------------------------------------------
def test_full_replay_attack_scenario_blocked():
    """A previously valid approval is captured by an attacker and
    replayed against:
      - the same workspace later in time
      - a different workspace
      - a different patch body in the same workspace
    All three replays must fail."""
    v = _verifier(now=1_700_000_010, max_age=60)
    initial = _verify(v, _packet(approval_id="captured"))
    assert initial.is_passed

    # Same nonce, later in time.
    v2 = ars.ApprovalReplayAndStalenessVerifier(
        ledger=v.ledger,
        max_age_seconds=60,
        now_fn=lambda: 1_700_000_020,
    )
    r1 = _verify(v2, _packet(approval_id="captured"))
    assert r1.decision == "APPROVAL_REPLAY_BLOCKED_REUSED_NONCE"

    # Same nonce, different workspace.
    r2 = _verify(
        v2,
        _packet(approval_id="captured", workspace_identity_hash="z" * 64),
        expected_workspace_identity_hash="z" * 64,
    )
    assert r2.decision == "APPROVAL_REPLAY_BLOCKED_REUSED_NONCE"

    # Same nonce, different patch body.
    r3 = _verify(
        v2,
        _packet(approval_id="captured", canonical_patch_body_hash="c" * 64),
        expected_canonical_patch_body_hash="c" * 64,
    )
    assert r3.decision == "APPROVAL_REPLAY_BLOCKED_REUSED_NONCE"


# ---------------------------------------------------------------------------
# In-memory ledger surface
# ---------------------------------------------------------------------------
def test_in_memory_ledger_records_consumed_nonces():
    ledger = ars.InMemoryNonceLedger()
    assert "nonce-A" not in ledger
    ledger.add("nonce-A")
    assert "nonce-A" in ledger
    assert len(ledger) == 1


def test_default_max_age_one_day():
    assert ars.DEFAULT_MAX_AGE_SECONDS == 24 * 60 * 60


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "CLAUDE_APPROVAL_REPLAY_AND_STALENESS_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "CLAUDE_APPROVAL_REPLAY_AND_STALENESS_LOCK_001" in ids
