"""Diagnose-only trace runner.

Permits a live/local or fixture model to participate in diagnosis
only. Task classes admitted: BUILD_DIAGNOSIS, TEST_FAILURE_LOCALIZATION.
The response is captured as advisory; the verifier remains the source
of truth. No patch is generated. No source mutation. No corpus row.
No training eligibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from models.live_model_admission_record import LiveModelAdmissionRecord  # noqa: E402
from models.live_model_compat_harness import FixtureProvider, LiveModelCompatHarness  # noqa: E402
from models.live_model_response_record import LiveModelResponse  # noqa: E402

from .live_diagnose_trace_record import (
    LIVE_DIAGNOSE_STATUS_TOKENS,
    LiveDiagnoseTrace,
    allowed_task_classes,
)


class LiveDiagnoseTraceRunner:
    """Stateless runner. Same inputs → same trace."""

    def __init__(self, harness: LiveModelCompatHarness | None = None) -> None:
        self._harness = harness or LiveModelCompatHarness()

    def run(
        self,
        workspace: Path,
        *,
        task_class: str,
        admission: LiveModelAdmissionRecord,
        provider: FixtureProvider,
        payload: dict[str, object] | None = None,
        schema_id: str = "diagnose_v1",
    ) -> LiveDiagnoseTrace:
        ws = Path(workspace).resolve()
        admission_ref = admission.decision

        # 1. Task class must be in the diagnose-only allowed set.
        if task_class not in allowed_task_classes():
            return self._blocked(
                workspace=str(ws),
                task_class=task_class,
                admission_ref=admission_ref,
                provider=provider.name,
                model_id=provider.model_id,
                decision="LIVE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
                note=f"task_class {task_class!r} not in {sorted(allowed_task_classes())}",
            )

        # 2. Admission must be READY with live_call_authorized=True.
        if not admission.is_ready or not admission.live_call_authorized:
            return self._blocked(
                workspace=str(ws),
                task_class=task_class,
                admission_ref=admission_ref,
                provider=provider.name,
                model_id=provider.model_id,
                decision="LIVE_DIAGNOSE_BLOCKED_MODEL_NOT_ADMITTED",
                note=f"admission decision={admission.decision} "
                f"live_call_authorized={admission.live_call_authorized}",
            )

        # 3. Invoke harness against the provider (fixture only).
        response: LiveModelResponse = self._harness.invoke(
            provider,
            task_class=task_class,
            schema_id=schema_id,
            payload=payload,
        )

        if response.is_blocked:
            return self._blocked(
                workspace=str(ws),
                task_class=task_class,
                admission_ref=admission_ref,
                provider=provider.name,
                model_id=provider.model_id,
                decision="LIVE_DIAGNOSE_BLOCKED_PROVIDER_REJECTED",
                response_status=response.status,
                note=f"harness blocked: {response.status}",
            )

        statuses_seen = (
            "LIVE_DIAGNOSE_TRACE_WRITTEN",
            "LIVE_DIAGNOSE_RESPONSE_CAPTURED_ADVISORY_ONLY",
            "LIVE_DIAGNOSE_NO_SOURCE_MUTATION",
        )
        return LiveDiagnoseTrace(
            decision="LIVE_DIAGNOSE_TRACE_WRITTEN",
            workspace=str(ws),
            task_class=task_class,
            admission_decision_ref=admission_ref,
            provider=provider.name,
            model_id=provider.model_id,
            response_status=response.status,
            advisory_payload=dict(response.payload),
            advisory_only=True,
            patch_generated=False,
            source_mutation_authorized=False,
            corpus_write_authorized=False,
            training_eligible=False,
            statuses_seen=statuses_seen,
            notes=("response captured as advisory; verifier remains source of truth",),
        )

    @staticmethod
    def _blocked(
        *,
        workspace: str,
        task_class: str,
        admission_ref: str,
        provider: str,
        model_id: str,
        decision: str,
        note: str,
        response_status: str = "",
    ) -> LiveDiagnoseTrace:
        return LiveDiagnoseTrace(
            decision=decision,
            workspace=workspace,
            task_class=task_class,
            admission_decision_ref=admission_ref,
            provider=provider,
            model_id=model_id,
            response_status=response_status,
            advisory_payload={},
            advisory_only=True,
            patch_generated=False,
            source_mutation_authorized=False,
            corpus_write_authorized=False,
            training_eligible=False,
            statuses_seen=(decision,),
            notes=(note,),
        )


__all__ = [
    "LiveDiagnoseTraceRunner",
    "LiveDiagnoseTrace",
    "LIVE_DIAGNOSE_STATUS_TOKENS",
    "allowed_task_classes",
]
