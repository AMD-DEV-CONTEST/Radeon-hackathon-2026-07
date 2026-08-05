"""Canonical local model ID selection.

Combines:

  - the locked CURRENT_MODEL_IDS / STALE_MODEL_IDS sets from
    ``models.model_router``
  - the locked detection record from
    ``models.real_ollama_provider_detection``

to classify the current host into a single canonical-selection
decision. Never invokes a model. Never pulls. Never opens a network.
"""

from __future__ import annotations

from collections.abc import Iterable

from .canonical_local_model_id_selection_record import (
    CANONICAL_LOCAL_MODEL_ID_SELECTION_STATUS_TOKENS,
    CanonicalLocalModelIdSelectionRecord,
)
from .live_model_admission import _LOCAL_PROVIDERS, _NETWORK_PROVIDER_TOKENS
from .local_model_admission_policy import ModelProvider
from .model_router import CURRENT_MODEL_IDS, STALE_MODEL_IDS
from .real_ollama_provider_detection_record import (
    RealOllamaProviderDetectionRecord,
)


def select(
    *,
    detection: RealOllamaProviderDetectionRecord | None,
    preferred_model_id: str = "",
    provider: str = "ollama",
    candidate_overrides: Iterable[str] | None = None,
) -> CanonicalLocalModelIdSelectionRecord:
    """Decide which canonical model id (if any) is selectable on this host.

    ``preferred_model_id`` lets the caller prefer one canonical id over
    another; if empty we walk ``CURRENT_MODEL_IDS`` in sort order.
    ``candidate_overrides`` is only honored if every override is also
    in ``CURRENT_MODEL_IDS`` — it is a way for tests to inject a
    deterministic order without weakening the gate.
    """
    candidates = tuple(
        sorted(candidate_overrides if candidate_overrides is not None else CURRENT_MODEL_IDS)
    )
    # Refuse if any candidate isn't in CURRENT_MODEL_IDS — defense.
    if any(c not in CURRENT_MODEL_IDS for c in candidates):
        return _blocked(
            "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED",
            provider=provider,
            candidates=candidates,
            daemon_models=tuple(getattr(detection, "models", ()) or ()),
            host_state="UNPINNED_CANDIDATE_SUPPLIED",
            operator_action=("candidate_overrides included an id not in CURRENT_MODEL_IDS"),
            note="reject unpinned override",
        )

    # 1. Network provider hard refusal.
    if provider in _NETWORK_PROVIDER_TOKENS:
        return _blocked(
            "CANONICAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER",
            provider=provider,
            candidates=candidates,
            daemon_models=tuple(getattr(detection, "models", ()) or ()),
            host_state="NETWORK_PROVIDER",
            operator_action=(
                "pick a local provider (no_model, ollama, local_hf, executable_adapter)"
            ),
            note=f"provider {provider!r} is a network provider",
        )

    # 2. Stale preferred id.
    if preferred_model_id and preferred_model_id in STALE_MODEL_IDS:
        return _blocked(
            "CANONICAL_LOCAL_MODEL_BLOCKED_STALE_ID",
            provider=provider,
            candidates=candidates,
            daemon_models=tuple(getattr(detection, "models", ()) or ()),
            host_state="PREFERRED_STALE",
            operator_action=(
                f"preferred_model_id={preferred_model_id!r} is stale; pick from CURRENT_MODEL_IDS"
            ),
            note="preferred id stale",
        )

    # 3. Unpinned preferred id.
    if preferred_model_id and preferred_model_id not in CURRENT_MODEL_IDS:
        return _blocked(
            "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED",
            provider=provider,
            candidates=candidates,
            daemon_models=tuple(getattr(detection, "models", ()) or ()),
            host_state="PREFERRED_UNPINNED",
            operator_action=(
                f"preferred_model_id={preferred_model_id!r} not in "
                "CURRENT_MODEL_IDS; pick a canonical id"
            ),
            note="preferred id unpinned",
        )

    # 4. Provider must be in the local set; ollama needs DETECTED.
    if provider not in _LOCAL_PROVIDERS or provider == ModelProvider.NO_MODEL.value:
        return _blocked(
            "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE",
            provider=provider,
            candidates=candidates,
            daemon_models=tuple(getattr(detection, "models", ()) or ()),
            host_state="PROVIDER_NOT_RECOGNIZED",
            operator_action="pick provider in {ollama, local_hf, executable_adapter}",
            note=f"provider {provider!r} not a real local model provider",
        )

    if provider == ModelProvider.OLLAMA.value:
        if detection is None or not detection.is_detected:
            return _blocked(
                "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE",
                provider=provider,
                candidates=candidates,
                daemon_models=tuple(getattr(detection, "models", ()) or ()),
                host_state="PROVIDER_NOT_RUNNING",
                operator_action=(
                    "start the Ollama daemon (`ollama serve`) and re-run "
                    "REAL_OLLAMA_PROVIDER_DETECTION_LOCK_001 detect()"
                ),
                note="ollama detection record missing or not DETECTED",
            )

    # 5. Pick the canonical id we'll try.
    if preferred_model_id:
        chosen = preferred_model_id
    else:
        chosen = candidates[0] if candidates else ""

    daemon_models = tuple(getattr(detection, "models", ()) or ())
    if not chosen:
        return _blocked(
            "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED",
            provider=provider,
            candidates=candidates,
            daemon_models=daemon_models,
            host_state="NO_CANDIDATE",
            operator_action="add canonical ids to CURRENT_MODEL_IDS",
            note="no candidate id available",
        )

    # 6. Is the chosen id actually pulled into the local provider?
    # The detection record's ``models`` is best available signal for
    # ollama; we tolerate the bare and ``:tag`` forms.
    pulled = False
    daemon_lc = {m.lower() for m in daemon_models}
    base = chosen.lower()
    for m in daemon_lc:
        if m == base or m.startswith(base + ":"):
            pulled = True
            break

    if provider == ModelProvider.OLLAMA.value and not pulled:
        return _blocked(
            "CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED",
            provider=provider,
            candidates=candidates,
            daemon_models=daemon_models,
            host_state="MODEL_NOT_PULLED",
            operator_action=(
                f"run `ollama pull {chosen}` to install the canonical model. "
                "Then re-run CANONICAL_LOCAL_MODEL_ID_SELECTION_LOCK_001 "
                "select()."
            ),
            note=f"{chosen!r} not present in ollama daemon model list",
        )

    return CanonicalLocalModelIdSelectionRecord(
        decision="CANONICAL_LOCAL_MODEL_SELECTED",
        selected_model_id=chosen,
        provider=provider,
        candidate_model_ids=candidates,
        daemon_models_available=daemon_models,
        host_state="MODEL_AVAILABLE",
        operator_action="",
        network_provider_admitted=False,
        live_model_called=False,
        notes=(
            f"selected canonical id {chosen!r}",
            "no live model call performed here",
            "downstream admission gates still required",
        ),
    )


def _blocked(
    decision: str,
    *,
    provider: str,
    candidates: tuple[str, ...],
    daemon_models: tuple[str, ...],
    host_state: str,
    operator_action: str,
    note: str,
) -> CanonicalLocalModelIdSelectionRecord:
    return CanonicalLocalModelIdSelectionRecord(
        decision=decision,
        selected_model_id="",
        provider=provider,
        candidate_model_ids=candidates,
        daemon_models_available=daemon_models,
        host_state=host_state,
        operator_action=operator_action,
        network_provider_admitted=False,
        live_model_called=False,
        notes=(note,),
    )


__all__ = [
    "select",
    "CANONICAL_LOCAL_MODEL_ID_SELECTION_STATUS_TOKENS",
    "CanonicalLocalModelIdSelectionRecord",
]
