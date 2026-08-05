"""Post-apply verifier runner.

Runs a hardened verifier callable on the user's workspace after a
real source-apply has completed. On PASS, the record stays
training_eligible=False (training is gated by a separate rung).
On FAIL, rollback_recommended=True so the next rung can restore
from the snapshot.

The verifier callable is pluggable; default is the locked
stub_verifier_pass. Callers should pass a real BuildAdapter-backed
verifier for production.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .post_apply_verifier_record import (
    POST_APPLY_VERIFIER_STATUS_TOKENS,
    PostApplyVerifierRecord,
)
from .safe_patch_workspace import VerifierResult, stub_verifier_pass  # noqa: E402
from .source_mutation_apply_after_approval_record import (  # noqa: E402
    SourceMutationApplyAfterApprovalRecord,
)


def _sha256_tree(root: Path) -> str:
    if not root.is_dir():
        return ""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()


def run(
    *,
    workspace: Path,
    apply_record: SourceMutationApplyAfterApprovalRecord | None,
    verifier: Callable[[Path], VerifierResult] | None = None,
    fixture_mode: bool = False,
) -> PostApplyVerifierRecord:
    """Post-apply verifier runner.

    CLAUDE-AUTH-003 remediation: verifier MUST be supplied explicitly
    in the live path. Tests that want to use stub_verifier_pass /
    stub_verifier_fail must pass `fixture_mode=True` AND supply the
    stub explicitly; otherwise the runner refuses with
    POST_APPLY_VERIFIER_BLOCKED_MISSING_VERIFIER or
    POST_APPLY_VERIFIER_BLOCKED_FIXTURE_VERIFIER_IN_LIVE_PATH.
    """
    ws = Path(workspace).resolve()

    if apply_record is None or not apply_record.is_applied:
        return PostApplyVerifierRecord(
            decision="POST_APPLY_VERIFIER_BLOCKED_NO_APPLY",
            workspace_identity=str(ws),
            verifier_status="PATCH_VERIFIER_SKIPPED",
            verifier_output="",
            post_apply_source_hash=_sha256_tree(ws),
            apply_ref=getattr(apply_record, "decision", "") if apply_record else "",
            rollback_snapshot_ref=getattr(apply_record, "rollback_snapshot_ref", "")
            if apply_record
            else "",
            rollback_recommended=False,
            training_eligible=False,
            statuses_seen=("POST_APPLY_VERIFIER_BLOCKED_NO_APPLY",),
            notes=("apply record missing or not applied",),
        )

    # CLAUDE-AUTH-003 remediation: refuse the silent-pass default.
    if verifier is None:
        return PostApplyVerifierRecord(
            decision="POST_APPLY_VERIFIER_BLOCKED_MISSING_VERIFIER",
            workspace_identity=str(ws),
            verifier_status="PATCH_VERIFIER_SKIPPED",
            verifier_output="",
            post_apply_source_hash=_sha256_tree(ws),
            apply_ref=apply_record.decision,
            rollback_snapshot_ref=apply_record.rollback_snapshot_ref,
            rollback_recommended=False,
            training_eligible=False,
            statuses_seen=(
                "POST_APPLY_VERIFIER_EXPLICIT_REQUIRED",
                "POST_APPLY_VERIFIER_BLOCKED_MISSING_VERIFIER",
            ),
            notes=(
                "no verifier supplied; the production path requires an "
                "explicit BuildAdapter-backed verifier callable",
            ),
        )

    # CLAUDE-AUTH-003 remediation: refuse stub verifiers in the live path.
    # Stub callables can only be used when fixture_mode=True is explicitly set.
    stub_callables = {stub_verifier_pass}
    try:
        from .safe_patch_workspace import stub_verifier_fail  # noqa: E402

        stub_callables.add(stub_verifier_fail)
    except ImportError:
        pass
    if verifier in stub_callables and not fixture_mode:
        return PostApplyVerifierRecord(
            decision="POST_APPLY_VERIFIER_BLOCKED_FIXTURE_VERIFIER_IN_LIVE_PATH",
            workspace_identity=str(ws),
            verifier_status="PATCH_VERIFIER_SKIPPED",
            verifier_output="",
            post_apply_source_hash=_sha256_tree(ws),
            apply_ref=apply_record.decision,
            rollback_snapshot_ref=apply_record.rollback_snapshot_ref,
            rollback_recommended=False,
            training_eligible=False,
            statuses_seen=(
                "POST_APPLY_VERIFIER_EXPLICIT_REQUIRED",
                "POST_APPLY_VERIFIER_BLOCKED_FIXTURE_VERIFIER_IN_LIVE_PATH",
            ),
            notes=(
                "stub verifier supplied without fixture_mode=True; the "
                "production path refuses fixture verifiers",
            ),
        )

    use_verifier = verifier
    vres = use_verifier(ws)
    post_hash = _sha256_tree(ws)

    # SafePatchWorkspace.VerifierResult shape: passed: bool, output: str
    passed = bool(getattr(vres, "passed", False))
    voutput = getattr(vres, "output", "")
    vstatus = "PATCH_VERIFIER_PASSED" if passed else "PATCH_VERIFIER_FAILED"

    if passed:
        return PostApplyVerifierRecord(
            decision="POST_APPLY_VERIFIER_PASSED",
            workspace_identity=str(ws),
            verifier_status=vstatus,
            verifier_output=voutput,
            post_apply_source_hash=post_hash,
            apply_ref=apply_record.decision,
            rollback_snapshot_ref=apply_record.rollback_snapshot_ref,
            rollback_recommended=False,
            training_eligible=False,
            statuses_seen=("POST_APPLY_VERIFIER_PASSED",),
            notes=(
                "verifier passed after source apply",
                "training eligibility remains False — no training row written",
                "rollback snapshot kept available",
            ),
        )

    return PostApplyVerifierRecord(
        decision="POST_APPLY_VERIFIER_FAILED",
        workspace_identity=str(ws),
        verifier_status=vstatus,
        verifier_output=voutput,
        post_apply_source_hash=post_hash,
        apply_ref=apply_record.decision,
        rollback_snapshot_ref=apply_record.rollback_snapshot_ref,
        rollback_recommended=True,
        training_eligible=False,
        statuses_seen=(
            "POST_APPLY_VERIFIER_FAILED",
            "POST_APPLY_ROLLBACK_RECOMMENDED",
        ),
        notes=(
            "verifier failed after source apply",
            "rollback recommended — rung 10 restores from snapshot",
            "no training row",
        ),
    )


__all__ = [
    "run",
    "POST_APPLY_VERIFIER_STATUS_TOKENS",
    "PostApplyVerifierRecord",
]
