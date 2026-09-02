"""Source-mutation rollback executor.

If the post-apply verifier failed, restore the workspace from the
rollback snapshot. Verifies the snapshot tree hash matches the one
captured at snapshot time before restoring. Records pre/post
rollback workspace hashes.

If the post-apply verifier passed, returns SOURCE_ROLLBACK_NOT_REQUIRED
without touching the workspace.
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

from . import symlink_policy as _symlink_policy  # noqa: E402
from .post_apply_verifier_record import (  # noqa: E402
    PostApplyVerifierRecord,
)
from .source_mutation_apply_after_approval_record import (  # noqa: E402
    SourceMutationApplyAfterApprovalRecord,
)
from .source_mutation_rollback_execution_record import (
    SOURCE_MUTATION_ROLLBACK_EXECUTION_STATUS_TOKENS,
    SourceMutationRollbackExecutionRecord,
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


def execute_rollback(
    *,
    workspace: Path,
    rollback_snapshot: SourceMutationRollbackSnapshotRecord | None,
    apply_record: SourceMutationApplyAfterApprovalRecord | None,
    post_apply: PostApplyVerifierRecord | None,
) -> SourceMutationRollbackExecutionRecord:
    ws = Path(workspace).resolve()
    pre_rollback_hash = _sha256_tree(ws)

    # CLAUDE-AUTH-009 remediation: refuse to restore into a workspace
    # that contains symlink(s). The rollback executor would overwrite
    # whatever the symlink points at — including locations outside
    # the workspace. The snapshot writer has already blocked snapshots
    # of symlinked trees; defense-in-depth means the executor also
    # checks its own invariants.
    if _symlink_policy.has_symlinks(ws):
        return SourceMutationRollbackExecutionRecord(
            decision="SOURCE_ROLLBACK_BLOCKED_SYMLINKS_UNSUPPORTED",
            workspace_identity=str(ws),
            snapshot_path=getattr(rollback_snapshot, "snapshot_path", "")
            if rollback_snapshot
            else "",
            snapshot_verified_tree_hash="",
            pre_rollback_source_hash=pre_rollback_hash,
            post_rollback_source_hash=pre_rollback_hash,
            rollback_snapshot_ref=getattr(rollback_snapshot, "decision", "")
            if rollback_snapshot
            else "",
            apply_ref=getattr(apply_record, "decision", "") if apply_record else "",
            verifier_ref=getattr(post_apply, "decision", "") if post_apply else "",
            training_eligible=False,
            notes=(
                "workspace contains symlink(s); rollback executor refuses "
                "to restore through symlinks (CLAUDE-AUTH-009 remediation)",
            ),
        )

    if post_apply is None or not post_apply.rollback_recommended:
        return SourceMutationRollbackExecutionRecord(
            decision="SOURCE_ROLLBACK_NOT_REQUIRED",
            workspace_identity=str(ws),
            snapshot_path=getattr(rollback_snapshot, "snapshot_path", "")
            if rollback_snapshot
            else "",
            snapshot_verified_tree_hash="",
            pre_rollback_source_hash=pre_rollback_hash,
            post_rollback_source_hash=pre_rollback_hash,
            rollback_snapshot_ref=getattr(rollback_snapshot, "decision", "")
            if rollback_snapshot
            else "",
            apply_ref=getattr(apply_record, "decision", "") if apply_record else "",
            verifier_ref=getattr(post_apply, "decision", "") if post_apply else "",
            training_eligible=False,
            notes=("post-apply verifier did not request rollback",),
        )

    if rollback_snapshot is None or not rollback_snapshot.is_written:
        return SourceMutationRollbackExecutionRecord(
            decision="SOURCE_ROLLBACK_BLOCKED_MISSING_SNAPSHOT",
            workspace_identity=str(ws),
            snapshot_path="",
            snapshot_verified_tree_hash="",
            pre_rollback_source_hash=pre_rollback_hash,
            post_rollback_source_hash=pre_rollback_hash,
            rollback_snapshot_ref=getattr(rollback_snapshot, "decision", "")
            if rollback_snapshot
            else "",
            apply_ref=getattr(apply_record, "decision", "") if apply_record else "",
            verifier_ref=post_apply.decision,
            training_eligible=False,
            notes=("rollback snapshot missing or not written",),
        )

    snap_path = Path(rollback_snapshot.snapshot_path)
    if not snap_path.is_dir():
        return SourceMutationRollbackExecutionRecord(
            decision="SOURCE_ROLLBACK_BLOCKED_MISSING_SNAPSHOT",
            workspace_identity=str(ws),
            snapshot_path=str(snap_path),
            snapshot_verified_tree_hash="",
            pre_rollback_source_hash=pre_rollback_hash,
            post_rollback_source_hash=pre_rollback_hash,
            rollback_snapshot_ref=rollback_snapshot.decision,
            apply_ref=getattr(apply_record, "decision", "") if apply_record else "",
            verifier_ref=post_apply.decision,
            training_eligible=False,
            notes=(f"snapshot path does not exist: {snap_path}",),
        )

    # Verify snapshot tree hash matches what was recorded at snapshot time.
    current_snap_hash = _sha256_tree(snap_path)
    if current_snap_hash != rollback_snapshot.snapshot_tree_hash:
        return SourceMutationRollbackExecutionRecord(
            decision="SOURCE_ROLLBACK_BLOCKED_SNAPSHOT_HASH_MISMATCH",
            workspace_identity=str(ws),
            snapshot_path=str(snap_path),
            snapshot_verified_tree_hash=current_snap_hash,
            pre_rollback_source_hash=pre_rollback_hash,
            post_rollback_source_hash=pre_rollback_hash,
            rollback_snapshot_ref=rollback_snapshot.decision,
            apply_ref=getattr(apply_record, "decision", "") if apply_record else "",
            verifier_ref=post_apply.decision,
            training_eligible=False,
            notes=(
                "snapshot tree hash changed since snapshot was written",
                "refusing to restore from a mutated snapshot",
            ),
        )

    # Restore: replace workspace contents with snapshot contents.
    # We don't delete the workspace dir itself (keep symlinks/perm bits),
    # we re-copy file contents and remove anything not present in the
    # snapshot.
    snap_files = {p.relative_to(snap_path).as_posix() for p in snap_path.rglob("*") if p.is_file()}
    ws_files = {p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_file()}

    # Remove files in ws that are not in snap.
    for extra_rel in sorted(ws_files - snap_files):
        target = ws / extra_rel
        try:
            target.unlink()
        except OSError:
            pass
    # Copy/overwrite files from snap to ws.
    for rel in sorted(snap_files):
        src = snap_path / rel
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    post_rollback_hash = _sha256_tree(ws)

    return SourceMutationRollbackExecutionRecord(
        decision="SOURCE_ROLLBACK_EXECUTED",
        workspace_identity=str(ws),
        snapshot_path=str(snap_path),
        snapshot_verified_tree_hash=current_snap_hash,
        pre_rollback_source_hash=pre_rollback_hash,
        post_rollback_source_hash=post_rollback_hash,
        rollback_snapshot_ref=rollback_snapshot.decision,
        apply_ref=getattr(apply_record, "decision", "") if apply_record else "",
        verifier_ref=post_apply.decision,
        training_eligible=False,
        notes=(
            "source restored from rollback snapshot",
            "post-rollback workspace hash captured",
            "no training row written",
        ),
    )


__all__ = [
    "execute_rollback",
    "SOURCE_MUTATION_ROLLBACK_EXECUTION_STATUS_TOKENS",
    "SourceMutationRollbackExecutionRecord",
]
