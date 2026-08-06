from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


SCHEMA = "ProofLaunchGTMFinalAcceptanceMatrixV2"
B2B_GOLD = (
    "b2b.industrial_climate.manufacturing",
    "b2b.industrial_climate.industrial_equipment",
    "b2b.industrial_climate.engineering_construction",
    "b2b.industrial_climate.commercial_real_estate",
    "b2b.professional_services.consulting",
)
B2C_GOLD = (
    "b2c.consumer_ai_mobile_apps.creative_apps",
    "b2c.health_wellness.fitness",
    "b2c.beauty_fashion.beauty",
    "b2c.food_beverage.consumer_packaged_goods",
    "b2c.travel_hospitality.destinations",
)


class GTMFinalAcceptanceError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def compile_final_acceptance_matrix(
    coverage: Mapping[str, Any],
    named_pk: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    todo_ledger: Mapping[str, Any],
    *,
    production_gold_stress_pass_count: int,
    traceable_claim_count: int,
    total_claim_count: int,
) -> dict[str, Any]:
    complete_ids = set(map(str, coverage.get("complete_subvertical_ids") or []))
    b2b_complete = {value for value in complete_ids if value.startswith("b2b.")}
    b2c_complete = {value for value in complete_ids if value.startswith("b2c.")}
    priority_ten = set(B2B_GOLD) | set(B2C_GOLD)
    completed_pk = int(named_pk.get("completed_product_pk_rows", 0))
    pk_wins = int(named_pk.get("candidate_win_count", 0))
    reviews = int(named_pk.get("submitted_human_review_count", 0))
    production_effects = int(lifecycle.get("production_outcomes_observed", 0))
    traceability_pass = total_claim_count > 0 and traceable_claim_count == total_claim_count
    gates = {
        "T091_priority_ten_full_funnel": {"required": 10, "observed": len(priority_ten & complete_ids), "pass": priority_ten.issubset(complete_ids)},
        "T092_all_b2b_full_funnel": {"required": 41, "observed": len(b2b_complete), "pass": len(b2b_complete) == 41},
        "T093_all_b2c_full_funnel": {"required": 40, "observed": len(b2c_complete), "pass": len(b2c_complete) == 40},
        "T094_b2b_gold_loops": {"required": 5, "observed": len(set(B2B_GOLD) & complete_ids), "pass": set(B2B_GOLD).issubset(complete_ids)},
        "T095_b2c_gold_loops": {"required": 5, "observed": len(set(B2C_GOLD) & complete_ids), "pass": set(B2C_GOLD).issubset(complete_ids)},
        "T096_gold_lifecycle_budget_stress": {"required": 200, "observed": int(production_gold_stress_pass_count), "pass": int(production_gold_stress_pass_count) == 200, "synthetic_lifecycle_scenarios_not_credited": int(lifecycle.get("scenario_count", 0))},
        "T097_named_product_pk": {"required_rows": 130, "protocol_rows": int(named_pk.get("row_count", 0)), "completed_rows": completed_pk, "candidate_wins": pk_wins, "pass": completed_pk == 130 and pk_wins == 130},
        "T098_five_hidden_reviewers_per_pk_row": {"required_reviews": 650, "observed_reviews": reviews, "pass": reviews >= 650 and completed_pk == 130},
        "T099_authorized_market_validation": {"required": 1, "observed": production_effects, "pass": production_effects > 0},
        "T100_final_release": {
            "subverticals_required": 81,
            "subverticals_complete": len(complete_ids),
            "gold_loops_required": 10,
            "gold_loops_complete": len(priority_ten & complete_ids),
            "traceable_claims": traceable_claim_count,
            "total_claims": total_claim_count,
            "traceability_pass": traceability_pass,
            "todo_completion_claim_allowed": bool(todo_ledger.get("completion_claim_allowed")),
            "pass": False,
        },
    }
    gates["T100_final_release"]["pass"] = all(gates[key]["pass"] for key in gates if key != "T100_final_release") and traceability_pass and bool(todo_ledger.get("completion_claim_allowed"))
    payload = {
        "schema": SCHEMA,
        "source_sha256s": {
            "coverage": coverage.get("content_sha256"), "named_pk": named_pk.get("content_sha256"),
            "lifecycle": lifecycle.get("content_sha256"), "todo_ledger": todo_ledger.get("content_sha256"),
        },
        "gates": gates,
        "passed_gate_count": sum(gate["pass"] for gate in gates.values()),
        "required_gate_count": 10,
        "final_release_allowed": gates["T100_final_release"]["pass"],
        "four_a_top1_or_effect_superiority_claim_allowed": False,
        "truth_boundary": "This matrix credits only completed real evidence. Synthetic scenarios, protocols, prepared packets, and unsubmitted reviews receive zero production-completion credit.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_final_acceptance_matrix(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMFinalAcceptanceError("final acceptance seal is invalid")
    gates = payload.get("gates")
    if not isinstance(gates, Mapping) or len(gates) != 10 or payload.get("passed_gate_count") != sum(gate.get("pass") is True for gate in gates.values()):
        raise GTMFinalAcceptanceError("final acceptance gate aggregate drifted")
    if payload.get("final_release_allowed") != gates["T100_final_release"]["pass"]:
        raise GTMFinalAcceptanceError("final release state drifted")
    if payload.get("four_a_top1_or_effect_superiority_claim_allowed") is not False:
        raise GTMFinalAcceptanceError("final matrix overstates quality or effect")


__all__ = ["GTMFinalAcceptanceError", "compile_final_acceptance_matrix", "verify_final_acceptance_matrix"]
