"""Deterministic checks shared by memory and Prompt A/B experiments."""

from __future__ import annotations

from typing import Any

from app.evidence.model_client import strict_json


RISK_MARKERS = ("必然", "保证胜诉", "一定主责", "保险公司一定少赔")
ID_FIELDS = ("fact_ids", "evidence_ids", "law_ids")


def string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float))]


def evaluate_answer(
    content: str,
    *,
    allowed_fact_ids: set[str],
    allowed_evidence_ids: set[str],
    allowed_law_ids: set[str],
    uncertainty_required: bool = False,
) -> dict[str, Any]:
    try:
        payload = strict_json(content)
        parse_error = ""
    except Exception as exc:  # noqa: BLE001 - experiment records bad outputs
        payload = {}
        parse_error = repr(exc)
    allowed = {
        "fact_ids": allowed_fact_ids,
        "evidence_ids": allowed_evidence_ids,
        "law_ids": allowed_law_ids,
    }
    unsupported: dict[str, list[str]] = {}
    supported_count = 0
    cited_count = 0
    for field in ID_FIELDS:
        values = string_list(payload, field)
        cited_count += len(values)
        supported_count += sum(value in allowed[field] for value in values)
        unsupported[field] = sorted(set(values) - allowed[field])
    risk_markers = [marker for marker in RISK_MARKERS if marker in content]
    hypotheses = payload.get("liability_hypotheses")
    has_multiple_hypotheses = isinstance(hypotheses, list) and len(hypotheses) >= 2
    uncertainty = str(payload.get("uncertainty", "")).strip()
    structure_checks = {
        "valid_json": not parse_error,
        "answer_present": bool(str(payload.get("answer", "")).strip()),
        "fact_ids_present": bool(string_list(payload, "fact_ids")),
        "evidence_ids_present": bool(string_list(payload, "evidence_ids")),
        "law_ids_present": bool(string_list(payload, "law_ids")),
        "multiple_hypotheses": has_multiple_hypotheses,
        "uncertainty_control": bool(uncertainty) if uncertainty_required else True,
    }
    grounding = supported_count / max(1, cited_count)
    required_passed = all(structure_checks.values())
    verifier_pass = (
        required_passed
        and not risk_markers
        and not any(unsupported.values())
    )
    return {
        "payload": payload,
        "parse_error": parse_error,
        "structure_checks": structure_checks,
        "unsupported_ids": unsupported,
        "risk_markers": risk_markers,
        "evidence_grounding": round(grounding, 6),
        "verifier_pass": verifier_pass,
        "quality_score": round(
            100
            * (
                0.45 * (sum(structure_checks.values()) / len(structure_checks))
                + 0.40 * grounding
                + 0.15 * (not risk_markers)
            ),
            3,
        ),
    }


def conclusion_consistency(first: dict[str, Any], second: dict[str, Any]) -> float:
    """Compare conclusion-bearing IDs and states without brittle text equality."""

    scores: list[float] = []
    for field in ID_FIELDS:
        left = set(string_list(first, field))
        right = set(string_list(second, field))
        union = left | right
        scores.append(len(left & right) / len(union) if union else 1.0)
    for field in ("approval_status", "uncertainty"):
        left_value = str(first.get(field, "")).strip()
        right_value = str(second.get(field, "")).strip()
        if left_value or right_value:
            scores.append(float(left_value == right_value))
    return round(sum(scores) / max(1, len(scores)), 6)
