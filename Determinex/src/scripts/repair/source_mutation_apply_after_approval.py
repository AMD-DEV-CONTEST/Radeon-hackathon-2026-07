"""Source mutation apply, after approval.

The FIRST place that actually writes the user's original workspace.
Before applying it re-checks every gate:

  - approval ACCEPTED with non-empty signature
  - temp verify PASSED
  - rollback snapshot WRITTEN
  - pre-apply source hash matches the snapshot's pre_apply hash
  - approval diff_hash matches a fresh hash of the supplied diff
  - each plan path normalizes to a relative POSIX path under the
    workspace (no ``..``, absolute, drive-anchored)
  - each accepted plan path has a body in plan_entries

If any gate fails, the workspace is NOT touched.

After a successful write, ``post_apply_verifier_required=True`` is
recorded; running it is rung 9.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterable
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide.real_human_approval_admission_record import (  # noqa: E402
    RealHumanApprovalAdmissionRecord,
)

from . import patch_body_hash as _patch_body_hash  # noqa: E402
from . import symlink_policy as _symlink_policy  # noqa: E402
from .real_patch_plan_quarantine_record import (  # noqa: E402
    RealPatchPlanQuarantineRecord,
)
from .real_temp_patch_verify_record import (  # noqa: E402
    RealTempPatchVerifyRecord,
)
from .source_mutation_apply_after_approval_record import (
    SOURCE_MUTATION_APPLY_AFTER_APPROVAL_STATUS_TOKENS,
    SourceMutationApplyAfterApprovalRecord,
)
from .source_mutation_rollback_snapshot_record import (  # noqa: E402
    SourceMutationRollbackSnapshotRecord,
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


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _normalize_rel(raw: str) -> tuple[str, str]:
    if not isinstance(raw, str) or not raw:
        return "", "empty"
    if "\x00" in raw:
        return "", "NUL byte"
    s = raw.replace("\\", "/")
    if s.startswith("/") or s.startswith("//"):
        return "", "absolute"
    first = s.split("/")[0]
    if ":" in first:
        return "", "drive-anchored"
    parts = [p for p in s.split("/") if p]
    for p in parts:
        if p == "..":
            return "", "contains '..'"
    if not parts:
        return "", "empty after normalize"
    return "/".join(parts), ""


def apply_after_approval(
    *,
    workspace: Path,
    approval: RealHumanApprovalAdmissionRecord | None,
    temp_verify: RealTempPatchVerifyRecord | None,
    rollback_snapshot: SourceMutationRollbackSnapshotRecord | None,
    plan: RealPatchPlanQuarantineRecord | None,
    plan_entries: Iterable[dict],
    observed_diff: str,
) -> SourceMutationApplyAfterApprovalRecord:
    ws = Path(workspace).resolve()
    pre_hash = _sha256_tree(ws)

    # CLAUDE-AUTH-009 remediation: refuse to apply into a workspace
    # that contains symlink(s). The apply gate has no safe semantics
    # for "write through a symlink" — that could redirect the write
    # outside the workspace. The rollback snapshotter has already
    # blocked the snapshot, but defense-in-depth: the apply gate
    # checks its own invariants and never trusts upstream callers.
    if _symlink_policy.has_symlinks(ws):
        return _block(
            "SOURCE_MUTATION_BLOCKED_SYMLINKS_UNSUPPORTED",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=getattr(approval, "diff_hash", "") if approval else "",
            approval_ref=getattr(approval, "decision", "") if approval else "",
            verifier_ref=getattr(temp_verify, "verifier_status", "") if temp_verify else "",
            rollback_ref=getattr(rollback_snapshot, "decision", "") if rollback_snapshot else "",
            note=(
                "workspace contains symlink(s); apply gate refuses to "
                "dereference (CLAUDE-AUTH-009 remediation)"
            ),
        )

    if approval is None or not approval.is_accepted:
        return _block(
            "SOURCE_MUTATION_BLOCKED_NO_APPROVAL",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=getattr(approval, "diff_hash", "") if approval else "",
            approval_ref=getattr(approval, "decision", "") if approval else "",
            verifier_ref=getattr(temp_verify, "verifier_status", "") if temp_verify else "",
            rollback_ref=getattr(rollback_snapshot, "decision", "") if rollback_snapshot else "",
            note="approval missing or not accepted",
        )

    # CLAUDE-AUTH-002 remediation: refuse fixture approvals AT THE
    # APPLY GATE itself. Previously this check existed only at the
    # admission constructor and the rung-8 orchestrator. A direct
    # call to apply_after_approval with a fixture-ACCEPTED record
    # would have bypassed it.
    if getattr(approval, "is_fixture", False):
        return _block(
            "SOURCE_MUTATION_BLOCKED_FIXTURE_APPROVAL",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=getattr(temp_verify, "verifier_status", "") if temp_verify else "",
            rollback_ref=getattr(rollback_snapshot, "decision", "") if rollback_snapshot else "",
            note="approval is fixture; apply gate refuses fixture approvals",
        )
    if getattr(approval, "signature_kind", "") not in {"real_local_signed", "real_local_hmac"}:
        return _block(
            "SOURCE_MUTATION_BLOCKED_INVALID_SIGNATURE_KIND",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=getattr(temp_verify, "verifier_status", "") if temp_verify else "",
            rollback_ref=getattr(rollback_snapshot, "decision", "") if rollback_snapshot else "",
            note=(
                f"signature_kind={approval.signature_kind!r} is not "
                "in the production set {real_local_signed, real_local_hmac}"
            ),
        )

    if temp_verify is None or not temp_verify.is_passed:
        return _block(
            "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=getattr(temp_verify, "verifier_status", "") if temp_verify else "",
            rollback_ref=getattr(rollback_snapshot, "decision", "") if rollback_snapshot else "",
            note="temp_verify missing or did not pass",
        )

    if rollback_snapshot is None or not rollback_snapshot.is_written:
        return _block(
            "SOURCE_MUTATION_BLOCKED_NO_ROLLBACK",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            rollback_ref=getattr(rollback_snapshot, "decision", "") if rollback_snapshot else "",
            note="rollback snapshot missing or not written",
        )

    if pre_hash != rollback_snapshot.pre_apply_source_hash:
        return _block(
            "SOURCE_MUTATION_BLOCKED_SOURCE_HASH_MISMATCH",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            rollback_ref=rollback_snapshot.decision,
            note=("workspace hash diverged from snapshot.pre_apply_source_hash"),
        )

    if _hash(observed_diff) != approval.diff_hash:
        return _block(
            "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            rollback_ref=rollback_snapshot.decision,
            note="observed diff hash != approval.diff_hash",
        )

    # CLAUDE-AUTH-001 remediation: bind the approval to the actual
    # patch bodies, not just the diff narrative. Compute canonical
    # hash from plan_entries now; require approval.canonical_patch_body_hash
    # to be non-empty and to match.
    expected_body_hash = getattr(approval, "canonical_patch_body_hash", "") or ""
    if not expected_body_hash:
        return _block(
            "SOURCE_MUTATION_BLOCKED_MISSING_BODY_HASH",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            rollback_ref=rollback_snapshot.decision,
            note=(
                "approval.canonical_patch_body_hash is empty; apply gate "
                "now requires a body-content binding (CLAUDE-AUTH-001)"
            ),
        )
    actual_body_hash = _patch_body_hash.compute(list(plan_entries or ()))
    if not actual_body_hash.is_valid:
        return _block(
            "SOURCE_MUTATION_BLOCKED_MISSING_BODY_HASH",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            rollback_ref=rollback_snapshot.decision,
            note=(
                "could not compute canonical_patch_body_hash from plan_entries: "
                f"{actual_body_hash.rejected_reason}"
            ),
        )
    if actual_body_hash.hex_digest != expected_body_hash:
        return _block(
            "SOURCE_MUTATION_BLOCKED_BODY_HASH_MISMATCH",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            rollback_ref=rollback_snapshot.decision,
            note=(
                "plan_entries body hash does not match approval.canonical_patch_body_hash "
                "(CLAUDE-AUTH-001 attack scenario blocked)"
            ),
        )

    # Resolve bodies from plan_entries by accepted path.
    accepted_paths: set[str] = set()
    if plan and plan.is_quarantined:
        accepted_paths = {e.path for e in plan.accepted}
    bodies: dict[str, str] = {}
    for raw in plan_entries or ():
        if not isinstance(raw, dict):
            continue
        norm, err = _normalize_rel(str(raw.get("path") or ""))
        if not norm:
            return _block(
                "SOURCE_MUTATION_BLOCKED_PATH_ESCAPE",
                workspace=str(ws),
                pre_hash=pre_hash,
                diff_hash=approval.diff_hash,
                approval_ref=approval.decision,
                verifier_ref=temp_verify.verifier_status,
                rollback_ref=rollback_snapshot.decision,
                note=f"path rejected during apply: {err}",
            )
        if accepted_paths and norm not in accepted_paths:
            # The plan record didn't accept this path — skip; we only
            # write what passed the quarantine validator.
            continue
        if isinstance(raw.get("new_content"), str):
            bodies[norm] = raw["new_content"]

    if not bodies:
        return _block(
            "SOURCE_MUTATION_BLOCKED_PLAN_BODY_MISSING",
            workspace=str(ws),
            pre_hash=pre_hash,
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            rollback_ref=rollback_snapshot.decision,
            note="no resolvable plan bodies for accepted paths",
        )

    # Apply.
    applied: list[str] = []
    for norm, content in sorted(bodies.items()):
        # Defensive re-check that target stays inside ws.
        target = (ws / norm).resolve()
        try:
            target.relative_to(ws)
        except ValueError:
            return _block(
                "SOURCE_MUTATION_BLOCKED_PATH_ESCAPE",
                workspace=str(ws),
                pre_hash=pre_hash,
                diff_hash=approval.diff_hash,
                approval_ref=approval.decision,
                verifier_ref=temp_verify.verifier_status,
                rollback_ref=rollback_snapshot.decision,
                note=f"resolved path escapes workspace: {target}",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        applied.append(norm)

    post_hash = _sha256_tree(ws)

    return SourceMutationApplyAfterApprovalRecord(
        decision="SOURCE_MUTATION_APPLIED_AFTER_APPROVAL",
        workspace_identity=str(ws),
        pre_apply_source_hash=pre_hash,
        post_apply_source_hash=post_hash,
        applied_paths=tuple(applied),
        diff_hash=approval.diff_hash,
        approval_ref=approval.decision,
        verifier_ref=temp_verify.verifier_status,
        rollback_snapshot_ref=rollback_snapshot.snapshot_path,
        source_mutation_applied=True,
        post_apply_verifier_required=True,
        training_eligible=False,
        notes=(
            "source mutation applied after real approval",
            "post-apply verifier required (rung 9)",
            "rollback snapshot available if verifier fails",
            "training eligibility remains False",
        ),
    )


def _block(
    decision: str,
    *,
    workspace: str,
    pre_hash: str,
    diff_hash: str,
    approval_ref: str,
    verifier_ref: str,
    rollback_ref: str,
    note: str,
) -> SourceMutationApplyAfterApprovalRecord:
    return SourceMutationApplyAfterApprovalRecord(
        decision=decision,
        workspace_identity=workspace,
        pre_apply_source_hash=pre_hash,
        post_apply_source_hash=pre_hash,  # unchanged on block
        applied_paths=tuple(),
        diff_hash=diff_hash,
        approval_ref=approval_ref,
        verifier_ref=verifier_ref,
        rollback_snapshot_ref=rollback_ref,
        source_mutation_applied=False,
        post_apply_verifier_required=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "apply_after_approval",
    "SOURCE_MUTATION_APPLY_AFTER_APPROVAL_STATUS_TOKENS",
    "SourceMutationApplyAfterApprovalRecord",
]
