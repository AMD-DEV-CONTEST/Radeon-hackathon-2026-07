"""Canonical patch-body hash for the approval binding.

Computes a deterministic sha256 over the actual bodies a patch plan
intends to write. The approval packet binds this hash; the apply gate
recomputes from the plan_entries supplied at apply time and refuses
if it does not match. This closes CLAUDE-AUTH-001: the previous
``diff_hash`` only bound an operator-supplied diff narrative; the
new ``canonical_patch_body_hash`` binds the actual file content.

Canonical form, one line per accepted entry, sorted by normalized path:

    "<operation>\\0<normalized_path>\\0<sha256(new_content_utf8)>\\0<len(new_content_utf8)>\\n"

Then sha256 over the concatenated form.

Path normalization:
  - backslashes -> forward slashes
  - leading/trailing slashes stripped
  - ``..`` segments rejected (returns empty hash and a reason)
  - NUL byte rejected
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

_SUPPORTED_OPERATIONS = frozenset({"replace_file"})


@dataclass(frozen=True)
class CanonicalPatchBodyHash:
    hex_digest: str
    accepted_count: int
    rejected_reason: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.hex_digest) and not self.rejected_reason


def _normalize_rel(raw: str) -> tuple[str, str]:
    if not isinstance(raw, str) or not raw:
        return "", "empty path"
    if "\x00" in raw:
        return "", "NUL byte in path"
    s = raw.replace("\\", "/")
    if s.startswith("/") or s.startswith("//"):
        return "", "absolute path"
    first = s.split("/")[0]
    if ":" in first:
        return "", "drive-anchored path"
    parts = [p for p in s.split("/") if p]
    for p in parts:
        if p == "..":
            return "", "contains '..'"
    if not parts:
        return "", "empty after normalize"
    return "/".join(parts), ""


def compute(plan_entries: Iterable[dict]) -> CanonicalPatchBodyHash:
    """Compute the canonical patch-body hash."""
    rows: list[bytes] = []
    rejected_reason = ""
    for raw in plan_entries or ():
        if not isinstance(raw, dict):
            rejected_reason = "non-dict entry"
            return CanonicalPatchBodyHash("", 0, rejected_reason)
        op = str(raw.get("operation") or "")
        if op not in _SUPPORTED_OPERATIONS:
            rejected_reason = f"unsupported operation {op!r}"
            return CanonicalPatchBodyHash("", 0, rejected_reason)
        norm_path, err = _normalize_rel(str(raw.get("path") or ""))
        if not norm_path:
            rejected_reason = f"path: {err}"
            return CanonicalPatchBodyHash("", 0, rejected_reason)
        body = raw.get("new_content")
        if not isinstance(body, str):
            rejected_reason = f"new_content not a string for {norm_path!r}"
            return CanonicalPatchBodyHash("", 0, rejected_reason)
        if "\x00" in body:
            rejected_reason = f"NUL byte in new_content for {norm_path!r}"
            return CanonicalPatchBodyHash("", 0, rejected_reason)
        body_bytes = body.encode("utf-8")
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        row = (
            op.encode("utf-8")
            + b"\x00"
            + norm_path.encode("utf-8")
            + b"\x00"
            + body_hash.encode("utf-8")
            + b"\x00"
            + str(len(body_bytes)).encode("utf-8")
            + b"\n"
        )
        rows.append(row)

    if not rows:
        return CanonicalPatchBodyHash("", 0, "no accepted entries")

    # Deterministic order: sort by row content.
    rows.sort()
    h = hashlib.sha256()
    for row in rows:
        h.update(row)
    return CanonicalPatchBodyHash(
        hex_digest=h.hexdigest(),
        accepted_count=len(rows),
    )


__all__ = ["compute", "CanonicalPatchBodyHash"]
