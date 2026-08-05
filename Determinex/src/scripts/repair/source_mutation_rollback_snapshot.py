"""Source-mutation rollback snapshot writer.

Creates a copy of the original workspace under a caller-supplied
snapshot root BEFORE any source mutation is attempted. Records the
pre-apply tree hash, the snapshot tree hash, the diff hash binding,
and references to the upstream approval and verifier results.

Source mutation is NOT applied by this lock. It produces the
snapshot the next rung will roll back to on post-apply verifier
failure.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide.real_human_approval_admission_record import (  # noqa: E402
    RealHumanApprovalAdmissionRecord,
)

from .real_temp_patch_verify_record import (  # noqa: E402
    RealTempPatchVerifyRecord,
)
from .source_mutation_rollback_snapshot_record import (
    SOURCE_MUTATION_ROLLBACK_SNAPSHOT_STATUS_TOKENS,
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


def _path_is_inside(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, RuntimeError):
        return False


def take_snapshot(
    *,
    workspace: Path,
    snapshot_root: Path,
    snapshot_id: str,
    approval: RealHumanApprovalAdmissionRecord | None,
    temp_verify: RealTempPatchVerifyRecord | None,
    expected_pre_apply_source_hash: str = "",
) -> SourceMutationRollbackSnapshotRecord:
    ws = Path(workspace).resolve()
    sroot = Path(snapshot_root).resolve()

    if approval is None or not approval.is_accepted:
        return _blocked(
            "ROLLBACK_SNAPSHOT_BLOCKED_NO_APPROVAL",
            workspace_identity=str(ws),
            diff_hash=getattr(approval, "diff_hash", "") if approval else "",
            approval_ref=getattr(approval, "decision", "") if approval else "",
            verifier_ref=getattr(temp_verify, "verifier_status", "") if temp_verify else "",
            note="approval missing or not accepted",
        )

    if temp_verify is None or not temp_verify.is_passed:
        return _blocked(
            "ROLLBACK_SNAPSHOT_BLOCKED_NO_VERIFY",
            workspace_identity=str(ws),
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=getattr(temp_verify, "verifier_status", "") if temp_verify else "",
            note="temp_verify missing or did not pass",
        )

    # CLAUDE-AUTH-009 remediation: refuse workspaces containing symlinks.
    from . import symlink_policy as _symlink_policy

    symlinks = _symlink_policy.find_symlinks(ws)
    if symlinks:
        return _blocked(
            "ROLLBACK_SNAPSHOT_BLOCKED_SYMLINKS_UNSUPPORTED",
            workspace_identity=str(ws),
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            note=(
                f"workspace contains {len(symlinks)} symlink(s); snapshot "
                "refuses to dereference (CLAUDE-AUTH-009). First: "
                f"{symlinks[0].as_posix()!r}"
            ),
        )

    # Snapshot location safety.
    try:
        sroot.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _blocked(
            "ROLLBACK_SNAPSHOT_BLOCKED_INVALID_LOCATION",
            workspace_identity=str(ws),
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            note=f"snapshot_root not writable: {exc}",
        )

    safe_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in snapshot_id)
    snap_path = sroot / f"rollback_{safe_id}"
    if not _path_is_inside(snap_path, sroot):
        return _blocked(
            "ROLLBACK_SNAPSHOT_BLOCKED_INVALID_LOCATION",
            workspace_identity=str(ws),
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            note="snapshot path escapes snapshot_root",
        )

    pre_hash = _sha256_tree(ws)
    if expected_pre_apply_source_hash and pre_hash != expected_pre_apply_source_hash:
        return _blocked(
            "ROLLBACK_SNAPSHOT_BLOCKED_SOURCE_HASH_MISMATCH",
            workspace_identity=str(ws),
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            note=(f"workspace hash {pre_hash} != expected {expected_pre_apply_source_hash}"),
        )

    if snap_path.exists():
        # Don't overwrite — refuse and let the caller pick a fresh id.
        return _blocked(
            "ROLLBACK_SNAPSHOT_BLOCKED_INVALID_LOCATION",
            workspace_identity=str(ws),
            diff_hash=approval.diff_hash,
            approval_ref=approval.decision,
            verifier_ref=temp_verify.verifier_status,
            note=f"snapshot path already exists: {snap_path}",
        )

    shutil.copytree(ws, snap_path, symlinks=False, dirs_exist_ok=False)
    snapshot_tree_hash = _sha256_tree(snap_path)

    return SourceMutationRollbackSnapshotRecord(
        decision="ROLLBACK_SNAPSHOT_WRITTEN",
        workspace_identity=str(ws),
        pre_apply_source_hash=pre_hash,
        snapshot_path=str(snap_path),
        snapshot_tree_hash=snapshot_tree_hash,
        diff_hash=approval.diff_hash,
        approval_ref=approval.decision,
        verifier_ref=temp_verify.verifier_status,
        source_mutation_applied=False,
        training_eligible=False,
        notes=(
            "rollback snapshot written",
            "source mutation NOT applied at this rung",
            "next rung is source-apply-after-approval",
        ),
    )


def _blocked(
    decision: str,
    *,
    workspace_identity: str,
    diff_hash: str,
    approval_ref: str,
    verifier_ref: str,
    note: str,
) -> SourceMutationRollbackSnapshotRecord:
    return SourceMutationRollbackSnapshotRecord(
        decision=decision,
        workspace_identity=workspace_identity,
        pre_apply_source_hash="",
        snapshot_path="",
        snapshot_tree_hash="",
        diff_hash=diff_hash,
        approval_ref=approval_ref,
        verifier_ref=verifier_ref,
        source_mutation_applied=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "take_snapshot",
    "SOURCE_MUTATION_ROLLBACK_SNAPSHOT_STATUS_TOKENS",
    "SourceMutationRollbackSnapshotRecord",
]
