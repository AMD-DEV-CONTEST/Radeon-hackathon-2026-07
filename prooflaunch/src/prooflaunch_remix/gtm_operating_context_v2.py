from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMOperatingContextMatrixV2"
SCALES = ("small", "mid_market", "enterprise_or_mass_brand")
LIFECYCLES = ("pre_pmf", "launch", "growth", "mature")
BUDGETS = ("zero_paid", "low_budget", "capital_efficient", "mixed_budget", "mature_scale")
COST_COMPONENTS = ("paid_media", "personnel", "tools", "creators", "channel_fees", "production")
COMPETITION_DIMENSIONS = (
    "content_density", "advertising_density", "search_difficulty",
    "creator_saturation", "price_competition", "trust_threshold",
)
ALLOCATION_BUCKETS = ("brand_building", "demand_capture", "retargeting", "channel_incentives")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class GTMOperatingContextError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _required_keys(value: Any, keys: Sequence[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GTMOperatingContextError(f"{label} must be an object")
    missing = [key for key in keys if key not in value]
    if missing:
        raise GTMOperatingContextError(f"{label} misses: {', '.join(missing)}")
    return value


def _scale_contract(scale: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if scale == "small":
        required = ("founder_time_hours_per_week", "sales_capacity_opportunities_per_month", "cash_cycle_days", "delivery_capacity_units_per_month", "top_channel_share_pct")
        _required_keys(inputs, required, label="small scale_inputs")
        return {
            "binding_constraints": ["founder_time", "sales_capacity", "cash_cycle", "delivery_bottleneck", "single_channel_risk"],
            "risk_flags": ["single_channel_concentration"] if float(inputs["top_channel_share_pct"]) > 60 else [],
            "planning_rule": "Do not propose a content or lead volume that exceeds founder, sales, cash, or delivery capacity.",
        }
    if scale == "mid_market":
        required = ("cross_function_owners", "brand_consistency_review", "regions", "channel_conflicts", "existing_customer_expansion_motion")
        _required_keys(inputs, required, label="mid-market scale_inputs")
        if len(inputs["cross_function_owners"]) < 2 or not inputs["regions"]:
            raise GTMOperatingContextError("mid-market context needs cross-functional owners and a region")
        return {
            "binding_constraints": ["department_coordination", "brand_consistency", "regional_expansion", "channel_conflict", "existing_customer_expansion"],
            "risk_flags": ["declared_channel_conflict"] if inputs["channel_conflicts"] else [],
            "planning_rule": "Bind owners, brand review, regional variation, channel conflict resolution, and customer expansion before launch.",
        }
    required = ("procurement_lead_time_days", "legal_review_required", "markets", "brand_governance_owner", "channel_partner_model", "organizational_change_cost_band")
    _required_keys(inputs, required, label="enterprise scale_inputs")
    if not inputs["markets"] or not str(inputs["brand_governance_owner"]):
        raise GTMOperatingContextError("enterprise context needs market and governance ownership")
    return {
        "binding_constraints": ["procurement", "legal", "multi_market_governance", "brand_assets", "channel_partners", "organizational_change_cost"],
        "risk_flags": ["legal_review_required"] if inputs["legal_review_required"] else [],
        "planning_rule": "Sequence procurement, legal, market governance, channel partners, and change management before scale execution.",
    }


def _lifecycle_contract(lifecycle: str, inputs: Mapping[str, Any], requested_objectives: Sequence[str]) -> dict[str, Any]:
    if lifecycle == "pre_pmf":
        _required_keys(inputs, ("problem_validation_method", "activation_event"), label="pre-PMF lifecycle_inputs")
        allowed = {"problem_awareness", "problem_validation", "activation_learning"}
        rejected = sorted(set(requested_objectives) - allowed)
        return {
            "allowed_objectives": sorted(allowed),
            "rejected_objectives": rejected,
            "required_proof": ["problem signal", "activation observation"],
            "forbidden_claim": "Do not promise scalable acquisition before product-market fit evidence.",
        }
    if lifecycle == "launch":
        _required_keys(inputs, ("first_audience", "first_channel", "first_value_moment", "feedback_loop"), label="launch lifecycle_inputs")
        return {
            "allowed_objectives": ["first_audience_proof", "first_channel_proof", "first_value_moment", "feedback_learning"],
            "rejected_objectives": [],
            "required_proof": ["named first audience", "one first channel", "observable first value moment", "real feedback loop"],
            "forbidden_claim": "Do not treat reach as proof of repeatable launch fit.",
        }
    if lifecycle == "growth":
        _required_keys(inputs, ("marginal_cac_usd", "retention_rate", "delivery_capacity_utilization_pct", "channel_saturation_score"), label="growth lifecycle_inputs")
        return {
            "allowed_objectives": ["efficient_acquisition", "retained_growth", "capacity_safe_growth", "channel_diversification"],
            "rejected_objectives": [],
            "required_proof": ["marginal CAC", "retention", "delivery capacity", "channel saturation"],
            "forbidden_claim": "Do not optimize acquisition while retention or delivery capacity is failing.",
        }
    _required_keys(inputs, ("brand_compounding_asset", "portfolio_efficiency_metric", "customer_expansion_metric", "internationalization_scope", "innovation_risk"), label="mature lifecycle_inputs")
    return {
        "allowed_objectives": ["brand_compounding", "portfolio_efficiency", "customer_expansion", "internationalization", "managed_innovation"],
        "rejected_objectives": [],
        "required_proof": ["brand asset", "portfolio efficiency", "customer expansion", "international scope", "innovation risk"],
        "forbidden_claim": "Do not sacrifice brand or portfolio economics for a short-lived channel spike.",
    }


def _budget_contract(budget: str, costs: Mapping[str, Any], allocation: Any) -> dict[str, Any]:
    _required_keys(costs, COST_COMPONENTS, label="resource_costs")
    known_total = 0.0
    unknown = []
    for component in COST_COMPONENTS:
        row = costs[component]
        if not isinstance(row, Mapping) or row.get("disclosure_status") not in {"known_zero", "disclosed", "bounded_estimate", "unknown"}:
            raise GTMOperatingContextError(f"invalid cost record: {component}")
        amount = row.get("amount_usd")
        if amount is None:
            unknown.append(component)
        elif float(amount) < 0:
            raise GTMOperatingContextError("costs cannot be negative")
        else:
            known_total += float(amount)
    blockers = []
    if budget in {"zero_paid", "low_budget"}:
        for component in ("personnel", "production"):
            if costs[component].get("disclosure_status") == "known_zero":
                blockers.append(f"{component}_cannot_be_assumed_free")
    normalized_allocation = None
    if budget in {"mixed_budget", "mature_scale"}:
        if not isinstance(allocation, Mapping) or set(allocation) != set(ALLOCATION_BUCKETS):
            blockers.append("four_way_budget_allocation_missing")
        else:
            normalized_allocation = {key: float(allocation[key]) for key in ALLOCATION_BUCKETS}
            if any(value < 0 for value in normalized_allocation.values()) or sum(normalized_allocation.values()) <= 0:
                blockers.append("four_way_budget_allocation_invalid")
    return {
        "known_cost_total_usd": round(known_total, 2),
        "unknown_cost_components": unknown,
        "allocation": normalized_allocation,
        "blockers": blockers,
        "planning_rule": "Count labor and production even when paid media is zero; separate brand, capture, retargeting, and channel incentives at scale.",
    }


def _competition_index(inputs: Mapping[str, Any]) -> dict[str, Any]:
    _required_keys(inputs, COMPETITION_DIMENSIONS, label="competition_inputs")
    values = {}
    evidence_states = []
    for dimension in COMPETITION_DIMENSIONS:
        row = inputs[dimension]
        if not isinstance(row, Mapping):
            raise GTMOperatingContextError(f"competition dimension is invalid: {dimension}")
        score = float(row.get("score", -1))
        receipts = [str(value) for value in row.get("evidence_receipt_sha256s") or []]
        if not 0 <= score <= 100 or not receipts or not all(SHA256_RE.fullmatch(value) for value in receipts):
            raise GTMOperatingContextError(f"competition dimension lacks bounded score and evidence: {dimension}")
        values[dimension] = score
        evidence_states.append(str(row.get("evidence_status") or "unknown"))
    composite = sum(values.values()) / len(values)
    band = "extreme" if composite >= 80 else "high" if composite >= 60 else "moderate" if composite >= 40 else "low"
    return {
        "dimension_scores": values,
        "equal_weight_composite": round(composite, 3),
        "pressure_band": band,
        "evidence_status": "observed" if set(evidence_states) == {"observed"} else "synthetic_or_mixed",
        "interpretation_rule": "Use the index to tighten differentiation, proof, channel focus, and trust requirements; never treat it as a forecast.",
    }


def compile_operating_context_matrix(scenarios: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    ids: set[str] = set()
    for raw in scenarios:
        scenario_id = str(raw.get("scenario_id") or "")
        scale = str(raw.get("company_scale") or "")
        lifecycle = str(raw.get("lifecycle_state") or "")
        budget = str(raw.get("budget_tier") or "")
        if not scenario_id or scenario_id in ids or scale not in SCALES or lifecycle not in LIFECYCLES or budget not in BUDGETS:
            raise GTMOperatingContextError("scenario identity or controlled vocabulary is invalid")
        ids.add(scenario_id)
        scale_contract = _scale_contract(scale, raw.get("scale_inputs") or {})
        lifecycle_contract = _lifecycle_contract(lifecycle, raw.get("lifecycle_inputs") or {}, list(raw.get("requested_objectives") or []))
        budget_contract = _budget_contract(budget, raw.get("resource_costs") or {}, raw.get("budget_allocation"))
        pressure = _competition_index(raw.get("competition_inputs") or {})
        blockers = [*lifecycle_contract["rejected_objectives"], *budget_contract["blockers"]]
        rows.append({
            "scenario_id": scenario_id,
            "company_scale": scale,
            "lifecycle_state": lifecycle,
            "budget_tier": budget,
            "scale_contract": scale_contract,
            "lifecycle_contract": lifecycle_contract,
            "budget_contract": budget_contract,
            "competition_pressure_index": pressure,
            "blockers": blockers,
            "status": "operating_context_ready" if not blockers else "operating_context_gap",
            "external_action_authority": False,
            "observed_effect_claim_allowed": False,
        })
    coverage = {
        "company_scales": sorted({row["company_scale"] for row in rows}),
        "lifecycle_states": sorted({row["lifecycle_state"] for row in rows}),
        "budget_tiers": sorted({row["budget_tier"] for row in rows}),
        "scale_lifecycle_budget_combinations": len({(row["company_scale"], row["lifecycle_state"], row["budget_tier"]) for row in rows}),
    }
    payload = {
        "schema": SCHEMA,
        "scenario_count": len(rows),
        "scenarios": sorted(rows, key=lambda row: row["scenario_id"]),
        "coverage": coverage,
        "policy": {
            "zero_paid_means_zero_paid_media_not_zero_total_cost": True,
            "pre_pmf_scale_claims_allowed": False,
            "lifecycle_and_scale_change_strategy_constraints": True,
            "competition_index_is_forecast": False,
        },
        "truth_boundary": "This matrix proves deterministic operating constraints. Synthetic scenarios do not prove market performance or completeness of any real company input.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_operating_context_matrix(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMOperatingContextError("operating context seal is invalid")
    rows = payload.get("scenarios")
    if not isinstance(rows, list) or payload.get("scenario_count") != len(rows):
        raise GTMOperatingContextError("operating context aggregate drifted")
    if any(row.get("external_action_authority") is not False or row.get("observed_effect_claim_allowed") is not False for row in rows):
        raise GTMOperatingContextError("operating context escaped authority or effect boundary")


__all__ = ["GTMOperatingContextError", "compile_operating_context_matrix", "verify_operating_context_matrix"]
