"""
determinex_cloak/restoration.py — Component 6: RestorationEngine.

Reverses obfuscation on AI-generated patches and file content.
Unrecognized x_NNNN tokens (AI-invented names) pass through unchanged.
"""

from __future__ import annotations

import re

from .symbol_map import SymbolMap

_X_TOKEN_RE = re.compile(r"\bx_\d{4}\b")

# Unified diff header prefixes — never touch these lines
_DIFF_HEADERS = (
    "---",
    "+++",
    "@@",
    "diff ",
    "index ",
    "new file",
    "old mode",
    "new mode",
    "deleted file",
    "similarity",
    "rename",
    "copy",
)


def restore_file_content(obfuscated: str, symbol_map: SymbolMap) -> str:
    """
    Restore an obfuscated file content string back to original identifiers.
    Unrecognized x_NNNN tokens (AI-invented) pass through unchanged.
    """
    if not symbol_map.reverse:
        return obfuscated
    sorted_tokens = sorted(symbol_map.reverse.keys(), key=len, reverse=True)
    result = obfuscated
    for token in sorted_tokens:
        if token in result:
            result = result.replace(token, symbol_map.reverse[token])
    return result


def restore_patch(
    raw_patch: str,
    symbol_map: SymbolMap,
) -> tuple[str | None, str | None]:
    """
    Restore obfuscated identifiers in a unified diff patch.

    Operates text-level on diff content lines. Diff header lines are untouched.
    Unrecognized x_NNNN tokens pass through unchanged.

    Returns:
        (restored_patch, None)         — success
        (None, error_description)      — failure (incomplete restoration of known tokens)
    """
    if not raw_patch.strip():
        return None, "empty patch"

    sorted_tokens = sorted(symbol_map.reverse.keys(), key=len, reverse=True)
    lines = raw_patch.splitlines(keepends=True)
    restored: list[str] = []

    for line in lines:
        if any(line.startswith(h) for h in _DIFF_HEADERS):
            restored.append(line)
            continue
        new_line = line
        for token in sorted_tokens:
            if token in new_line:
                new_line = new_line.replace(token, symbol_map.reverse[token])
        restored.append(new_line)

    result = "".join(restored)

    remaining = set(_X_TOKEN_RE.findall(result)) & set(symbol_map.reverse.keys())
    if remaining:
        return None, f"restoration incomplete — {len(remaining)} known tokens remain: {remaining}"

    return result, None
