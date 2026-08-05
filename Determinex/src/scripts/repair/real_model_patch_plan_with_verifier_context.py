"""Real model patch plan with verifier context.

Consumes a model-produced structured plan and quarantines it. The
verifier context (build_system_id, verifier argv) is recorded
alongside the quarantine result. No patch is applied. Layered on
top of the locked REAL_PATCH_PLAN_QUARANTINE_LOCK_001 validator —
this rung doesn't re-implement schema/path/op gates; it wraps them
so every accepted entry is traced back to the verifier context.
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
from models.real_local_model_healthcheck_record import (  # noqa: E402
    RealLocalModelHealthcheckRecord,
)

from .build_adapter_backed_verifier_selection_record import (
    BuildAdapterBackedVerifierSelectionRecord,
)
from .real_model_patch_plan_with_verifier_context_record import (
    REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_STATUS_TOKENS,
    RealModelPatchPlanWithVerifierContextRecord,
    RealPatchPlanContextEntry,
)
from .real_patch_plan_quarantine import quarantine as _inner_quarantine


def quarantine_with_verifier_context(
    *,
    healthcheck: RealLocalModelHealthcheckRecord | None,
    verifier_selection: BuildAdapterBackedVerifierSelectionRecord | None,
    workspace: Path | str,
    plan_entries: Sequence[dict],
    admission: RealLocalModelAdmissionRecord | None = None,
    opt_in: bool = False,
) -> RealModelPatchPlanWithVerifierContextRecord:
    """Quarantine a model-supplied plan with verifier context recorded.

    CLAUDE-AUTH-004 remediation: caller MUST supply a real admission
    record from REAL_LOCAL_MODEL_ADMISSION_LOCK_001.admit(). The
    healthcheck-derived synthesized admission shortcut is removed.
    """
    ws = str(Path(workspace).resolve()) if workspace else ""
    if healthcheck is None or not healthcheck.is_passed:
        return _blocked(
            "REAL_PATCH_PLAN_CONTEXT_BLOCKED_HEALTHCHECK",
            workspace=ws,
            model_id=getattr(healthcheck, "model_id", "") if healthcheck else "",
            provider=getattr(healthcheck, "provider", "") if healthcheck else "",
            build_system_id=getattr(verifier_selection, "build_system_id", "")
            if verifier_selection
            else "",
            verifier_argv=tuple(getattr(verifier_selection, "verifier_command", ()))
            if verifier_selection
            else (),
            note="healthcheck missing or not passed",
        )

    if verifier_selection is None or not verifier_selection.is_selected:
        return _blocked(
            "REAL_PATCH_PLAN_CONTEXT_BLOCKED_NO_VERIFIER",
            workspace=ws,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id="",
            verifier_argv=(),
            note="verifier selection missing or not selected",
        )

    if not opt_in:
        return _blocked(
            "REAL_PATCH_PLAN_CONTEXT_BLOCKED_NOT_OPTED_IN",
            workspace=ws,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id=verifier_selection.build_system_id,
            verifier_argv=verifier_selection.verifier_command,
            note="explicit opt_in=True is required",
        )

    # CLAUDE-AUTH-004 remediation: require a REAL admission record. The
    # previous synthesized-from-healthcheck shortcut bypassed the
    # stale-id / unpinned-id / task-class / detection / opt-in checks
    # baked into real_local_model_admission.admit().
    if admission is None or not admission.is_admitted:
        return _blocked(
            "REAL_PATCH_PLAN_CONTEXT_BLOCKED_MODEL_ADMISSION_REQUIRED",
            workspace=ws,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id=verifier_selection.build_system_id,
            verifier_argv=verifier_selection.verifier_command,
            note=(
                "no valid admission record supplied; "
                "REAL_LOCAL_MODEL_ADMISSION_LOCK_001.admit() must be "
                "called explicitly (synthesized admission is no longer "
                "accepted as of CLAUDE-AUTH-004 remediation)"
            ),
        )

    # Cross-check the admission's model_id/provider against the
    # healthcheck record so the admission cannot be reused across
    # disjoint sessions.
    if admission.model_id != healthcheck.model_id or admission.provider != healthcheck.provider:
        return _blocked(
            "REAL_PATCH_PLAN_CONTEXT_BLOCKED_MODEL_ADMISSION_REQUIRED",
            workspace=ws,
            model_id=healthcheck.model_id,
            provider=healthcheck.provider,
            build_system_id=verifier_selection.build_system_id,
            verifier_argv=verifier_selection.verifier_command,
            note=(
                f"admission model_id/provider ({admission.model_id!r},"
                f" {admission.provider!r}) does not match healthcheck "
                f"({healthcheck.model_id!r}, {healthcheck.provider!r})"
            ),
        )

    inner = _inner_quarantine(
        plan_entries,
        admission=admission,
        workspace=workspace,
        opt_in=True,
    )

    # Map the inner decision to this rung's namespace.
    inner_to_outer = {
        "REAL_PATCH_PLAN_QUARANTINED": "REAL_PATCH_PLAN_CONTEXT_QUARANTINED",
        "REAL_PATCH_PLAN_BLOCKED_SCHEMA_INVALID": "REAL_PATCH_PLAN_CONTEXT_BLOCKED_SCHEMA_INVALID",
        "REAL_PATCH_PLAN_BLOCKED_PATH_ESCAPE": "REAL_PATCH_PLAN_CONTEXT_BLOCKED_PATH_ESCAPE",
        "REAL_PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION": "REAL_PATCH_PLAN_CONTEXT_BLOCKED_UNSUPPORTED_OPERATION",
    }
    outer_decision = inner_to_outer.get(
        inner.decision, "REAL_PATCH_PLAN_CONTEXT_BLOCKED_SCHEMA_INVALID"
    )

    accepted = tuple(
        RealPatchPlanContextEntry(
            operation=e.operation,
            path=e.path,
            new_content_chars=e.new_content_chars,
        )
        for e in inner.accepted
    )
    rejected = tuple(
        RealPatchPlanContextEntry(
            operation=e.operation,
            path=e.path,
            new_content_chars=e.new_content_chars,
            rejection_reason=e.rejection_reason,
        )
        for e in inner.rejected
    )

    statuses_seen = [outer_decision, "REAL_PATCH_PLAN_CONTEXT_OUTPUT_UNTRUSTED"]
    notes = (
        "quarantine layered on REAL_PATCH_PLAN_QUARANTINE_LOCK_001",
        "verifier context recorded; no patch applied",
        "model output remains untrusted",
        "no source mutation; no training row",
    )

    return RealModelPatchPlanWithVerifierContextRecord(
        decision=outer_decision,
        workspace=ws,
        model_id=healthcheck.model_id,
        provider=healthcheck.provider,
        build_system_id=verifier_selection.build_system_id,
        verifier_command=verifier_selection.verifier_command,
        accepted=accepted,
        rejected=rejected,
        quarantined=(outer_decision == "REAL_PATCH_PLAN_CONTEXT_QUARANTINED"),
        output_trusted=False,
        patch_applied=False,
        source_mutation_authorized=False,
        training_eligible=False,
        statuses_seen=tuple(statuses_seen),
        notes=notes,
    )


def _blocked(
    decision: str,
    *,
    workspace: str,
    model_id: str,
    provider: str,
    build_system_id: str,
    verifier_argv: tuple[str, ...],
    note: str,
) -> RealModelPatchPlanWithVerifierContextRecord:
    return RealModelPatchPlanWithVerifierContextRecord(
        decision=decision,
        workspace=workspace,
        model_id=model_id,
        provider=provider,
        build_system_id=build_system_id,
        verifier_command=verifier_argv,
        accepted=tuple(),
        rejected=tuple(),
        quarantined=False,
        output_trusted=False,
        patch_applied=False,
        source_mutation_authorized=False,
        training_eligible=False,
        statuses_seen=(decision, "REAL_PATCH_PLAN_CONTEXT_OUTPUT_UNTRUSTED"),
        notes=(note,),
    )


__all__ = [
    "quarantine_with_verifier_context",
    "REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_STATUS_TOKENS",
    "RealModelPatchPlanWithVerifierContextRecord",
    "RealPatchPlanContextEntry",
]
