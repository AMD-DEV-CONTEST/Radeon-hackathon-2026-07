"""Real temp-patch apply + verify.

Takes a quarantined plan and the original workspace, stages a copy
into a temp workspace, applies the plan there, runs the verifier, and
returns whether the temp-only result passes. The ORIGINAL SOURCE IS
NEVER WRITTEN: pre/post sha256 of the original tree is captured and
compared as a defense-in-depth invariant.

Verifier is pluggable; the default is the locked
``stub_verifier_pass`` from SafePatchWorkspace's surface. Callers
should pass a real BuildAdapter-backed verifier for production.

Pass/fail invariants:

  - PASSED      → human approval still REQUIRED before source apply
  - FAILED      → block, no further action
  - BLOCKED_*   → quarantine record missing / apply rejected
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

from .real_patch_plan_quarantine_record import (  # noqa: E402
    RealPatchPlanQuarantineRecord,
)
from .real_temp_patch_verify_record import (
    REAL_TEMP_PATCH_VERIFY_STATUS_TOKENS,
    RealTempPatchVerifyRecord,
)
from .safe_patch_record import FilePatch  # noqa: E402
from .safe_patch_workspace import (  # noqa: E402
    SafePatchWorkspace,
    VerifierResult,
    stub_verifier_pass,
)


def _sha256_tree(root: Path) -> str:
    """Stable hash over a directory tree."""
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


def verify(
    *,
    plan: RealPatchPlanQuarantineRecord | None,
    plan_entries: tuple[dict, ...] | None,
    workspace: Path,
    temp_root: Path,
    workspace_id: str = "real_temp_verify",
    verifier: Callable[[Path], VerifierResult] | None = None,
) -> RealTempPatchVerifyRecord:
    ws = Path(workspace).resolve()
    troot = Path(temp_root).resolve()

    if plan is None or not plan.is_quarantined:
        return _blocked(
            "REAL_TEMP_PATCH_BLOCKED_NOT_QUARANTINED",
            workspace=str(ws),
            temp_workspace="",
            reason="plan missing or not quarantined",
        )

    src_before = _sha256_tree(ws)
    # Map quarantine-accepted paths to the original entries' new_content.
    # The quarantine record stores only char counts as a defensive
    # design; the bodies live in plan_entries.
    accepted_paths = {e.path for e in plan.accepted}
    bodies: dict[str, str] = {}
    for raw in plan_entries or ():
        if not isinstance(raw, dict):
            continue
        norm_path = str(raw.get("path") or "").replace("\\", "/").strip("/")
        if norm_path in accepted_paths and isinstance(raw.get("new_content"), str):
            bodies[norm_path] = raw["new_content"]

    patches = tuple(
        FilePatch(path=path, new_content=bodies.get(path, ""))
        for path in accepted_paths
        if path in bodies
    )

    if not patches:
        return _blocked(
            "REAL_TEMP_PATCH_BLOCKED_APPLY_REJECTED",
            workspace=str(ws),
            temp_workspace="",
            reason="no patches resolved from plan_entries",
        )

    sw = SafePatchWorkspace(ws, troot, workspace_id=workspace_id)
    res = sw.apply_and_verify(
        patches,
        verifier=verifier or stub_verifier_pass,
        rollback_on_failure=False,
    )

    src_after = _sha256_tree(ws)
    original_unchanged = (src_before == src_after) and res.original_unchanged

    if res.is_blocked:
        return _blocked(
            "REAL_TEMP_PATCH_BLOCKED_APPLY_REJECTED",
            workspace=str(ws),
            temp_workspace=res.temp_workspace,
            reason=f"safe-patch apply blocked: {res.status}",
            src_before=src_before,
            src_after=src_after,
            original_unchanged=original_unchanged,
        )

    if res.is_verifier_pass:
        return RealTempPatchVerifyRecord(
            decision="REAL_TEMP_PATCH_VERIFIER_PASSED",
            workspace=str(ws),
            temp_workspace=res.temp_workspace,
            verifier_status=res.verifier_status,
            unified_diff=res.unified_diff,
            applied_paths=tuple(res.applied_patches),
            original_unchanged=original_unchanged,
            original_sha256_before=src_before,
            original_sha256_after=src_after,
            human_approval_required=True,
            source_mutation_authorized=False,
            training_eligible=False,
            statuses_seen=(
                "REAL_TEMP_PATCH_VERIFIER_PASSED",
                "REAL_TEMP_PATCH_SOURCE_UNCHANGED",
                "REAL_TEMP_PATCH_HUMAN_APPROVAL_REQUIRED",
            ),
            notes=(
                "verifier passed on temp workspace",
                "original source unchanged",
                "human approval required before source apply",
            ),
        )

    return RealTempPatchVerifyRecord(
        decision="REAL_TEMP_PATCH_VERIFIER_FAILED",
        workspace=str(ws),
        temp_workspace=res.temp_workspace,
        verifier_status=res.verifier_status,
        unified_diff=res.unified_diff,
        applied_paths=tuple(res.applied_patches),
        original_unchanged=original_unchanged,
        original_sha256_before=src_before,
        original_sha256_after=src_after,
        human_approval_required=False,
        source_mutation_authorized=False,
        training_eligible=False,
        statuses_seen=(
            "REAL_TEMP_PATCH_VERIFIER_FAILED",
            "REAL_TEMP_PATCH_SOURCE_UNCHANGED",
        ),
        notes=(
            "verifier failed on temp workspace",
            "original source unchanged",
            "no source apply; no human approval flow",
        ),
    )


def _blocked(
    decision: str,
    *,
    workspace: str,
    temp_workspace: str,
    reason: str,
    src_before: str = "",
    src_after: str = "",
    original_unchanged: bool = True,
) -> RealTempPatchVerifyRecord:
    return RealTempPatchVerifyRecord(
        decision=decision,
        workspace=workspace,
        temp_workspace=temp_workspace,
        verifier_status="PATCH_VERIFIER_SKIPPED",
        unified_diff="",
        applied_paths=tuple(),
        original_unchanged=original_unchanged,
        original_sha256_before=src_before,
        original_sha256_after=src_after,
        human_approval_required=False,
        source_mutation_authorized=False,
        training_eligible=False,
        statuses_seen=(decision, "REAL_TEMP_PATCH_SOURCE_UNCHANGED"),
        notes=(reason,),
    )


__all__ = [
    "verify",
    "REAL_TEMP_PATCH_VERIFY_STATUS_TOKENS",
    "RealTempPatchVerifyRecord",
]
