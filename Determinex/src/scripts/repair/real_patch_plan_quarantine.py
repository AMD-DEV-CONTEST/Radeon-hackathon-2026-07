"""Real patch-plan quarantine.

Accepts a structured patch plan from a real-admitted local model and
records it as quarantined / untrusted. No patch is applied — not to
the original source, not to a temp workspace at this rung.

Hard refusals (per-entry rejections accumulate into the rejected
list; the overall decision flips to BLOCKED_* when no entry survives):

  - schema_invalid: missing/typed-wrong required keys
  - path_escape: absolute paths, drive-anchored, '..' segments,
    backslashes, NUL bytes
  - unsupported_operation: anything other than replace_file
  - oversize content / oversize total (bounded entry/total bytes)

Overall decisions:

  - REAL_PATCH_PLAN_QUARANTINED — at least one entry validated; whole
    plan is quarantined as untrusted
  - REAL_PATCH_PLAN_BLOCKED_NO_MODEL — admission missing/not admitted
  - REAL_PATCH_PLAN_BLOCKED_NOT_OPTED_IN
  - REAL_PATCH_PLAN_BLOCKED_SCHEMA_INVALID — all entries failed schema
  - REAL_PATCH_PLAN_BLOCKED_PATH_ESCAPE — all entries failed path
  - REAL_PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION — all entries failed op

Pure validation. No filesystem write at this rung.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.real_local_model_admission_record import (  # noqa: E402
    RealLocalModelAdmissionRecord,
)

from .real_patch_plan_quarantine_record import (
    REAL_PATCH_PLAN_QUARANTINE_STATUS_TOKENS,
    RealPatchPlanQuarantineRecord,
    RealQuarantinedPatchEntry,
)

_SUPPORTED_OPERATIONS: frozenset[str] = frozenset({"replace_file"})
_MAX_ENTRY_BYTES = 2_000_000
_MAX_TOTAL_BYTES = 16_000_000


def _normalize_rel(p: str) -> tuple[str, str]:
    if not isinstance(p, str) or not p:
        return "", "empty path"
    if "\x00" in p:
        return "", "NUL byte in path"
    raw = p.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("//"):
        return "", "absolute path"
    first = raw.split("/")[0]
    if ":" in first:
        return "", "drive-anchored path"
    parts = [seg for seg in raw.split("/") if seg]
    for seg in parts:
        if seg == "..":
            return "", "contains '..'"
    if not parts:
        return "", "empty after normalization"
    return "/".join(parts), ""


def quarantine(
    plan_entries: Sequence[dict[str, object]],
    *,
    admission: RealLocalModelAdmissionRecord | None,
    workspace: Path | str,
    opt_in: bool = False,
) -> RealPatchPlanQuarantineRecord:
    """Validate a model-supplied plan; record quarantined / blocked."""
    ws = str(Path(workspace).resolve()) if workspace else ""

    if admission is None or not admission.is_admitted:
        return _blocked(
            "REAL_PATCH_PLAN_BLOCKED_NO_MODEL",
            workspace=ws,
            model_id=getattr(admission, "model_id", ""),
            provider=getattr(admission, "provider", ""),
            reason="admission missing or not admitted",
        )

    if not opt_in:
        return _blocked(
            "REAL_PATCH_PLAN_BLOCKED_NOT_OPTED_IN",
            workspace=ws,
            model_id=admission.model_id,
            provider=admission.provider,
            reason="explicit opt_in=True is required",
        )

    accepted: list[RealQuarantinedPatchEntry] = []
    rejected: list[RealQuarantinedPatchEntry] = []
    total_bytes = 0
    rejection_kinds: set[str] = set()

    for raw in plan_entries:
        if not isinstance(raw, dict):
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation="?",
                    path="?",
                    new_content_chars=0,
                    rejection_reason="entry is not a dict",
                )
            )
            rejection_kinds.add("schema")
            continue

        op = raw.get("operation")
        path_raw = raw.get("path")
        content = raw.get("new_content")

        if not isinstance(op, str) or not op:
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation="?",
                    path=str(path_raw or "?"),
                    new_content_chars=0,
                    rejection_reason="missing operation",
                )
            )
            rejection_kinds.add("schema")
            continue
        if op not in _SUPPORTED_OPERATIONS:
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation=op,
                    path=str(path_raw or "?"),
                    new_content_chars=0,
                    rejection_reason=f"unsupported operation {op!r}",
                )
            )
            rejection_kinds.add("unsupported_operation")
            continue

        if not isinstance(path_raw, str):
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation=op,
                    path=str(path_raw),
                    new_content_chars=0,
                    rejection_reason="path is not a string",
                )
            )
            rejection_kinds.add("schema")
            continue

        norm, err = _normalize_rel(path_raw)
        if not norm:
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation=op,
                    path=path_raw,
                    new_content_chars=0,
                    rejection_reason=f"path: {err}",
                )
            )
            rejection_kinds.add("path_escape")
            continue

        if not isinstance(content, str):
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation=op,
                    path=norm,
                    new_content_chars=0,
                    rejection_reason="new_content not a string",
                )
            )
            rejection_kinds.add("schema")
            continue

        if "\x00" in content:
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation=op,
                    path=norm,
                    new_content_chars=len(content),
                    rejection_reason="binary content (NUL byte)",
                )
            )
            rejection_kinds.add("schema")
            continue

        nbytes = len(content.encode("utf-8"))
        if nbytes > _MAX_ENTRY_BYTES:
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation=op,
                    path=norm,
                    new_content_chars=len(content),
                    rejection_reason=f"entry exceeds {_MAX_ENTRY_BYTES} bytes",
                )
            )
            rejection_kinds.add("schema")
            continue
        if total_bytes + nbytes > _MAX_TOTAL_BYTES:
            rejected.append(
                RealQuarantinedPatchEntry(
                    operation=op,
                    path=norm,
                    new_content_chars=len(content),
                    rejection_reason=f"plan exceeds {_MAX_TOTAL_BYTES} bytes",
                )
            )
            rejection_kinds.add("schema")
            continue

        total_bytes += nbytes
        accepted.append(
            RealQuarantinedPatchEntry(
                operation=op,
                path=norm,
                new_content_chars=len(content),
                rejection_reason="",
            )
        )

    if accepted:
        return RealPatchPlanQuarantineRecord(
            decision="REAL_PATCH_PLAN_QUARANTINED",
            workspace=ws,
            model_id=admission.model_id,
            provider=admission.provider,
            accepted=tuple(accepted),
            rejected=tuple(rejected),
            quarantined=True,
            output_trusted=False,
            patch_applied=False,
            source_mutation_authorized=False,
            training_eligible=False,
            notes=(
                "plan quarantined as untrusted",
                "no patch applied at this rung",
                "temp-patch verifier is the next rung",
            ),
        )

    # No survivors. Pick the dominant rejection kind for the overall
    # decision; ties favor stricter codes.
    if "path_escape" in rejection_kinds:
        decision = "REAL_PATCH_PLAN_BLOCKED_PATH_ESCAPE"
    elif "unsupported_operation" in rejection_kinds:
        decision = "REAL_PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION"
    else:
        decision = "REAL_PATCH_PLAN_BLOCKED_SCHEMA_INVALID"

    return RealPatchPlanQuarantineRecord(
        decision=decision,
        workspace=ws,
        model_id=admission.model_id,
        provider=admission.provider,
        accepted=tuple(),
        rejected=tuple(rejected),
        quarantined=False,
        output_trusted=False,
        patch_applied=False,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=("all entries rejected; nothing quarantined",),
    )


def _blocked(
    decision: str,
    *,
    workspace: str,
    model_id: str,
    provider: str,
    reason: str,
) -> RealPatchPlanQuarantineRecord:
    return RealPatchPlanQuarantineRecord(
        decision=decision,
        workspace=workspace,
        model_id=model_id,
        provider=provider,
        accepted=tuple(),
        rejected=tuple(),
        quarantined=False,
        output_trusted=False,
        patch_applied=False,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(reason,),
    )


__all__ = [
    "quarantine",
    "REAL_PATCH_PLAN_QUARANTINE_STATUS_TOKENS",
    "RealPatchPlanQuarantineRecord",
    "RealQuarantinedPatchEntry",
]
