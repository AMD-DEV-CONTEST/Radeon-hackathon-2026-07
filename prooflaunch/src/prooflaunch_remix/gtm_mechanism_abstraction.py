from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


SCHEMA = "ProofLaunchGTMMechanismAbstractionRegisterV1"
_OUTCOMES = frozenset(
    {
        "relative_breakout_candidate",
        "high_attention_low_conversion",
        "backlash",
        "positioning_drift",
        "content_fatigue",
    }
)
_COUNTERFACTUAL = frozenset({"survives", "weakens", "fails", "unknown"})
_FORBIDDEN_SOURCE_FIELDS = frozenset(
    {
        "raw_text",
        "source_text",
        "transcript",
        "caption",
        "creative_copy",
        "title",
        "description",
        "shot_list",
        "image_bytes",
        "audio_bytes",
    }
)
_CONFLICTS = (
    ("premium_trust", "aggressive_discount", "premium trust conflicts with aggressive discount framing"),
    ("community_contribution", "mass_link_drop", "community contribution conflicts with mass link placement"),
    ("regulated_claim_discipline", "unsupported_certainty", "regulated claim discipline conflicts with unsupported certainty"),
    ("long_term_brand_asset", "rage_bait", "long-term brand building conflicts with rage bait"),
)


class MechanismAbstractionError(ValueError):
    """Case abstraction would copy expression, invent causality, or escape its boundary."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _required(value: object, field: str, maximum: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise MechanismAbstractionError(f"{field} must be a bounded nonblank string")
    return value.strip()


def _assert_no_expression(value: object, path: str = "case") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_SOURCE_FIELDS:
                raise MechanismAbstractionError(f"{path}.{key} retains source expression")
            _assert_no_expression(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _assert_no_expression(child, f"{path}[{index}]")


def _time(value: object) -> str:
    text = _required(value, "observed_at", 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise MechanismAbstractionError("observed_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise MechanismAbstractionError("observed_at must include a timezone")
    return text


def _similarity(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise MechanismAbstractionError(f"{field} must be between 0 and 1")
    return round(float(value), 6)


def compile_mechanism_abstraction_register(
    cases: Sequence[Mapping[str, object]],
    *,
    recombinations: Sequence[Mapping[str, object]] = (),
    similarity_threshold: float = 0.78,
) -> dict[str, Any]:
    threshold = _similarity(similarity_threshold, "similarity_threshold")
    rows: list[dict[str, Any]] = []
    ids: set[str] = set()
    for case in cases:
        _assert_no_expression(case)
        case_id = _required(case.get("case_id"), "case_id", 128)
        if case_id in ids:
            raise MechanismAbstractionError("case IDs must be unique")
        ids.add(case_id)
        source_uri = _required(case.get("source_uri"), "source_uri")
        parsed = urlparse(source_uri)
        if parsed.scheme != "https" or not parsed.hostname:
            raise MechanismAbstractionError("source_uri must be public or authorized HTTPS")
        source_sha = _required(case.get("source_sha256"), "source_sha256", 64)
        if len(source_sha) != 64 or any(ch not in "0123456789abcdef" for ch in source_sha):
            raise MechanismAbstractionError("source_sha256 is invalid")
        if case.get("rights_status") not in {"public_measurement", "licensed", "owner_approved"}:
            raise MechanismAbstractionError("case rights are not admissible")
        outcome = _required(case.get("outcome_class"), "outcome_class", 64)
        if outcome not in _OUTCOMES:
            raise MechanismAbstractionError("outcome_class is unsupported")
        reviewer = _required(case.get("named_reviewer"), "named_reviewer", 200)
        chain = case.get("causal_chain")
        if not isinstance(chain, Mapping):
            raise MechanismAbstractionError("causal_chain is required")
        causal_fields = (
            "trigger_background",
            "audience_tension",
            "hook_mechanism",
            "proof_mechanism",
            "format_mechanism",
            "distribution_mechanism",
            "conversion_path",
        )
        normalized_chain = {field: _required(chain.get(field), f"causal_chain.{field}") for field in causal_fields}
        applicability = case.get("applicability")
        if not isinstance(applicability, Mapping):
            raise MechanismAbstractionError("applicability boundary is required")
        applicability_fields = ("industry", "company_scale", "budget", "market", "platform", "lifecycle")
        normalized_applicability = {field: _required(applicability.get(field), f"applicability.{field}", 300) for field in applicability_fields}
        counterfactual = case.get("counterfactual")
        if not isinstance(counterfactual, Mapping) or counterfactual.get("without_brand_budget_or_celebrity") not in _COUNTERFACTUAL:
            raise MechanismAbstractionError("mechanism counterfactual is incomplete")
        similarity = case.get("originality_similarity")
        if not isinstance(similarity, Mapping):
            raise MechanismAbstractionError("four-layer originality similarity is required")
        originality = {
            axis: _similarity(similarity.get(axis), f"originality_similarity.{axis}")
            for axis in ("semantic", "structure", "visual", "shot")
        }
        originality_passed = all(value <= threshold for value in originality.values())
        tags = sorted({_required(tag, "strategy_tag", 100) for tag in case.get("strategy_tags", [])})
        conflicts = [
            reason
            for left, right, reason in _CONFLICTS
            if left in tags and right in tags
        ]
        mechanism_id = f"mechanism-{_digest({'chain': normalized_chain, 'applicability': normalized_applicability})[:20]}"
        rows.append(
            {
                "case_id": case_id,
                "mechanism_id": mechanism_id,
                "source_uri": source_uri,
                "source_sha256": source_sha,
                "observed_at": _time(case.get("observed_at")),
                "rights_status": case["rights_status"],
                "named_reviewer": reviewer,
                "outcome_class": outcome,
                "failure_library_entry": outcome != "relative_breakout_candidate",
                "causal_chain_annotation": normalized_chain,
                "mechanism_only_expression_retained": False,
                "counterfactual": {
                    "without_brand_budget_or_celebrity": counterfactual["without_brand_budget_or_celebrity"],
                    "rationale": _required(counterfactual.get("rationale"), "counterfactual.rationale"),
                    "causality_proven": False,
                },
                "applicability_boundary": normalized_applicability,
                "strategy_tags": tags,
                "strategy_conflicts": conflicts,
                "originality_similarity": originality,
                "originality_threshold": threshold,
                "originality_gate_passed": originality_passed,
                "strategy_activation_eligible": originality_passed and not conflicts,
                "automatic_strategy_activation_allowed": False,
                "training_admitted": False,
            }
        )
    mechanisms = {row["mechanism_id"]: row for row in rows}
    recombination_rows: list[dict[str, Any]] = []
    for item in recombinations:
        source_ids = item.get("source_mechanism_ids")
        if not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes)) or len(set(source_ids)) < 2:
            raise MechanismAbstractionError("recombination requires at least two source mechanisms")
        if any(source_id not in mechanisms for source_id in source_ids):
            raise MechanismAbstractionError("recombination references an unknown mechanism")
        industries = {mechanisms[source_id]["applicability_boundary"]["industry"] for source_id in source_ids}
        if len(industries) < 2:
            raise MechanismAbstractionError("recombination requires cross-industry mechanisms")
        owner_proof_id = _required(item.get("owner_proof_id"), "owner_proof_id", 128)
        recombination_rows.append(
            {
                "recombination_id": f"recombination-{_digest({'sources': sorted(source_ids), 'proof': owner_proof_id})[:20]}",
                "source_mechanism_ids": sorted(source_ids),
                "source_industries": sorted(industries),
                "owner_proof_id": owner_proof_id,
                "mechanism_count": len(set(source_ids)),
                "cross_industry_gate_passed": True,
                "owner_proof_gate_passed": True,
                "creative_expression_copied": False,
                "human_strategy_selection": None,
                "automatic_strategy_activation_allowed": False,
            }
        )
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "case_count": len(rows),
        "breakout_case_count": sum(row["outcome_class"] == "relative_breakout_candidate" for row in rows),
        "failure_case_count": sum(row["failure_library_entry"] for row in rows),
        "strategy_conflict_case_count": sum(bool(row["strategy_conflicts"]) for row in rows),
        "originality_gate_pass_count": sum(row["originality_gate_passed"] for row in rows),
        "cases": rows,
        "recombination_count": len(recombination_rows),
        "recombinations": recombination_rows,
        "operational_state": "mechanism_register_ready" if rows else "awaiting_named_human_case_abstraction",
        "raw_creative_expression_retained": False,
        "automatic_strategy_mutation_executed": False,
        "automatic_training_admission_executed": False,
        "truth_boundary": (
            "A named reviewer supplies mechanism annotations and boundaries. The register does not infer causality from attention, "
            "retain source expression, copy a campaign, or activate strategy or training automatically."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_mechanism_abstraction_register(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise MechanismAbstractionError("mechanism abstraction seal is invalid")
    cases = payload.get("cases")
    if not isinstance(cases, list) or payload.get("case_count") != len(cases):
        raise MechanismAbstractionError("mechanism case count drifted")
    if payload.get("raw_creative_expression_retained") is not False:
        raise MechanismAbstractionError("mechanism register retained creative expression")
    if payload.get("automatic_strategy_mutation_executed") is not False or payload.get("automatic_training_admission_executed") is not False:
        raise MechanismAbstractionError("mechanism register executed an automatic mutation")
