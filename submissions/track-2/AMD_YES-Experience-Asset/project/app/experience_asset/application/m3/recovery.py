"""Deterministic, side-effect-free recovery decisions for E4/M3 preparation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.experience_asset.workflow.m3_state import (
    M3_MODEL_CALL_BUDGET,
    M3_REPLAN_BUDGET,
    M3_STRUCTURED_REPAIR_BUDGET,
    M3GraphStateV1,
)


class M3RecoveryAction(StrEnum):
    REPAIR = "REPAIR"
    REPLAN = "REPLAN"
    SAFE_STOP = "SAFE_STOP"


@dataclass(frozen=True)
class M3RecoveryDecision:
    """A small immutable result that production graph nodes can consume later."""

    action: M3RecoveryAction
    selected_edge: str
    failure_code: str | None
    state: M3GraphStateV1


def decide_invalid_output_recovery(
    state: M3GraphStateV1,
) -> M3RecoveryDecision:
    """Choose one bounded recovery step without retrying or executing effects.

    A structured repair is preferred while both its own budget and the global
    model-call budget remain. Once repairs are exhausted, one re-plan may be
    attempted if a model call remains. Otherwise the run stops with the stable
    invalid-output failure code.
    """

    if (
        state.structured_repair_attempts < M3_STRUCTURED_REPAIR_BUDGET
        and state.model_call_count < M3_MODEL_CALL_BUDGET
    ):
        return M3RecoveryDecision(
            action=M3RecoveryAction.REPAIR,
            selected_edge="validate_m3_output:repairable",
            failure_code=None,
            state=state.model_copy(
                update={
                    "structured_repair_attempts": (state.structured_repair_attempts + 1),
                    "model_call_count": state.model_call_count + 1,
                    "last_node": "validate_m3_output",
                    "selected_edge": "validate_m3_output:repairable",
                    "finding_codes": sorted({*state.finding_codes, "INVALID_MODEL_OUTPUT"}),
                    "safe_message": (
                        "The structured result was invalid; a bounded repair will be attempted."
                    ),
                }
            ),
        )

    if state.replan_attempts < M3_REPLAN_BUDGET and state.model_call_count < M3_MODEL_CALL_BUDGET:
        return M3RecoveryDecision(
            action=M3RecoveryAction.REPLAN,
            selected_edge="validate_m3_output:exhausted",
            failure_code=None,
            state=state.model_copy(
                update={
                    "replan_attempts": state.replan_attempts + 1,
                    "model_call_count": state.model_call_count + 1,
                    "last_node": "validate_m3_output",
                    "selected_edge": "validate_m3_output:exhausted",
                    "finding_codes": sorted(
                        {
                            *state.finding_codes,
                            "INVALID_MODEL_OUTPUT",
                            "STRUCTURED_REPAIR_EXHAUSTED",
                        }
                    ),
                    "safe_message": (
                        "Structured repairs were exhausted; one bounded re-plan will be attempted."
                    ),
                }
            ),
        )

    return M3RecoveryDecision(
        action=M3RecoveryAction.SAFE_STOP,
        selected_edge="replan_m3_run:exhausted",
        failure_code="REPLAN_EXHAUSTED",
        state=state.model_copy(
            update={
                "last_node": "replan_m3_run",
                "selected_edge": "replan_m3_run:exhausted",
                "terminal_candidate": "INVALID_MODEL_OUTPUT",
                "finding_codes": sorted(
                    {
                        *state.finding_codes,
                        "INVALID_MODEL_OUTPUT",
                        "STRUCTURED_REPAIR_EXHAUSTED",
                        "REPLAN_EXHAUSTED",
                    }
                ),
                "safe_message": (
                    "The local model could not produce a valid ledger within "
                    "the bounded recovery budget. No ledger was saved."
                ),
                "retryable": False,
            }
        ),
    )
