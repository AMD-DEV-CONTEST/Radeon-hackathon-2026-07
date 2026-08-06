from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .gtm_organic_signal_sampling_standard import PLATFORMS


SCHEMA = "ProofLaunchGTMStrategyDecisionPackV2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_CHANNELS = {row["platform"] for row in PLATFORMS}
B2B_ROLES = ("user", "champion", "technical_approver", "economic_buyer", "procurement", "legal", "opponent")
B2C_ROLES = ("user", "payer", "household", "peer", "creator", "reviewer", "repeat_buyer")
TENSION_FIELDS = ("stale_assumption", "hidden_cost", "unmet_job", "cultural_tension", "ownable_narrative")
WHY_NOW_FIELDS = ("technology", "economic", "regulatory", "cultural", "platform")


class GTMStrategyDecisionError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(row: Mapping[str, Any], field: str, minimum: int = 4) -> str:
    value = str(row.get(field) or "").strip()
    if len(value) < minimum:
        raise GTMStrategyDecisionError(f"{field} is missing or too thin")
    return value


def _receipts(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise GTMStrategyDecisionError("at least one evidence receipt is required")
    rows = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise GTMStrategyDecisionError("evidence receipt is invalid")
        url, digest = str(item.get("source_url") or ""), str(item.get("content_sha256") or "")
        if urlparse(url).scheme != "https" or not urlparse(url).netloc or not SHA256_RE.fullmatch(digest):
            raise GTMStrategyDecisionError("evidence receipt lacks public HTTPS URL or SHA-256")
        rows.append({"source_url": url, "content_sha256": digest, "claim_scope": _text(item, "claim_scope", 8)})
    return rows


def _influence_graph(business_model: str, audience: Mapping[str, Any]) -> dict[str, Any]:
    roles = B2B_ROLES if business_model == "b2b" else B2C_ROLES
    overlays = audience.get("role_overlays") if isinstance(audience.get("role_overlays"), Mapping) else {}
    nodes = []
    for role in roles:
        overlay = overlays.get(role) if isinstance(overlays.get(role), Mapping) else {}
        nodes.append({
            "role": role,
            "decision_job": str(overlay.get("decision_job") or f"Resolve the {role.replace('_', ' ')} decision in the primary audience journey."),
            "resistance_or_motivation": str(overlay.get("resistance_or_motivation") or "Must be researched for this brief."),
            "evidence_state": str(overlay.get("evidence_state") or "assumption_pending_validation"),
        })
    edges = [{"from": roles[index], "to": roles[index + 1], "relationship": "influences_or_gates"} for index in range(len(roles) - 1)]
    return {"graph_type": "buying_committee" if business_model == "b2b" else "consumer_influence", "nodes": nodes, "edges": edges}


def compile_strategy_decision_pack(brief: Mapping[str, Any]) -> dict[str, Any]:
    brief_id = _text(brief, "brief_id", 4)
    business_model = str(brief.get("business_model") or "")
    if business_model not in {"b2b", "b2c"}:
        raise GTMStrategyDecisionError("business_model must be b2b or b2c")
    product_truth = brief.get("product_truth")
    if not isinstance(product_truth, list) or len(product_truth) < 2:
        raise GTMStrategyDecisionError("product truth requires at least two source-bound statements")
    for statement in product_truth:
        _text(statement, "statement", 12)
        hashes = statement.get("evidence_receipt_sha256s")
        if not isinstance(hashes, list) or not hashes or not all(SHA256_RE.fullmatch(str(value)) for value in hashes):
            raise GTMStrategyDecisionError("product truth lacks evidence hashes")
    market = brief.get("market")
    audience = brief.get("audience")
    budget = brief.get("budget")
    objective = brief.get("objective")
    delivery = brief.get("delivery_capability")
    for value, label, fields in (
        (market, "market", ("primary_market", "competition_pressure_index")),
        (audience, "audience", ("primary_segment", "job_to_be_done")),
        (budget, "budget", ("tier", "total_ceiling_usd")),
        (objective, "objective", ("primary_metric", "target_direction", "horizon_days")),
        (delivery, "delivery_capability", ("content_hours_per_week", "approvers", "production_capabilities")),
    ):
        if not isinstance(value, Mapping) or any(field not in value for field in fields):
            raise GTMStrategyDecisionError(f"{label} is incomplete")
    evidence = _receipts(brief.get("evidence_receipts"))
    evidence_hashes = {row["content_sha256"] for row in evidence}

    entry_points = brief.get("category_entry_points")
    if not isinstance(entry_points, list) or len(entry_points) < 3:
        raise GTMStrategyDecisionError("at least three category entry points must precede format selection")
    normalized_entry_points = []
    for row in entry_points:
        hashes = [str(value) for value in row.get("evidence_receipt_sha256s") or []]
        if not hashes or not set(hashes).issubset(evidence_hashes):
            raise GTMStrategyDecisionError("category entry point is not bound to brief evidence")
        normalized_entry_points.append({
            "entry_point_id": _text(row, "entry_point_id"),
            "situation_trigger": _text(row, "situation_trigger", 8),
            "customer_job": _text(row, "customer_job", 8),
            "evidence_receipt_sha256s": hashes,
        })

    tensions = brief.get("strategic_tensions")
    if not isinstance(tensions, Mapping):
        raise GTMStrategyDecisionError("strategic tensions are required")
    normalized_tensions = {field: _text(tensions, field, 12) for field in TENSION_FIELDS}

    why_now = brief.get("why_now")
    if not isinstance(why_now, Mapping) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(why_now.get("as_of_date") or "")):
        raise GTMStrategyDecisionError("why-now requires an ISO date")
    why_hashes = [str(value) for value in why_now.get("evidence_receipt_sha256s") or []]
    if not why_hashes or not set(why_hashes).issubset(evidence_hashes):
        raise GTMStrategyDecisionError("why-now is not bound to brief evidence")
    normalized_why_now = {"as_of_date": why_now["as_of_date"], **{field: _text(why_now, field, 8) for field in WHY_NOW_FIELDS}, "evidence_receipt_sha256s": why_hashes}

    wedges = brief.get("strategic_wedges")
    if not isinstance(wedges, list) or len(wedges) < 5:
        raise GTMStrategyDecisionError("at least five strategic wedges are required")
    normalized_wedges = []
    wedge_ids: set[str] = set()
    for raw in wedges:
        wedge_id = _text(raw, "wedge_id")
        if wedge_id in wedge_ids:
            raise GTMStrategyDecisionError("strategic wedge IDs must be unique")
        wedge_ids.add(wedge_id)
        primary, enhancer = str(raw.get("primary_channel") or ""), str(raw.get("enhancing_channel") or "")
        if primary not in ALLOWED_CHANNELS or enhancer not in ALLOWED_CHANNELS or primary == enhancer:
            raise GTMStrategyDecisionError("each wedge needs one distinct primary and enhancing channel")
        proof_hashes = [str(value) for value in raw.get("proof_receipt_sha256s") or []]
        if not proof_hashes or not set(proof_hashes).issubset(evidence_hashes):
            raise GTMStrategyDecisionError("strategic wedge lacks brief-bound proof")
        scores = {field: float(raw.get(field, -1)) for field in ("evidence_fit_score", "resource_fit_score", "differentiation_score")}
        if any(not 0 <= value <= 100 for value in scores.values()):
            raise GTMStrategyDecisionError("strategic wedge scores must be in [0,100]")
        expected_chain = list(raw.get("expected_chain") or [])
        if len(expected_chain) < 3:
            raise GTMStrategyDecisionError("strategic wedge expected chain is too short")
        normalized_wedges.append({
            "wedge_id": wedge_id,
            "thesis": _text(raw, "thesis", 16),
            "category_entry_point_ids": list(raw.get("category_entry_point_ids") or []),
            "proof_receipt_sha256s": proof_hashes,
            "required_capabilities": list(raw.get("required_capabilities") or []),
            "estimated_cost_usd": float(raw.get("estimated_cost_usd", 0)),
            "risk": _text(raw, "risk", 8),
            "primary_channel": primary,
            "enhancing_channel": enhancer,
            "expected_chain": expected_chain,
            "stop_rule": _text(raw, "stop_rule", 12),
            **scores,
            "weighted_score": round(scores["evidence_fit_score"] * .4 + scores["resource_fit_score"] * .35 + scores["differentiation_score"] * .25, 3),
        })
    entry_ids = {row["entry_point_id"] for row in normalized_entry_points}
    if any(not row["category_entry_point_ids"] or not set(row["category_entry_point_ids"]).issubset(entry_ids) for row in normalized_wedges):
        raise GTMStrategyDecisionError("a wedge does not route from category entry points")
    selected = max(normalized_wedges, key=lambda row: (row["weighted_score"], row["wedge_id"]))
    rejected = [{
        "wedge_id": row["wedge_id"],
        "reason": f"Lower evidence/resource/differentiation fit ({row['weighted_score']}) than selected {selected['wedge_id']} ({selected['weighted_score']}); preserve as a rejected alternative, not an implicit fallback.",
    } for row in normalized_wedges if row["wedge_id"] != selected["wedge_id"]]
    payload = {
        "schema": SCHEMA,
        "brief": {
            "brief_id": brief_id,
            "business_model": business_model,
            "company_scale": brief.get("company_scale"),
            "lifecycle_state": brief.get("lifecycle_state"),
            "product_truth": product_truth,
            "market": dict(market),
            "audience": dict(audience),
            "budget": dict(budget),
            "objective": dict(objective),
            "evidence_receipts": evidence,
            "delivery_capability": dict(delivery),
        },
        "influence_graph": _influence_graph(business_model, audience),
        "category_entry_points": normalized_entry_points,
        "strategic_tensions": normalized_tensions,
        "why_now": normalized_why_now,
        "strategic_wedges": normalized_wedges,
        "selected_strategy": selected,
        "rejected_alternatives": rejected,
        "decision_binding": {
            "evidence_receipt_sha256s": sorted(set(selected["proof_receipt_sha256s"] + why_hashes)),
            "budget_ceiling_usd": budget["total_ceiling_usd"],
            "risks": [selected["risk"]],
            "expected_chain": selected["expected_chain"],
            "stop_rule": selected["stop_rule"],
            "primary_channel_count": 1,
            "enhancing_channel_count": 1,
        },
        "external_publish_or_spend_allowed": False,
        "observed_effect_claim_allowed": False,
        "truth_boundary": "This pack proves an evidence- and resource-bound strategic decision. It does not prove market effect and grants no external action authority.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_strategy_decision_pack(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMStrategyDecisionError("strategy decision pack seal is invalid")
    wedges = payload.get("strategic_wedges")
    rejected = payload.get("rejected_alternatives")
    if not isinstance(wedges, list) or len(wedges) < 5 or not isinstance(rejected, list) or len(rejected) != len(wedges) - 1:
        raise GTMStrategyDecisionError("strategy portfolio or rejected alternatives drifted")
    selected = payload.get("selected_strategy")
    if selected.get("primary_channel") == selected.get("enhancing_channel"):
        raise GTMStrategyDecisionError("strategy collapsed its two channels")
    if payload.get("external_publish_or_spend_allowed") is not False or payload.get("observed_effect_claim_allowed") is not False:
        raise GTMStrategyDecisionError("strategy pack escaped authority or truth boundary")


__all__ = ["GTMStrategyDecisionError", "compile_strategy_decision_pack", "verify_strategy_decision_pack"]
