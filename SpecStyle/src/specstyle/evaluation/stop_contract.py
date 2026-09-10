"""Formal arm stopping-event and candidate-selection contracts."""

from __future__ import annotations

from typing import Any

from specstyle.calibration.evidence_io import _exact, _sha, _text
from specstyle.errors import DomainError
from specstyle.evaluation.protocol import FORMAL_ARMS

_STOP_EVENT_KEYS = {
    "generation_index",
    "guardrail_decision",
    "kind",
    "repair_action_sha256",
    "result_sha256",
    "trigger_rule_ids",
}


def _optional_sha(value: object, name: str) -> str | None:
    return None if value is None else _sha(value, name)


def _rule_ids(value: object) -> list[str]:
    if type(value) is not list:
        raise DomainError("invalid machine evaluation ledger")
    rules = [_text(item, "trigger rule id") for item in value]
    if len(set(rules)) != len(rules):
        raise DomainError("invalid machine evaluation ledger")
    return rules


def parse_stop_event(
    value: object, attempts: tuple[dict[str, Any], ...]
) -> dict[str, Any]:
    event = _exact(value, _STOP_EVENT_KEYS, "machine stop event")
    index = event["generation_index"]
    if index is not None and (
        type(index) is not int
        or isinstance(index, bool)
        or not 0 <= index < len(attempts)
    ):
        raise DomainError("invalid machine evaluation ledger")
    decision = _text(event["guardrail_decision"], "stop guardrail decision")
    if decision not in {
        "DISABLED_EVALUATION_ONLY",
        "NOT_APPLICABLE",
        "PASSED",
        "REJECTED",
    }:
        raise DomainError("invalid machine evaluation ledger")
    return {
        "generation_index": index,
        "guardrail_decision": decision,
        "kind": _text(event["kind"], "machine stop kind"),
        "repair_action_sha256": _optional_sha(
            event["repair_action_sha256"], "stop repair action sha256"
        ),
        "result_sha256": _sha(event["result_sha256"], "stop result sha256"),
        "trigger_rule_ids": _rule_ids(event["trigger_rule_ids"]),
    }


def _plain(event: dict[str, Any], last_index: int) -> bool:
    return (
        event["generation_index"] == last_index
        and event["guardrail_decision"] == "NOT_APPLICABLE"
        and event["repair_action_sha256"] is None
        and not event["trigger_rule_ids"]
    )


def _early_repair(
    arm: str, attempts: tuple[dict[str, Any], ...], event: dict[str, Any]
) -> bool:
    kind = event["kind"]
    last = attempts[-1]
    index = event["generation_index"]
    decision = event["guardrail_decision"]
    action = event["repair_action_sha256"]
    rules = event["trigger_rule_ids"]
    if kind == "GENERATION_FAILED":
        return (
            index == len(attempts) - 1
            and last["generation_status"] == "GENERATION_FAILED"
            and decision == "NOT_APPLICABLE"
            and action is None
            and not rules
        )
    if kind == "NO_ACTION_AVAILABLE":
        return (
            index is None
            and decision == "NOT_APPLICABLE"
            and action is None
            and bool(rules)
        )
    if kind == "UNVERIFIABLE":
        return (
            index == len(attempts) - 1
            and last["generation_status"] == "GENERATED"
            and decision == "NOT_APPLICABLE"
            and action is None
            and bool(rules)
        )
    if arm != FORMAL_ARMS[4]:
        return False
    if kind == "NO_IMPROVEMENT":
        return (
            index == len(attempts) - 1
            and last["generation_status"] == "GENERATED"
            and decision == "PASSED"
            and action == last["repair_action_sha256"]
            and rules == last["trigger_rule_ids"]
            and bool(rules)
        )
    return (
        kind == "GUARDRAIL_REJECTED"
        and index is None
        and decision == "REJECTED"
        and action is not None
        and bool(rules)
    )


def _valid_stop(
    arm: str,
    attempts: tuple[dict[str, Any], ...],
    maximum: int,
    event: dict[str, Any],
) -> bool:
    passed = any(item["qa_pass"] for item in attempts)
    kind = event["kind"]
    plain = _plain(event, len(attempts) - 1)
    if arm == FORMAL_ARMS[0]:
        return len(attempts) == 1 and kind == "SINGLE_PASS_COMPLETE" and plain
    if arm == FORMAL_ARMS[1]:
        return (passed and kind == "QA_PASSED" and plain) or (
            not passed
            and len(attempts) == maximum
            and kind == "BUDGET_EXHAUSTED"
            and plain
        )
    if arm == FORMAL_ARMS[2]:
        return len(attempts) == maximum and kind == "BUDGET_EXHAUSTED" and plain
    return (
        (passed and kind == "QA_PASSED" and plain)
        or (
            not passed
            and len(attempts) == maximum
            and kind == "BUDGET_EXHAUSTED"
            and plain
        )
        or (
            not passed
            and len(attempts) < maximum
            and _early_repair(arm, attempts, event)
        )
    )


def validate_stopping(
    arm: str,
    attempts: tuple[dict[str, Any], ...],
    candidate: str | None,
    maximum: int,
    stop_event: dict[str, Any],
) -> None:
    if not _valid_stop(arm, attempts, maximum, stop_event):
        raise DomainError("invalid machine evaluation ledger")
    generated = [item for item in attempts if item["artifact_sha256"] is not None]
    if arm == FORMAL_ARMS[2] and candidate is not None:
        best = max(float(item["utility_score"]) for item in generated)
        selected = next(item for item in generated if item["utility_score"] == best)
        if candidate != selected["artifact_sha256"]:
            raise DomainError("invalid machine evaluation ledger")
    elif arm != FORMAL_ARMS[2]:
        passing = [index for index, item in enumerate(attempts) if item["qa_pass"]]
        if passing and passing[0] != len(attempts) - 1:
            raise DomainError("invalid machine evaluation ledger")
        if candidate is not None and candidate != generated[-1]["artifact_sha256"]:
            raise DomainError("invalid machine evaluation ledger")
