"""Real approval-gated apply + post-verify trace.

End-to-end orchestrator that composes the existing locked modules:

  - source_mutation_rollback_snapshot.take_snapshot
  - source_mutation_apply_after_approval.apply_after_approval
  - post_apply_verifier.run (with build-adapter callable)
  - source_mutation_rollback_execution.execute_rollback (on fail)

Refuses to act unless:
  - real human approval is ACCEPTED (signature_kind == real_local_signed)
  - upstream temp verify passed
  - verifier selection available
  - trace_id, diff_hash, verifier_ref binding match
  - explicit human-approval object supplied (else REAL_APPROVAL_REQUIRED)

Training eligibility remains False on every record — promotion to
True is gated by a separate (future) global training guard.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Sequence
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide.real_human_approval_admission_record import (  # noqa: E402
    RealHumanApprovalAdmissionRecord,
)

from .build_adapter_backed_verifier_selection_record import (
    BuildAdapterBackedVerifierSelectionRecord,
)
from .post_apply_verifier import run as _post_run  # noqa: E402
from .real_approval_apply_post_verify_trace_record import (
    REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_STATUS_TOKENS,
    RealApprovalApplyPostVerifyTraceRecord,
)
from .real_patch_plan_quarantine_record import (
    RealPatchPlanQuarantineRecord,
    RealQuarantinedPatchEntry,
)
from .real_temp_patch_verify_record import (
    RealTempPatchVerifyRecord,
)
from .safe_patch_workspace import VerifierResult  # noqa: E402
from .source_mutation_apply_after_approval import (  # noqa: E402
    apply_after_approval as _apply_after_approval,
)
from .source_mutation_rollback_execution import (  # noqa: E402
    execute_rollback as _execute_rollback,
)
from .source_mutation_rollback_snapshot import (  # noqa: E402
    take_snapshot as _take_snapshot,
)

_OUTPUT_CAP = 2048
_PYTEST_COMMANDS = frozenset({"pytest", "pytest.exe"})


def _portable_hardened_runner_argv(verifier_argv: Sequence[str]) -> list[str]:
    argv = list(verifier_argv)
    if argv and Path(argv[0]).name.lower() in _PYTEST_COMMANDS:
        return [sys.executable, "-m", "pytest", *argv[1:]]
    return argv


def _build_post_apply_verifier_callable(
    verifier_argv: Sequence[str],
    *,
    timeout_seconds: int,
):
    """Closure that runs verifier_argv on the *workspace* through the
    hardened runner. Returns a function compatible with
    post_apply_verifier.run's verifier= parameter."""
    try:
        hr = importlib.import_module("intake.hardened_runner")
    except ImportError:
        hr = None

    def verifier(workspace: Path) -> VerifierResult:
        if hr is None:
            return VerifierResult(passed=False, output="HARDENED_RUNNER_UNAVAILABLE")
        res = hr.run(
            _portable_hardened_runner_argv(verifier_argv),
            workspace=Path(workspace),
            timeout=timeout_seconds,
        )
        if getattr(res, "blocked", False):
            return VerifierResult(
                passed=False,
                output=f"HARDENED_RUNNER_BLOCKED: {getattr(res, 'reason', '')}"[:_OUTPUT_CAP],
            )
        if getattr(res, "timed_out", False):
            return VerifierResult(
                passed=False,
                output=f"VERIFIER_TIMED_OUT after {timeout_seconds}s"[:_OUTPUT_CAP],
            )
        passed = bool(getattr(res, "success", False))
        out = (getattr(res, "stdout", "") or "") + (
            "\n--- stderr ---\n" + (getattr(res, "stderr", "") or "")
            if getattr(res, "stderr", "")
            else ""
        )
        return VerifierResult(passed=passed, output=out[:_OUTPUT_CAP])

    return verifier


def _synthesize_quarantine_plan(
    plan_entries: Sequence[dict],
    *,
    workspace: str,
    model_id: str,
    provider: str,
) -> RealPatchPlanQuarantineRecord:
    """Convert raw plan_entries into the quarantine record shape that
    source_mutation_apply_after_approval expects."""
    accepted: list[RealQuarantinedPatchEntry] = []
    for e in plan_entries:
        if not isinstance(e, dict):
            continue
        op = str(e.get("operation") or "")
        path = str(e.get("path") or "").replace("\\", "/").strip("/")
        body = e.get("new_content")
        if op == "replace_file" and path and isinstance(body, str):
            accepted.append(
                RealQuarantinedPatchEntry(
                    operation=op,
                    path=path,
                    new_content_chars=len(body),
                )
            )
    return RealPatchPlanQuarantineRecord(
        decision="REAL_PATCH_PLAN_QUARANTINED"
        if accepted
        else "REAL_PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
        workspace=workspace,
        model_id=model_id,
        provider=provider,
        accepted=tuple(accepted),
        rejected=tuple(),
        quarantined=bool(accepted),
        output_trusted=False,
        patch_applied=False,
        source_mutation_authorized=False,
        training_eligible=False,
    )


def trace(
    *,
    workspace: Path,
    snapshot_root: Path,
    snapshot_id: str,
    approval: RealHumanApprovalAdmissionRecord | None,
    temp_verify: RealTempPatchVerifyRecord | None,
    verifier_selection: BuildAdapterBackedVerifierSelectionRecord | None,
    plan_entries: Sequence[dict],
    observed_diff: str,
    verifier_timeout_seconds: int = 120,
    model_id: str = "determinex-engineer-v11-dsl",
    provider: str = "ollama",
) -> RealApprovalApplyPostVerifyTraceRecord:
    ws = Path(workspace).resolve()

    if temp_verify is None or not temp_verify.is_passed:
        return _blocked(
            "REAL_APPROVAL_APPLY_BLOCKED_NO_TEMP_VERIFY",
            ws=str(ws),
            approval_decision=getattr(approval, "decision", "") if approval else "",
            temp_verify_decision=getattr(temp_verify, "decision", "") if temp_verify else "",
            note="temp_verify missing or did not pass",
        )

    if verifier_selection is None or not verifier_selection.is_selected:
        return _blocked(
            "REAL_APPROVAL_APPLY_BLOCKED_NO_VERIFIER",
            ws=str(ws),
            approval_decision=getattr(approval, "decision", "") if approval else "",
            temp_verify_decision=temp_verify.decision,
            note="verifier selection missing or blocked",
        )

    # No approval supplied → REAL_APPROVAL_REQUIRED.
    if approval is None:
        return RealApprovalApplyPostVerifyTraceRecord(
            decision="REAL_APPROVAL_REQUIRED",
            workspace_identity=str(ws),
            approval_decision="",
            temp_verify_decision=temp_verify.decision,
            rollback_snapshot_decision="",
            apply_decision="",
            post_apply_decision="",
            rollback_execution_decision="",
            source_mutation_applied=False,
            rollback_executed=False,
            training_eligible=False,
            statuses_seen=("REAL_APPROVAL_REQUIRED",),
            notes=(
                "no approval supplied — explicit operator action required",
                "source not mutated",
            ),
        )

    if not approval.is_accepted:
        return _blocked(
            "REAL_APPROVAL_APPLY_BLOCKED_NO_APPROVAL",
            ws=str(ws),
            approval_decision=approval.decision,
            temp_verify_decision=temp_verify.decision,
            note="approval is not ACCEPTED",
        )

    if approval.is_fixture or approval.signature_kind not in {
        "real_local_signed",
        "real_local_hmac",
    }:
        return _blocked(
            "REAL_APPROVAL_APPLY_BLOCKED_NO_APPROVAL",
            ws=str(ws),
            approval_decision=approval.decision,
            temp_verify_decision=temp_verify.decision,
            note=("approval is fixture or signature_kind not in production set"),
        )

    # Trace + diff + verifier-status binding sanity.
    if approval.verifier_status != temp_verify.verifier_status:
        return _blocked(
            "REAL_APPROVAL_APPLY_BLOCKED_MISMATCH",
            ws=str(ws),
            approval_decision=approval.decision,
            temp_verify_decision=temp_verify.decision,
            note="approval.verifier_status != temp_verify.verifier_status",
        )

    # 1. Take rollback snapshot.
    snap = _take_snapshot(
        workspace=ws,
        snapshot_root=Path(snapshot_root),
        snapshot_id=snapshot_id,
        approval=approval,
        temp_verify=temp_verify,
    )
    if not snap.is_written:
        return _blocked(
            "REAL_APPROVAL_APPLY_BLOCKED_MISMATCH",
            ws=str(ws),
            approval_decision=approval.decision,
            temp_verify_decision=temp_verify.decision,
            rollback_snapshot_decision=snap.decision,
            note=f"snapshot not written: {snap.decision}",
        )

    # 2. Apply.
    plan_rec = _synthesize_quarantine_plan(
        plan_entries,
        workspace=str(ws),
        model_id=model_id,
        provider=provider,
    )
    if not plan_rec.is_quarantined:
        return _blocked(
            "REAL_APPROVAL_APPLY_BLOCKED_MISMATCH",
            ws=str(ws),
            approval_decision=approval.decision,
            temp_verify_decision=temp_verify.decision,
            rollback_snapshot_decision=snap.decision,
            note="plan_entries did not synthesize into a quarantine record",
        )

    apply_rec = _apply_after_approval(
        workspace=ws,
        approval=approval,
        temp_verify=temp_verify,
        rollback_snapshot=snap,
        plan=plan_rec,
        plan_entries=plan_entries,
        observed_diff=observed_diff,
    )
    if not apply_rec.is_applied:
        return _blocked(
            "REAL_APPROVAL_APPLY_BLOCKED_MISMATCH",
            ws=str(ws),
            approval_decision=approval.decision,
            temp_verify_decision=temp_verify.decision,
            rollback_snapshot_decision=snap.decision,
            apply_decision=apply_rec.decision,
            note=f"apply blocked: {apply_rec.decision}",
        )

    # 3. Post-apply verifier.
    verifier_callable = _build_post_apply_verifier_callable(
        verifier_selection.verifier_command,
        timeout_seconds=verifier_timeout_seconds,
    )
    post = _post_run(workspace=ws, apply_record=apply_rec, verifier=verifier_callable)

    # 4. Rollback if needed.
    if post.rollback_recommended:
        rollback = _execute_rollback(
            workspace=ws,
            rollback_snapshot=snap,
            apply_record=apply_rec,
            post_apply=post,
        )
        return RealApprovalApplyPostVerifyTraceRecord(
            decision="REAL_APPROVAL_APPLY_POST_VERIFY_FAILED_ROLLBACK_REQUIRED",
            workspace_identity=str(ws),
            approval_decision=approval.decision,
            temp_verify_decision=temp_verify.decision,
            rollback_snapshot_decision=snap.decision,
            apply_decision=apply_rec.decision,
            post_apply_decision=post.decision,
            rollback_execution_decision=rollback.decision,
            source_mutation_applied=True,
            rollback_executed=rollback.is_executed,
            training_eligible=False,
            statuses_seen=("REAL_APPROVAL_APPLY_POST_VERIFY_FAILED_ROLLBACK_REQUIRED",),
            notes=(
                "post-apply verifier failed; rollback executed",
                f"rollback decision: {rollback.decision}",
                "training eligibility remains False",
            ),
        )

    return RealApprovalApplyPostVerifyTraceRecord(
        decision="REAL_APPROVAL_APPLY_POST_VERIFY_PASSED",
        workspace_identity=str(ws),
        approval_decision=approval.decision,
        temp_verify_decision=temp_verify.decision,
        rollback_snapshot_decision=snap.decision,
        apply_decision=apply_rec.decision,
        post_apply_decision=post.decision,
        rollback_execution_decision="",
        source_mutation_applied=True,
        rollback_executed=False,
        training_eligible=False,
        statuses_seen=("REAL_APPROVAL_APPLY_POST_VERIFY_PASSED",),
        notes=(
            "real approval accepted; source applied; post-apply verifier passed",
            "training eligibility remains False until a separate global "
            "training guard explicitly admits this trace",
        ),
    )


def _blocked(
    decision: str,
    *,
    ws: str,
    approval_decision: str = "",
    temp_verify_decision: str = "",
    rollback_snapshot_decision: str = "",
    apply_decision: str = "",
    note: str = "",
) -> RealApprovalApplyPostVerifyTraceRecord:
    return RealApprovalApplyPostVerifyTraceRecord(
        decision=decision,
        workspace_identity=ws,
        approval_decision=approval_decision,
        temp_verify_decision=temp_verify_decision,
        rollback_snapshot_decision=rollback_snapshot_decision,
        apply_decision=apply_decision,
        post_apply_decision="",
        rollback_execution_decision="",
        source_mutation_applied=False,
        rollback_executed=False,
        training_eligible=False,
        statuses_seen=(decision,),
        notes=(note,) if note else (),
    )


__all__ = [
    "trace",
    "REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_STATUS_TOKENS",
    "RealApprovalApplyPostVerifyTraceRecord",
]
