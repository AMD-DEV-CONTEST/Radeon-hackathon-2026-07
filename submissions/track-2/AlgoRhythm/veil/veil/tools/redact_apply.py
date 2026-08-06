"""Edit application — the Guardian's hands.

Edits are applied to text offsets, in reverse order so earlier offsets stay
valid, and every application returns a diff record for the audit log. There is
no in-place mutation anywhere: each iteration produces a new document version,
which is what makes the privacy/utility curve reconstructible after the fact.

For PDFs the output is regenerated from text rather than patched, because
patching a PDF is precisely the failure mode this project exists to attack.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veil.tools.registry import REGISTRY
from veil.types import Edit, EditType, Span, content_hash


@dataclass
class ApplyResult:
    text: str
    applied: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    version_hash: str


def _replacement_for(edit: Edit) -> str:
    if edit.edit_type is EditType.SUPPRESS:
        return "[REDACTED]"
    return edit.replacement


def apply_edits(text: str, edits: list[Edit]) -> ApplyResult:
    """Apply edits by offset, right-to-left, rejecting overlaps."""
    ordered = sorted(edits, key=lambda e: e.span.start, reverse=True)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    claimed: list[tuple[int, int]] = []
    out = text

    for edit in ordered:
        s, e = edit.span.start, edit.span.end
        if s < 0 or e > len(text) or s >= e:
            skipped.append({"finding_id": edit.finding_id, "reason": "span out of range"})
            continue
        if any(not (e <= cs or s >= ce) for cs, ce in claimed):
            skipped.append({"finding_id": edit.finding_id, "reason": "overlaps an earlier edit"})
            continue
        original = out[s:e]
        if original != edit.span.text:
            # The document moved under us — refuse rather than corrupt it.
            skipped.append(
                {
                    "finding_id": edit.finding_id,
                    "reason": f"span text mismatch (expected {edit.span.text!r}, found {original!r})",
                }
            )
            continue
        repl = _replacement_for(edit)
        out = out[:s] + repl + out[e:]
        claimed.append((s, e))
        applied.append(
            {
                "finding_id": edit.finding_id,
                "edit_type": edit.edit_type.value,
                "removed": original,
                "inserted": repl,
                "offset": s,
                "rationale": edit.rationale,
            }
        )

    return ApplyResult(out, list(reversed(applied)), skipped, content_hash(out))


@REGISTRY.register(
    name="redact_apply",
    description=(
        "Apply a proposed edit to the working document and return the result. "
        "Used by the Guardian to test whether an edit is well-formed before it "
        "is committed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Current document text."},
            "start": {"type": "integer"},
            "end": {"type": "integer"},
            "replacement": {"type": "string"},
            "edit_type": {
                "type": "string",
                "enum": ["suppress", "generalize", "pseudonymize", "restructure"],
            },
        },
        "required": ["text", "start", "end", "replacement", "edit_type"],
    },
)
def redact_apply(
    text: str, start: int, end: int, replacement: str, edit_type: str
) -> dict[str, Any]:
    edit = Edit(
        finding_id="preview",
        edit_type=EditType(edit_type),
        span=Span(start=start, end=end, text=text[start:end]),
        replacement=replacement,
        rationale="preview",
    )
    res = apply_edits(text, [edit])
    return {
        "ok": bool(res.applied),
        "preview": res.text[max(0, start - 120) : start + len(replacement) + 120],
        "skipped": res.skipped,
        "chars_removed": end - start,
        "chars_inserted": len(replacement),
    }
