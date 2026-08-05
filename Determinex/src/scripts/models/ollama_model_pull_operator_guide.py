"""Ollama model-pull operator guide.

If the canonical local model id is not pulled, produce a record
containing the EXACT command an operator should run, plus safety
warnings and the next validation command. This lock DOES NOT
PULL the model — that is intentional. Auto-pull is left for a
later, separately-locked rung when local policy explicitly
opt-in's to autopull.
"""

from __future__ import annotations

import re

from .canonical_local_model_id_selection_record import (
    CanonicalLocalModelIdSelectionRecord,
)
from .ollama_model_pull_operator_guide_record import (
    OLLAMA_MODEL_PULL_OPERATOR_GUIDE_STATUS_TOKENS,
    OllamaModelPullOperatorGuideRecord,
)

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9._:-]+$")


_SAFETY_WARNING = (
    "Running `ollama pull` downloads a model file from a model registry. "
    "Do this only on the operator's own development host. The downloaded "
    "blob is treated as untrusted by Determinex; admission, healthcheck, "
    "patch-plan quarantine, temp verifier, and real human approval still "
    "apply before any source mutation. Determinex will NOT auto-pull."
)


def guide(
    *,
    selection: CanonicalLocalModelIdSelectionRecord | None,
) -> OllamaModelPullOperatorGuideRecord:
    if selection is None:
        return _blocked(
            "OPERATOR_GUIDE_BLOCKED_PROVIDER_UNAVAILABLE",
            model_id="",
            provider="",
            selection_decision="",
            selection_host_state="",
            note="selection record missing",
        )

    if selection.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER":
        return _blocked(
            "OPERATOR_GUIDE_BLOCKED_NETWORK_PROVIDER",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            selection_decision=selection.decision,
            selection_host_state=selection.host_state,
            note="network provider blocked at selection",
        )

    if selection.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_STALE_ID":
        return _blocked(
            "OPERATOR_GUIDE_BLOCKED_STALE_ID",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            selection_decision=selection.decision,
            selection_host_state=selection.host_state,
            note="selection refused a stale id; no pull guide for stale ids",
        )

    if selection.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_UNPINNED":
        return _blocked(
            "OPERATOR_GUIDE_BLOCKED_UNPINNED",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            selection_decision=selection.decision,
            selection_host_state=selection.host_state,
            note="selection refused an unpinned id; no pull guide for unpinned ids",
        )

    if selection.decision == "CANONICAL_LOCAL_MODEL_BLOCKED_PROVIDER_UNAVAILABLE":
        return _blocked(
            "OPERATOR_GUIDE_BLOCKED_PROVIDER_UNAVAILABLE",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            selection_decision=selection.decision,
            selection_host_state=selection.host_state,
            note=(
                "provider not available; operator must start the local "
                "provider before a pull is meaningful"
            ),
        )

    if selection.decision == "CANONICAL_LOCAL_MODEL_SELECTED":
        return OllamaModelPullOperatorGuideRecord(
            decision="OPERATOR_GUIDE_NOT_NEEDED_MODEL_AVAILABLE",
            model_id=selection.selected_model_id,
            provider=selection.provider,
            expected_command="",
            safety_warning="",
            next_validation_command="",
            selection_decision=selection.decision,
            selection_host_state=selection.host_state,
            network_provider_admitted=False,
            auto_pull_performed=False,
            training_eligibility_opened=False,
            notes=(
                "model already pulled per selection",
                "no operator action required",
            ),
        )

    # Remaining case: CANONICAL_LOCAL_MODEL_BLOCKED_NOT_PULLED.
    # The selection already proposed a `selected_model_id` in its
    # `operator_action`; we re-derive the id from `candidate_model_ids`
    # because the selected_model_id field is intentionally empty on
    # the blocked path.
    candidate = selection.candidate_model_ids[0] if selection.candidate_model_ids else ""
    # Defensive ID safety check: refuse to emit a guide for anything
    # that doesn't look like a plain ollama tag.
    if not candidate or not _SAFE_ID_RE.match(candidate):
        return _blocked(
            "OPERATOR_GUIDE_BLOCKED_UNPINNED",
            model_id=candidate,
            provider=selection.provider,
            selection_decision=selection.decision,
            selection_host_state=selection.host_state,
            note="canonical candidate id is empty or malformed",
        )

    return OllamaModelPullOperatorGuideRecord(
        decision="OPERATOR_GUIDE_WRITTEN",
        model_id=candidate,
        provider=selection.provider,
        expected_command=f"ollama pull {candidate}",
        safety_warning=_SAFETY_WARNING,
        next_validation_command=(
            "python -m pytest tests/models/"
            "test_canonical_local_model_id_selection_lock.py "
            "tests/models/test_real_local_model_healthcheck_lock.py -q --tb=short"
        ),
        selection_decision=selection.decision,
        selection_host_state=selection.host_state,
        network_provider_admitted=False,
        auto_pull_performed=False,  # this lock NEVER auto-pulls
        training_eligibility_opened=False,
        notes=(
            f"operator must run `ollama pull {candidate}` to install the canonical model",
            "Determinex will NOT auto-pull",
            "downstream healthcheck + admission gates still apply",
        ),
    )


def _blocked(
    decision: str,
    *,
    model_id: str,
    provider: str,
    selection_decision: str,
    selection_host_state: str,
    note: str,
) -> OllamaModelPullOperatorGuideRecord:
    return OllamaModelPullOperatorGuideRecord(
        decision=decision,
        model_id=model_id,
        provider=provider,
        expected_command="",
        safety_warning="",
        next_validation_command="",
        selection_decision=selection_decision,
        selection_host_state=selection_host_state,
        network_provider_admitted=False,
        auto_pull_performed=False,
        training_eligibility_opened=False,
        notes=(note,),
    )


__all__ = [
    "guide",
    "OLLAMA_MODEL_PULL_OPERATOR_GUIDE_STATUS_TOKENS",
    "OllamaModelPullOperatorGuideRecord",
]
