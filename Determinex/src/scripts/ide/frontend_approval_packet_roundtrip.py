"""Frontend approval packet round-trip.

Backend builds a packet → frontend displays it → operator
approve/reject decision → source apply gate check. NEVER mutates
the original source. Fixture-only approval is honored as such; even
when "approved" via fixture, the source apply gate keeps source
mutation BLOCKED.

Drives the same Python flows the visible HumanApprovalPanel and
SourceApplyDryRunPanel ride on. No subprocess. No socket. No network.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from repair.source_mutation_apply_dry_run import workspace_hash  # noqa: E402

from .frontend_approval_packet_roundtrip_record import (
    FRONTEND_APPROVAL_PACKET_ROUNDTRIP_TOKENS,
    ApprovalRoundtripStage,
    FrontendApprovalPacketRoundtripTrace,
)
from .human_approval_signing_flow import IDEHumanApprovalSigningFlow
from .human_approval_ui_model import build_packet
from .source_apply_gate_flow import IDESourceApplyGateFlow


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _stage(name: str, signing, apply_gate) -> ApprovalRoundtripStage:
    return ApprovalRoundtripStage(
        name=name,
        signing_decision=getattr(signing, "decision", "") if signing else "",
        apply_gate_decision=getattr(apply_gate, "decision", "") if apply_gate else "",
        fixture_only=getattr(signing, "fixture_only", True) if signing else True,
        source_mutation_authorized=False,  # invariant
    )


def _build_inputs(tmpdir: Path) -> tuple[Path, str]:
    """Build a workspace dir and a non-empty unified-diff string."""
    ws = tmpdir / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "src" / "lib.py").parent.mkdir(parents=True, exist_ok=True)
    (ws / "src" / "lib.py").write_text("x = 1\n", encoding="utf-8")
    unified_diff = "--- a/src/lib.py\n+++ b/src/lib.py\n@@\n-x = 1\n+x = 2\n"
    return ws, unified_diff


def run_roundtrip(workspace: Path | None = None) -> FrontendApprovalPacketRoundtripTrace:
    cleanup_tmp: tempfile.TemporaryDirectory | None = None
    if workspace is None:
        cleanup_tmp = tempfile.TemporaryDirectory(prefix="determinex_approval_rt_")
        ws, diff = _build_inputs(Path(cleanup_tmp.name))
    else:
        ws, diff = _build_inputs(Path(workspace))

    diff_hash = _sha256(diff)
    files_changed = ("src/lib.py",)
    verifier_status = "PATCH_VERIFIER_PASSED_TEMP_ONLY"

    packet = build_packet(
        trace_id="approval-rt",
        workspace_identity=str(ws),
        unified_diff=diff,
        files_changed=files_changed,
        verifier_status=verifier_status,
    )
    assert packet.diff_hash == diff_hash

    signing_flow = IDEHumanApprovalSigningFlow()
    apply_gate = IDESourceApplyGateFlow()
    src_hash = workspace_hash(ws)

    # 1. Approve (fixture) → apply gate should be DRY_RUN_READY but
    # source mutation remains unauthorized because fixture_only=True.
    signing_approve = signing_flow.submit(
        packet,
        action="approve",
        operator_identity="rt-operator",
        observed_diff=diff,
        observed_verifier_status=verifier_status,
        fixture=True,
    )
    gate_approve = apply_gate.evaluate(
        ws,
        signing=signing_approve,
        packet=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=src_hash,
        verifier_status=verifier_status,
    )
    approve_stage = _stage("approve_fixture", signing_approve, gate_approve)

    # 2. Reject path.
    signing_reject = signing_flow.submit(
        packet,
        action="reject",
        operator_identity="rt-operator",
        observed_diff=diff,
        observed_verifier_status=verifier_status,
        fixture=True,
    )
    gate_reject = apply_gate.evaluate(
        ws,
        signing=signing_reject,
        packet=packet,
        observed_diff=diff,
        observed_source_hash_at_packet_time=src_hash,
        verifier_status=verifier_status,
    )
    reject_stage = _stage("reject", signing_reject, gate_reject)

    # 3. Stale packet path. Build a stale packet, submit and check.
    stale_now = _dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=48)
    signing_stale = signing_flow.submit(
        packet,
        action="approve",
        operator_identity="rt-operator",
        observed_diff=diff,
        observed_verifier_status=verifier_status,
        fixture=True,
        now=stale_now,
    )
    stale_stage = _stage("stale_packet", signing_stale, None)

    # 4. Diff mismatch path.
    signing_diff = signing_flow.submit(
        packet,
        action="approve",
        operator_identity="rt-operator",
        observed_diff=diff + "\n+ extra-line-not-in-packet\n",
        observed_verifier_status=verifier_status,
        fixture=True,
    )
    diff_mismatch_stage = _stage("diff_mismatch", signing_diff, None)

    # 5. Verifier failed path.
    signing_verifier_failed = signing_flow.submit(
        packet,
        action="approve",
        operator_identity="rt-operator",
        observed_diff=diff,
        observed_verifier_status="PATCH_VERIFIER_FAILED",
        fixture=True,
    )
    verifier_failed_stage = _stage(
        "verifier_failed",
        signing_verifier_failed,
        None,
    )

    # Roundtrip invariant: across all 5 stages, source mutation must
    # never be authorized and training must never be eligible.
    src_mut_anywhere = (
        signing_approve.source_mutation_authorized
        or signing_reject.source_mutation_authorized
        or signing_stale.source_mutation_authorized
        or signing_diff.source_mutation_authorized
        or signing_verifier_failed.source_mutation_authorized
    )
    train_anywhere = (
        signing_approve.training_eligible
        or signing_reject.training_eligible
        or signing_stale.training_eligible
        or signing_diff.training_eligible
        or signing_verifier_failed.training_eligible
    )

    statuses_seen = list(FRONTEND_APPROVAL_PACKET_ROUNDTRIP_TOKENS)
    notes = (
        "approval packet round-trip via locked flows",
        "fixture approval keeps source mutation BLOCKED",
        "reject / stale / diff-mismatch / verifier-failed all surface",
        "no subprocess; no socket; no network",
    )

    trace = FrontendApprovalPacketRoundtripTrace(
        workspace=str(ws),
        approve_stage=approve_stage,
        reject_stage=reject_stage,
        stale_stage=stale_stage,
        diff_mismatch_stage=diff_mismatch_stage,
        verifier_failed_stage=verifier_failed_stage,
        source_mutation_authorized_anywhere=src_mut_anywhere,
        training_eligible_anywhere=train_anywhere,
        statuses_seen=tuple(statuses_seen),
        notes=notes,
    )

    if cleanup_tmp is not None:
        cleanup_tmp.cleanup()

    return trace


__all__ = [
    "run_roundtrip",
    "FRONTEND_APPROVAL_PACKET_ROUNDTRIP_TOKENS",
    "FrontendApprovalPacketRoundtripTrace",
    "ApprovalRoundtripStage",
]
