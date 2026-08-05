"""Safe temp-workspace patch applier with diff capture and rollback.

Locked under ``SAFE_PATCH_DIFF_ROLLBACK_LOCK_001``. The applier:

  * **Never writes to the original repo**. The original is treated as
    immutable; sha256 trees are taken before and after the call and the
    invariant is asserted at the end.
  * Stages a bounded copy under a caller-supplied ``temp_root`` (tests
    use ``tmp_path``). The temp workspace is bounded to that root; any
    operation that would escape it is blocked.
  * Validates each ``FilePatch`` for path traversal, symlink escape, and
    binary content before writing.
  * Generates a unified diff (via :mod:`difflib`) over the *temp*
    workspace's before/after state.
  * Optionally runs a verifier callable on the temp workspace. The
    default verifier returns ``PATCH_VERIFIER_SKIPPED`` — wiring a real
    BuildAdapter-backed verifier is the next rung
    (``VERIFIED_REPAIR_TRACE_LOCK_001``).
  * Rolls back (deletes the temp tree) on patch rejection or verifier
    failure, when the caller requests it via ``rollback_on_failure``.

Public surface:

  from repair.safe_patch_workspace import (
      SafePatchWorkspace, FilePatch, SafePatchResult, VerifierResult,
      SAFE_PATCH_STATUS_TOKENS, stub_verifier_pass, stub_verifier_fail,
  )
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .safe_patch_record import (
    SAFE_PATCH_STATUS_TOKENS,
    FilePatch,
    SafePatchResult,
)

_FORBIDDEN_PATH_SEGMENTS = frozenset({"..", ""})  # "" guards leading "/"
_MAX_PATCH_BYTES = 2_000_000  # 2 MB per file — refuse to load larger
_MAX_TOTAL_BYTES = 16_000_000  # 16 MB across all patches


@dataclass(frozen=True)
class VerifierResult:
    """Verifier outcome on the temp workspace."""

    passed: bool
    output: str = ""


def stub_verifier_pass(_temp_workspace: Path) -> VerifierResult:
    return VerifierResult(passed=True, output="STUB_VERIFIER_PASS")


def stub_verifier_fail(_temp_workspace: Path) -> VerifierResult:
    return VerifierResult(passed=False, output="STUB_VERIFIER_FAIL")


def _sha256_tree(root: Path) -> dict[str, str]:
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


def _normalize_rel(p: str) -> tuple[str, str]:
    """Return (cleaned, reason) where reason='' means OK.

    Rejects:
      * absolute paths
      * any segment containing ``..``
      * empty path
      * non-portable drive letters / UNC roots
    """
    if not p:
        return "", "empty path"
    raw = p.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("//") or ":" in raw.split("/")[0]:
        return "", "absolute or drive-anchored path"
    parts = [seg for seg in raw.split("/") if seg]
    for seg in parts:
        if seg == ".." or seg == "":
            return "", "contains '..'"
    if not parts:
        return "", "empty after normalization"
    return "/".join(parts), ""


def _path_is_inside(child: Path, parent: Path) -> bool:
    try:
        c = child.resolve(strict=False)
        p = parent.resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    try:
        c.relative_to(p)
        return True
    except ValueError:
        return False


def _is_binary_text(s: str) -> bool:
    """Heuristic: reject content with NULs. UTF-8 decoding already happened
    upstream; here we just guard against embedded NULs which would break
    most tools and almost certainly indicate a binary blob."""
    return "\x00" in s


def _build_unified_diff(
    workspace: Path, before: dict[str, str], after: dict[str, str], context: int = 3
) -> str:
    """Build a single unified-diff blob across all changed files."""
    lines: list[str] = []
    all_paths = sorted(set(before.keys()) | set(after.keys()))
    for rel in all_paths:
        before_hash = before.get(rel)
        after_hash = after.get(rel)
        if before_hash == after_hash:
            continue
        # Load text content; fall back to a marker for binary.
        try:
            before_text = (
                (workspace / rel).read_text(encoding="utf-8")
                if before_hash is not None and (workspace / rel).is_file() and rel in before
                else ""
            )
        except (OSError, UnicodeDecodeError):
            before_text = ""
        try:
            after_text = (
                (workspace / rel).read_text(encoding="utf-8")
                if after_hash is not None and (workspace / rel).is_file()
                else ""
            )
        except (OSError, UnicodeDecodeError):
            after_text = ""
        # Note: before content is unavailable post-write; we capture it
        # from the *_BASELINE_ directory instead. See apply_and_verify.
        lines.extend(
            difflib.unified_diff(
                before_text.splitlines(keepends=True),
                after_text.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=context,
            )
        )
    return "".join(lines)


class SafePatchWorkspace:
    """Bounded temp-workspace patch applier.

    The original repo is never written. The temp workspace lives under
    ``temp_root``; the applier creates one subdirectory there and stages
    the original's contents into it before applying patches.
    """

    __slots__ = ("_original", "_temp_root", "_workspace_id", "_temp", "_baseline")

    def __init__(self, original: Path, temp_root: Path, workspace_id: str = "ws") -> None:
        self._original = Path(original).resolve()
        self._temp_root = Path(temp_root).resolve()
        self._workspace_id = workspace_id
        self._temp = self._temp_root / f"safe_patch_{workspace_id}"
        self._baseline = self._temp_root / f"safe_patch_{workspace_id}__BASELINE_"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def original(self) -> Path:
        return self._original

    @property
    def temp_workspace(self) -> Path:
        return self._temp

    @property
    def baseline_snapshot(self) -> Path:
        return self._baseline

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------

    def stage(self) -> None:
        """Copy ``original`` → ``temp`` and ``original`` → ``baseline``.

        Raises FileExistsError if either temp path already exists — the
        caller must clean up before re-staging.
        """
        if not self._original.is_dir():
            raise FileNotFoundError(f"Original workspace missing: {self._original}")
        if not _path_is_inside(self._temp, self._temp_root):
            raise PermissionError(
                f"Temp workspace {self._temp} escapes temp_root {self._temp_root}"
            )
        if self._temp.exists() or self._baseline.exists():
            raise FileExistsError(
                f"Temp workspace already exists: {self._temp} or {self._baseline}"
            )
        shutil.copytree(self._original, self._temp, symlinks=False, dirs_exist_ok=False)
        shutil.copytree(self._original, self._baseline, symlinks=False, dirs_exist_ok=False)

    def rollback(self) -> None:
        for p in (self._temp, self._baseline):
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)

    # ------------------------------------------------------------------
    # Patch application
    # ------------------------------------------------------------------

    def apply_and_verify(
        self,
        patches: Sequence[FilePatch],
        *,
        verifier: Callable[[Path], VerifierResult] | None = None,
        rollback_on_failure: bool = True,
    ) -> SafePatchResult:
        """Stage, validate-and-apply, generate diff, run verifier.

        The original repo is never written. On any rejection or verifier
        failure (and ``rollback_on_failure=True``), the temp tree is
        deleted. The returned SafePatchResult carries the unified diff,
        verifier status, and an ``original_unchanged`` assertion.
        """
        original_before = _sha256_tree(self._original)
        notes: list[str] = []
        applied: list[str] = []
        rejected: list[dict[str, str]] = []

        # Stage if not already staged. Failures bubble up as PATCH_REJECTED with note.
        if not self._temp.exists():
            try:
                self.stage()
            except (FileExistsError, FileNotFoundError, PermissionError) as exc:
                notes.append(f"stage failed: {type(exc).__name__}: {exc}")
                return self._final_result(
                    status="PATCH_REJECTED",
                    applied=applied,
                    rejected=rejected,
                    unified_diff="",
                    verifier_status="PATCH_VERIFIER_SKIPPED",
                    verifier_output="",
                    rolled_back=False,
                    original_unchanged=(original_before == _sha256_tree(self._original)),
                    notes=notes,
                )

        # Total-size guard.
        total_bytes = sum(len(p.new_content.encode("utf-8")) for p in patches)
        if total_bytes > _MAX_TOTAL_BYTES:
            notes.append(f"total patch bytes {total_bytes} exceeds {_MAX_TOTAL_BYTES}")
            if rollback_on_failure:
                self.rollback()
            return self._final_result(
                status="PATCH_REJECTED",
                applied=applied,
                rejected=rejected,
                unified_diff="",
                verifier_status="PATCH_VERIFIER_SKIPPED",
                verifier_output="",
                rolled_back=rollback_on_failure,
                original_unchanged=(original_before == _sha256_tree(self._original)),
                notes=notes,
            )

        # Validate + apply each patch.
        for patch in patches:
            cleaned, reason = _normalize_rel(patch.path)
            if reason:
                rejected.append(
                    {"path": patch.path, "reason": reason, "status": "PATCH_BLOCKED_PATH_ESCAPE"}
                )
                if rollback_on_failure:
                    self.rollback()
                return self._final_result(
                    status="PATCH_BLOCKED_PATH_ESCAPE",
                    applied=applied,
                    rejected=rejected,
                    unified_diff="",
                    verifier_status="PATCH_VERIFIER_SKIPPED",
                    verifier_output="",
                    rolled_back=rollback_on_failure,
                    original_unchanged=(original_before == _sha256_tree(self._original)),
                    notes=notes,
                )

            target = self._temp / cleaned
            # Symlink escape check on target's parent chain.
            if not _path_is_inside(target, self._temp):
                rejected.append(
                    {
                        "path": patch.path,
                        "reason": "resolves outside temp",
                        "status": "PATCH_BLOCKED_SYMLINK_ESCAPE",
                    }
                )
                if rollback_on_failure:
                    self.rollback()
                return self._final_result(
                    status="PATCH_BLOCKED_SYMLINK_ESCAPE",
                    applied=applied,
                    rejected=rejected,
                    unified_diff="",
                    verifier_status="PATCH_VERIFIER_SKIPPED",
                    verifier_output="",
                    rolled_back=rollback_on_failure,
                    original_unchanged=(original_before == _sha256_tree(self._original)),
                    notes=notes,
                )
            # If target exists as a symlink, refuse.
            if target.exists() and target.is_symlink():
                rejected.append(
                    {
                        "path": patch.path,
                        "reason": "target is symlink",
                        "status": "PATCH_BLOCKED_SYMLINK_ESCAPE",
                    }
                )
                if rollback_on_failure:
                    self.rollback()
                return self._final_result(
                    status="PATCH_BLOCKED_SYMLINK_ESCAPE",
                    applied=applied,
                    rejected=rejected,
                    unified_diff="",
                    verifier_status="PATCH_VERIFIER_SKIPPED",
                    verifier_output="",
                    rolled_back=rollback_on_failure,
                    original_unchanged=(original_before == _sha256_tree(self._original)),
                    notes=notes,
                )

            # Binary content guard.
            if _is_binary_text(patch.new_content):
                rejected.append(
                    {
                        "path": patch.path,
                        "reason": "NUL byte in content",
                        "status": "PATCH_BLOCKED_BINARY_CONTENT",
                    }
                )
                if rollback_on_failure:
                    self.rollback()
                return self._final_result(
                    status="PATCH_BLOCKED_BINARY_CONTENT",
                    applied=applied,
                    rejected=rejected,
                    unified_diff="",
                    verifier_status="PATCH_VERIFIER_SKIPPED",
                    verifier_output="",
                    rolled_back=rollback_on_failure,
                    original_unchanged=(original_before == _sha256_tree(self._original)),
                    notes=notes,
                )

            # Per-file size guard.
            if len(patch.new_content.encode("utf-8")) > _MAX_PATCH_BYTES:
                rejected.append(
                    {"path": patch.path, "reason": "file size > 2MB", "status": "PATCH_REJECTED"}
                )
                if rollback_on_failure:
                    self.rollback()
                return self._final_result(
                    status="PATCH_REJECTED",
                    applied=applied,
                    rejected=rejected,
                    unified_diff="",
                    verifier_status="PATCH_VERIFIER_SKIPPED",
                    verifier_output="",
                    rolled_back=rollback_on_failure,
                    original_unchanged=(original_before == _sha256_tree(self._original)),
                    notes=notes,
                )

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch.new_content, encoding="utf-8", newline="")
            applied.append(cleaned)

        # Generate diff baseline → temp using the baseline copy.
        diff_blob = self._compute_diff(self._baseline, self._temp)

        # Run verifier.
        if verifier is None:
            v_status = "PATCH_VERIFIER_SKIPPED"
            v_output = ""
            v_passed: bool | None = None
        else:
            v_result = verifier(self._temp)
            v_passed = v_result.passed
            v_output = (v_result.output or "")[:4000]
            v_status = (
                "PATCH_VERIFIER_PASSED_TEMP_ONLY" if v_result.passed else "PATCH_VERIFIER_FAILED"
            )

        # Final status.
        final_status = "PATCH_APPLIED_TO_TEMP_WORKSPACE"
        rolled = False
        if v_passed is False and rollback_on_failure:
            self.rollback()
            rolled = True
            final_status = "PATCH_ROLLED_BACK"

        # Source-mutation guard — always verified.
        original_after = _sha256_tree(self._original)
        if original_before != original_after:
            return self._final_result(
                status="SOURCE_MUTATION_BLOCKED",
                applied=applied,
                rejected=rejected,
                unified_diff=diff_blob,
                verifier_status=v_status,
                verifier_output=v_output,
                rolled_back=rolled,
                original_unchanged=False,
                notes=[*notes, "original tree was modified — invariant violation"],
            )

        return self._final_result(
            status=final_status,
            applied=applied,
            rejected=rejected,
            unified_diff=diff_blob,
            verifier_status=v_status,
            verifier_output=v_output,
            rolled_back=rolled,
            original_unchanged=True,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_diff(self, baseline: Path, after: Path) -> str:
        """Compute a unified diff between baseline and after trees."""
        lines: list[str] = []
        baseline_tree = _sha256_tree(baseline)
        after_tree = _sha256_tree(after)
        for rel in sorted(set(baseline_tree.keys()) | set(after_tree.keys())):
            if baseline_tree.get(rel) == after_tree.get(rel):
                continue
            try:
                before_text = (
                    (baseline / rel).read_text(encoding="utf-8")
                    if (baseline / rel).is_file()
                    else ""
                )
            except (OSError, UnicodeDecodeError):
                before_text = ""
            try:
                after_text = (
                    (after / rel).read_text(encoding="utf-8") if (after / rel).is_file() else ""
                )
            except (OSError, UnicodeDecodeError):
                after_text = ""
            lines.extend(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True),
                    after_text.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                    n=3,
                )
            )
        return "".join(lines)

    def _final_result(
        self,
        *,
        status: str,
        applied: Iterable[str],
        rejected: Iterable[dict[str, str]],
        unified_diff: str,
        verifier_status: str,
        verifier_output: str,
        rolled_back: bool,
        original_unchanged: bool,
        notes: Iterable[str],
    ) -> SafePatchResult:
        return SafePatchResult(
            workspace=str(self._original),
            temp_workspace=str(self._temp),
            status=status,
            applied_patches=tuple(applied),
            rejected_patches=tuple(rejected),
            unified_diff=unified_diff,
            verifier_status=verifier_status,
            verifier_output=verifier_output,
            rolled_back=rolled_back,
            original_unchanged=original_unchanged,
            training_eligible=False,
            notes=tuple(notes),
        )


__all__ = [
    "FilePatch",
    "SafePatchResult",
    "SafePatchWorkspace",
    "SAFE_PATCH_STATUS_TOKENS",
    "VerifierResult",
    "stub_verifier_pass",
    "stub_verifier_fail",
]
