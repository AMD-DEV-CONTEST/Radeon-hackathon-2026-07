"""Real local-model admission gate.

Admits exactly one real local model for a set of task classes only when
all of these hold:

  - a real Ollama provider has been DETECTED (or another local provider
    is explicitly admitted by the caller via a detection record)
  - the provider is one of the locked local set (no_model is rejected
    here because the rung is about admitting a real model)
  - the model id is in CURRENT_MODEL_IDS
  - the model id is NOT in STALE_MODEL_IDS
  - every requested task class is in the supported set
  - the caller passed opt_in=True

The admission record itself never calls the model. It is a pure
decision surface; inference still has to ride the verifier/temp/
approval gates.
"""

from __future__ import annotations

from collections.abc import Iterable

from .live_model_admission import _LOCAL_PROVIDERS, _NETWORK_PROVIDER_TOKENS
from .local_model_admission_policy import ModelProvider
from .model_router import CURRENT_MODEL_IDS, STALE_MODEL_IDS, TaskClass
from .real_local_model_admission_record import (
    REAL_LOCAL_MODEL_ADMISSION_STATUS_TOKENS,
    RealLocalModelAdmissionRecord,
)
from .real_ollama_provider_detection_record import (
    RealOllamaProviderDetectionRecord,
)


def _supported_task_classes() -> frozenset[str]:
    return frozenset(t.value for t in TaskClass if t is not TaskClass.UNKNOWN)


def admit(
    *,
    detection: RealOllamaProviderDetectionRecord | None,
    provider: str,
    model_id: str,
    task_classes: Iterable[str],
    opt_in: bool = False,
) -> RealLocalModelAdmissionRecord:
    """Decide whether one real local model is admitted.

    The decision is structured so that the caller can replay the same
    inputs and re-derive the same outcome.
    """
    task_classes_t = tuple(t for t in task_classes if t)

    # 1. Network providers refused outright.
    if provider in _NETWORK_PROVIDER_TOKENS:
        return _blocked(
            "REAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER",
            provider,
            model_id,
            task_classes_t,
            f"provider {provider!r} is a network provider",
            detection,
        )

    # 2. Provider must be in the local set AND not no_model (the rung
    # exists to admit a real model).
    if provider == ModelProvider.NO_MODEL.value:
        return _blocked(
            "REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER",
            provider,
            model_id,
            task_classes_t,
            "no_model cannot satisfy real local admission",
            detection,
        )
    if provider not in _LOCAL_PROVIDERS:
        return _blocked(
            "REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER",
            provider,
            model_id,
            task_classes_t,
            f"provider {provider!r} is not a recognized local provider",
            detection,
        )

    # 3. Stale id.
    if model_id in STALE_MODEL_IDS:
        return _blocked(
            "REAL_LOCAL_MODEL_BLOCKED_STALE",
            provider,
            model_id,
            task_classes_t,
            f"model_id {model_id!r} is stale",
            detection,
        )

    # 4. Unpinned id.
    if model_id not in CURRENT_MODEL_IDS:
        return _blocked(
            "REAL_LOCAL_MODEL_BLOCKED_UNPINNED",
            provider,
            model_id,
            task_classes_t,
            f"model_id {model_id!r} not pinned in CURRENT_MODEL_IDS",
            detection,
        )

    # 5. Task class compatibility.
    supported = _supported_task_classes()
    if not task_classes_t or any(t not in supported for t in task_classes_t):
        return _blocked(
            "REAL_LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS",
            provider,
            model_id,
            task_classes_t,
            "one or more task classes are unsupported",
            detection,
        )

    # 6. Provider detection. If the caller is asking us to admit an
    # Ollama-backed model and the detection record does NOT report
    # DETECTED, refuse — we will not pretend the daemon is up.
    if provider == ModelProvider.OLLAMA.value:
        if detection is None or not detection.is_detected:
            return _blocked(
                "REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER",
                provider,
                model_id,
                task_classes_t,
                "ollama provider not detected; pass a DETECTED record to admit",
                detection,
            )

    # 7. Explicit opt-in required.
    if not opt_in:
        return _blocked(
            "REAL_LOCAL_MODEL_BLOCKED_NOT_OPTED_IN",
            provider,
            model_id,
            task_classes_t,
            "explicit opt_in=True is required for real admission",
            detection,
        )

    return RealLocalModelAdmissionRecord(
        decision="REAL_LOCAL_MODEL_ADMITTED",
        provider=provider,
        model_id=model_id,
        task_classes_admitted=task_classes_t,
        dry_run_default=True,
        opt_in=True,
        source_mutation_authorized=False,
        training_eligible=False,
        network_provider_admitted=False,
        provider_detection_decision=getattr(detection, "decision", ""),
        notes=(
            "admitted for real inference under explicit opt_in",
            "source mutation still BLOCKED pending approval gates",
            "training eligibility still BLOCKED by default",
        ),
    )


def _blocked(
    decision: str,
    provider: str,
    model_id: str,
    task_classes: tuple[str, ...],
    reason: str,
    detection: RealOllamaProviderDetectionRecord | None,
) -> RealLocalModelAdmissionRecord:
    return RealLocalModelAdmissionRecord(
        decision=decision,
        provider=provider,
        model_id=model_id,
        task_classes_admitted=task_classes,
        dry_run_default=True,
        opt_in=False,
        source_mutation_authorized=False,
        training_eligible=False,
        network_provider_admitted=False,
        provider_detection_decision=getattr(detection, "decision", ""),
        notes=(reason,),
    )


__all__ = [
    "admit",
    "RealLocalModelAdmissionRecord",
    "REAL_LOCAL_MODEL_ADMISSION_STATUS_TOKENS",
]
