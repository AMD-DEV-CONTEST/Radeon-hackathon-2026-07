"""Live patch-plan quarantine.

Accepts a structured patch plan produced by a live (or fixture) model,
validates each entry, and stores the result as a quarantined,
untrusted record. No patch is applied — not to source, not even to a
temp workspace at this rung. The temp-patch verifier gate is rung 5.

Validated entry shape::

    {"operation": "replace_file", "path": "src/x.py", "new_content": "..."}

Only ``replace_file`` is supported. Path traversal, symlink-friendly
paths, binary content, and oversized entries are rejected with
specific status tokens.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.live_model_admission_record import LiveModelAdmissionRecord  # noqa: E402

from .live_patch_plan_record import (
    LIVE_PATCH_PLAN_STATUS_TOKENS,
    PatchOp,
    QuarantinedPatchEntry,
    QuarantinedPatchPlan,
    supported_operations,
)

_MAX_ENTRY_BYTES = 2_000_000  # 2 MB per file
_MAX_TOTAL_BYTES = 16_000_000  # 16 MB across all entries


def _normalize_rel(p: str) -> tuple[str, str]:
    if not p:
        return "", "empty path"
    raw = p.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("//") or ":" in raw.split("/")[0]:
        return "", "absolute or drive-anchored"
    parts = [seg for seg in raw.split("/") if seg]
    for seg in parts:
        if seg == "..":
            return "", "contains '..'"
    if not parts:
        return "", "empty after normalization"
    return "/".join(parts), ""


def _is_binary_text(s: str) -> bool:
    return "\x00" in s


def _preview(s: str, n: int = 200) -> str:
    return s[:n]


class LivePatchPlanQuarantine:
    """Stateless quarantine. Same inputs → same record."""

    def quarantine(
        self,
        plan_entries: Sequence[dict[str, object]],
        *,
        admission: LiveModelAdmissionRecord,
        workspace: Path,
        provider_name: str = "",
        model_id: str = "",
    ) -> QuarantinedPatchPlan:
        ws = Path(workspace).resolve()
        admission_ref = admission.decision

        # 1. Admission must be READY.
        if not admission.is_ready or not admission.live_call_authorized:
            return self._blocked(
                "PATCH_PLAN_BLOCKED_MODEL_NOT_ADMITTED",
                admission_ref=admission_ref,
                provider=provider_name,
                model_id=model_id,
                workspace=str(ws),
                note=f"admission decision={admission.decision} "
                f"live_call_authorized={admission.live_call_authorized}",
            )

        # 2. Validate each entry.
        accepted: list[QuarantinedPatchEntry] = []
        rejected: list[QuarantinedPatchEntry] = []
        total_bytes = 0

        for raw in plan_entries:
            if not isinstance(raw, dict):
                rejected.append(
                    QuarantinedPatchEntry(
                        operation="?",
                        path="?",
                        new_content_chars=0,
                        new_content_preview="",
                        rejected_reason="entry is not a dict",
                    )
                )
                return self._blocked(
                    "PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
                    admission_ref=admission_ref,
                    provider=provider_name,
                    model_id=model_id,
                    workspace=str(ws),
                    rejected=rejected,
                    note="entry not a dict",
                )

            op = str(raw.get("operation", ""))
            path = str(raw.get("path", ""))
            new_content = str(raw.get("new_content", ""))
            entry_chars = len(new_content)
            entry_preview = _preview(new_content)

            # 2a. Unsupported operation.
            if op not in supported_operations():
                rejected.append(
                    QuarantinedPatchEntry(
                        operation=op,
                        path=path,
                        new_content_chars=entry_chars,
                        new_content_preview=entry_preview,
                        rejected_reason=f"unsupported operation {op!r}",
                    )
                )
                return self._blocked(
                    "PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION",
                    admission_ref=admission_ref,
                    provider=provider_name,
                    model_id=model_id,
                    workspace=str(ws),
                    rejected=rejected,
                    note=f"unsupported operation {op!r}",
                )

            # 2b. Path validation.
            cleaned, reason = _normalize_rel(path)
            if reason:
                rejected.append(
                    QuarantinedPatchEntry(
                        operation=op,
                        path=path,
                        new_content_chars=entry_chars,
                        new_content_preview=entry_preview,
                        rejected_reason=f"path escape: {reason}",
                    )
                )
                return self._blocked(
                    "PATCH_PLAN_BLOCKED_PATH_ESCAPE",
                    admission_ref=admission_ref,
                    provider=provider_name,
                    model_id=model_id,
                    workspace=str(ws),
                    rejected=rejected,
                    note=f"path escape {path!r}: {reason}",
                )

            # 2c. Binary content.
            if _is_binary_text(new_content):
                rejected.append(
                    QuarantinedPatchEntry(
                        operation=op,
                        path=cleaned,
                        new_content_chars=entry_chars,
                        new_content_preview=entry_preview,
                        rejected_reason="NUL byte in content",
                    )
                )
                return self._blocked(
                    "PATCH_PLAN_BLOCKED_BINARY_CONTENT",
                    admission_ref=admission_ref,
                    provider=provider_name,
                    model_id=model_id,
                    workspace=str(ws),
                    rejected=rejected,
                    note="binary content rejected",
                )

            # 2d. Per-entry size.
            entry_bytes = len(new_content.encode("utf-8"))
            if entry_bytes > _MAX_ENTRY_BYTES:
                rejected.append(
                    QuarantinedPatchEntry(
                        operation=op,
                        path=cleaned,
                        new_content_chars=entry_chars,
                        new_content_preview=entry_preview,
                        rejected_reason=f"entry > {_MAX_ENTRY_BYTES} bytes",
                    )
                )
                return self._blocked(
                    "PATCH_PLAN_BLOCKED_OVERSIZED",
                    admission_ref=admission_ref,
                    provider=provider_name,
                    model_id=model_id,
                    workspace=str(ws),
                    rejected=rejected,
                    note="entry oversized",
                )

            total_bytes += entry_bytes
            if total_bytes > _MAX_TOTAL_BYTES:
                rejected.append(
                    QuarantinedPatchEntry(
                        operation=op,
                        path=cleaned,
                        new_content_chars=entry_chars,
                        new_content_preview=entry_preview,
                        rejected_reason=f"total > {_MAX_TOTAL_BYTES} bytes",
                    )
                )
                return self._blocked(
                    "PATCH_PLAN_BLOCKED_OVERSIZED",
                    admission_ref=admission_ref,
                    provider=provider_name,
                    model_id=model_id,
                    workspace=str(ws),
                    rejected=rejected,
                    note="cumulative oversized",
                )

            accepted.append(
                QuarantinedPatchEntry(
                    operation=op,
                    path=cleaned,
                    new_content_chars=entry_chars,
                    new_content_preview=entry_preview,
                )
            )

        if not accepted:
            return self._blocked(
                "PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
                admission_ref=admission_ref,
                provider=provider_name,
                model_id=model_id,
                workspace=str(ws),
                note="empty plan",
            )

        return QuarantinedPatchPlan(
            decision="PATCH_PLAN_QUARANTINED",
            admission_decision_ref=admission_ref,
            provider=provider_name,
            model_id=model_id,
            workspace=str(ws),
            entries=tuple(accepted),
            rejected_entries=tuple(rejected),
            trusted=False,
            applied_to_source=False,
            applied_to_temp_workspace=False,
            source_mutation_authorized=False,
            corpus_write_authorized=False,
            training_eligible=False,
            notes=(f"{len(accepted)} entry(ies) quarantined, untrusted",),
        )

    @staticmethod
    def _blocked(
        decision: str,
        *,
        admission_ref: str,
        provider: str,
        model_id: str,
        workspace: str,
        note: str,
        rejected: Iterable[QuarantinedPatchEntry] = (),
    ) -> QuarantinedPatchPlan:
        return QuarantinedPatchPlan(
            decision=decision,
            admission_decision_ref=admission_ref,
            provider=provider,
            model_id=model_id,
            workspace=workspace,
            entries=(),
            rejected_entries=tuple(rejected),
            trusted=False,
            applied_to_source=False,
            applied_to_temp_workspace=False,
            source_mutation_authorized=False,
            corpus_write_authorized=False,
            training_eligible=False,
            notes=(note,),
        )


__all__ = [
    "LivePatchPlanQuarantine",
    "QuarantinedPatchPlan",
    "QuarantinedPatchEntry",
    "LIVE_PATCH_PLAN_STATUS_TOKENS",
    "PatchOp",
]
