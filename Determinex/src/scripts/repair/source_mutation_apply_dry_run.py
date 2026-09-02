"""Source mutation apply dry-run.

Consumes an approval packet fixture + observed source state. Computes
what WOULD be applied, without actually writing. Detects stale source,
diff mismatch, missing approval, and verifier-not-passed.

This rung never writes to source.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ide.human_approval_ui_record import HumanApprovalPacket  # noqa: E402

from .source_mutation_apply_record import (
    SOURCE_APPLY_DRY_RUN_STATUS_TOKENS,
    SourceApplyDryRunRecord,
)


def _hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
    return out


class SourceMutationApplyDryRun:
    """Stateless dry-run."""

    def run(
        self,
        workspace: Path,
        *,
        approval: HumanApprovalPacket | None,
        observed_diff: str,
        observed_source_hash_at_packet_time: str,
        verifier_status: str,
    ) -> SourceApplyDryRunRecord:
        ws = Path(workspace).resolve()
        before = _hash_tree(ws)

        # 1. Approval required.
        if approval is None or not approval.approval_required:
            return SourceApplyDryRunRecord(
                decision="SOURCE_APPLY_DRY_RUN_BLOCKED_NO_APPROVAL",
                workspace=str(ws),
                source_unchanged=True,
                notes=("approval missing or not required",),
            )

        # 2. Verifier must have passed.
        if verifier_status != "PATCH_VERIFIER_PASSED_TEMP_ONLY":
            return SourceApplyDryRunRecord(
                decision="SOURCE_APPLY_DRY_RUN_BLOCKED_VERIFIER_NOT_PASSED",
                workspace=str(ws),
                source_unchanged=True,
                notes=(f"verifier status={verifier_status!r}",),
            )

        # 3. Diff must match packet.
        if _hash_text(observed_diff) != approval.diff_hash:
            return SourceApplyDryRunRecord(
                decision="SOURCE_APPLY_DRY_RUN_BLOCKED_DIFF_MISMATCH",
                workspace=str(ws),
                source_unchanged=True,
                notes=("diff hash mismatch",),
            )

        # 4. Source must not be stale.
        current_source_hash = _aggregate_tree_hash(before)
        if observed_source_hash_at_packet_time != current_source_hash:
            return SourceApplyDryRunRecord(
                decision="SOURCE_APPLY_DRY_RUN_BLOCKED_STALE_SOURCE",
                workspace=str(ws),
                source_unchanged=True,
                notes=("source changed since packet was created",),
            )

        # 5. All checks pass — compute would-apply plan from the packet's
        #    files_changed. We do NOT write.
        after = _hash_tree(ws)
        assert before == after, "dry-run mutated workspace — invariant violation"

        return SourceApplyDryRunRecord(
            decision="SOURCE_APPLY_DRY_RUN_READY",
            workspace=str(ws),
            files_would_change=tuple(approval.files_changed),
            conflicts=(),
            source_unchanged=True,
            training_eligible=False,
            notes=(
                "dry-run only; no write performed; real apply requires a separate, audited step",
            ),
        )


def _aggregate_tree_hash(tree: dict[str, str]) -> str:
    h = hashlib.sha256()
    for k in sorted(tree.keys()):
        h.update(k.encode("utf-8"))
        h.update(b"\x1f")
        h.update(tree[k].encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def workspace_hash(workspace: Path) -> str:
    return _aggregate_tree_hash(_hash_tree(Path(workspace)))


__all__ = [
    "SourceMutationApplyDryRun",
    "SourceApplyDryRunRecord",
    "SOURCE_APPLY_DRY_RUN_STATUS_TOKENS",
    "workspace_hash",
]
