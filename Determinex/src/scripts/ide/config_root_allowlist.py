"""Config root allowlist verifier.

CLAUDE_CONFIG_ROOT_ALLOWLIST_LOCK_001 — rung 5.

Verifies that a candidate config_root or workspace_root is:

  * not malformed
  * not a path-traversal attempt
  * not a dangerous/system root
  * within a caller-supplied allowlist of trusted parents

The verifier does NOT create the directory; it does NOT write
anything. It is a pure path classifier the apply gate / config
saver can require BEFORE touching disk.

Cross-platform: the dangerous-root set covers Windows and POSIX
conventions. Allowed parents are normalized to lowercase on
Windows (case-insensitive) and as-is elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path, PurePath

from .config_root_allowlist_record import (
    CONFIG_ROOT_ALLOWLIST_STATUS_TOKENS,
    ConfigRootAllowlistRecord,
)

# Conservative dangerous-root denylist. Two tiers:
#
# Exact-match only: the bare drive/filesystem root (e.g. "/" or
# "c:\\"). Prefix-matching these would refuse every absolute path
# on the system; we just want to refuse the root itself.
#
# Prefix-match: system sub-roots that should never contain a
# config_root, even one nested several levels deep.
_DANGEROUS_ROOTS_POSIX_EXACT = ("/",)
_DANGEROUS_ROOTS_POSIX_PREFIX = (
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/boot",
    "/sys",
    "/proc",
    "/dev",
    "/root",
    "/var",
    "/lib",
    "/lib64",
    "/System",
    "/Library",
)
_DANGEROUS_ROOTS_WINDOWS_EXACT = ("c:\\", "d:\\", "e:\\")
_DANGEROUS_ROOTS_WINDOWS_PREFIX = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
    "d:\\windows",
    "e:\\windows",
)


def _is_windows() -> bool:
    return sys.platform.startswith("win") or sys.platform == "cygwin"


def _normalize_for_compare(p: PurePath) -> str:
    """Normalize a path for cross-platform comparison."""
    s = str(p)
    if _is_windows():
        return s.lower().replace("/", "\\")
    return s


def _is_inside(child: Path, parent: Path) -> bool:
    """True iff resolved child is inside resolved parent."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def verify(
    requested_root: str | Path | None,
    *,
    allowed_parents: list[str | Path],
) -> ConfigRootAllowlistRecord:
    """Verify a candidate config_root.

    ``allowed_parents`` is the explicit, caller-supplied set of
    paths under which the config_root must reside. Examples:
      - the user's profile directory
      - the workspace root they explicitly selected
      - a temp directory for test fixtures

    The function never expands the allowlist on its own. An empty
    allowed_parents list means EVERY root is refused.
    """
    if requested_root is None or requested_root == "":
        return _block(
            "CONFIG_ROOT_BLOCKED_MALFORMED_PATH",
            requested=str(requested_root or ""),
            resolved="",
            allowed_parent="",
            note="requested_root is empty",
        )

    raw = str(requested_root)
    if "\x00" in raw:
        return _block(
            "CONFIG_ROOT_BLOCKED_MALFORMED_PATH",
            requested=raw,
            resolved="",
            allowed_parent="",
            note="requested_root contains NUL",
        )

    # Path traversal — check the raw input BEFORE resolution, so an
    # attacker cannot hide ".." behind a resolved absolute that lands
    # inside the allowlist.
    raw_parts = [seg for seg in raw.replace("\\", "/").split("/") if seg]
    if any(seg == ".." for seg in raw_parts):
        return _block(
            "CONFIG_ROOT_BLOCKED_PATH_TRAVERSAL",
            requested=raw,
            resolved="",
            allowed_parent="",
            note="requested_root contains '..' segment",
        )

    try:
        resolved = Path(raw).resolve(strict=False)
    except (OSError, ValueError) as exc:
        return _block(
            "CONFIG_ROOT_BLOCKED_MALFORMED_PATH",
            requested=raw,
            resolved="",
            allowed_parent="",
            note=f"could not resolve requested_root: {exc}",
        )

    # Dangerous-root check. Two tiers:
    #
    #   * Exact: the drive/filesystem root itself ("/" or "c:\\").
    #     Refuse iff resolved EXACTLY equals it (prefix-matching
    #     these would refuse every absolute path).
    #   * Prefix: system sub-roots. Refuse iff resolved equals OR
    #     is inside any of them.
    if _is_windows():
        exact_dangerous = _DANGEROUS_ROOTS_WINDOWS_EXACT
        prefix_dangerous = _DANGEROUS_ROOTS_WINDOWS_PREFIX
    else:
        exact_dangerous = _DANGEROUS_ROOTS_POSIX_EXACT
        prefix_dangerous = _DANGEROUS_ROOTS_POSIX_PREFIX

    for dr_raw in exact_dangerous:
        dr_path = Path(dr_raw).resolve(strict=False)
        if resolved == dr_path:
            return _block(
                "CONFIG_ROOT_BLOCKED_DISALLOWED_ROOT",
                requested=raw,
                resolved=str(resolved),
                allowed_parent="",
                note=f"resolved root {str(resolved)!r} is the bare filesystem root {dr_raw!r}",
            )

    for dr_raw in prefix_dangerous:
        dr_path = Path(dr_raw).resolve(strict=False)
        if resolved == dr_path or _is_inside(resolved, dr_path):
            return _block(
                "CONFIG_ROOT_BLOCKED_DISALLOWED_ROOT",
                requested=raw,
                resolved=str(resolved),
                allowed_parent="",
                note=f"resolved root {str(resolved)!r} is inside dangerous system root {dr_raw!r}",
            )

    # Allowlist check.
    if not allowed_parents:
        return _block(
            "CONFIG_ROOT_BLOCKED_UNTRUSTED_CONFIG",
            requested=raw,
            resolved=str(resolved),
            allowed_parent="",
            note="no allowed_parents supplied; every root refused",
        )

    for parent in allowed_parents:
        p = Path(parent)
        try:
            p_resolved = p.resolve(strict=False)
        except (OSError, ValueError):
            continue
        if resolved == p_resolved or _is_inside(resolved, p_resolved):
            return ConfigRootAllowlistRecord(
                decision="CONFIG_ROOT_ALLOWLIST_PASSED",
                requested_root=raw,
                resolved_root=str(resolved),
                allowed_parent=str(p_resolved),
                source_mutation_authorized=False,
                training_eligible=False,
                notes=(
                    "config root resolved and inside allowlisted parent",
                    "verifier does not create the directory",
                    "does not authorize source mutation or training",
                ),
            )

    return _block(
        "CONFIG_ROOT_BLOCKED_UNTRUSTED_CONFIG",
        requested=raw,
        resolved=str(resolved),
        allowed_parent="",
        note="resolved root is not inside any allowed_parent",
    )


def _block(
    decision: str,
    *,
    requested: str,
    resolved: str,
    allowed_parent: str,
    note: str,
) -> ConfigRootAllowlistRecord:
    return ConfigRootAllowlistRecord(
        decision=decision,
        requested_root=requested,
        resolved_root=resolved,
        allowed_parent=allowed_parent,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "verify",
    "CONFIG_ROOT_ALLOWLIST_STATUS_TOKENS",
    "ConfigRootAllowlistRecord",
]
