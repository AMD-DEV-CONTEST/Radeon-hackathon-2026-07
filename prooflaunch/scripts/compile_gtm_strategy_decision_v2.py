#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_strategy_decision_v2 import compile_strategy_decision_pack, verify_strategy_decision_pack


ROOT = Path(__file__).resolve().parents[1]
H = hashlib.sha256(b"synthetic-strategy-regression-evidence").hexdigest()


def brief(business_model: str) -> dict:
    receipt = {"source_url": "https://example.com/public-proof", "content_sha256": H, "claim_scope": "synthetic regression proof binding only"}
    entry_points = [{"entry_point_id": f"cep-{i}", "situation_trigger": f"Decision situation trigger {i}", "customer_job": f"Resolve evidence-sensitive job {i}", "evidence_receipt_sha256s": [H]} for i in range(3)]
    wedges = [{
        "wedge_id": f"wedge-{i}", "thesis": f"Distinct strategic thesis {i} grounded in the proof and category entry point.",
        "category_entry_point_ids": [f"cep-{i % 3}"], "proof_receipt_sha256s": [H],
        "required_capabilities": ["research", "proof production"], "estimated_cost_usd": 100 + i,
        "risk": "The evidence may not transfer to the target segment.", "primary_channel": "linkedin" if business_model == "b2b" else "tiktok",
        "enhancing_channel": "owned_blog_newsletter", "expected_chain": ["qualified attention", "proof consumption", "activation"],
        "stop_rule": "Stop if qualified proof consumption does not improve during the fixed test window.",
        "evidence_fit_score": 70 + i, "resource_fit_score": 75 - i, "differentiation_score": 65 + i,
    } for i in range(5)]
    return {
        "brief_id": f"synthetic-{business_model}-brief", "business_model": business_model, "company_scale": "small", "lifecycle_state": "launch",
        "product_truth": [{"statement": "The product creates an inspectable proof object before a release decision.", "evidence_receipt_sha256s": [H]}, {"statement": "External publishing and spend remain under human authority.", "evidence_receipt_sha256s": [H]}],
        "market": {"primary_market": "north_america", "competition_pressure_index": 60},
        "audience": {"primary_segment": "evidence-sensitive operators", "job_to_be_done": "make a governed release decision"},
        "budget": {"tier": "low_budget", "total_ceiling_usd": 1000},
        "objective": {"primary_metric": "qualified proof consumption", "target_direction": "increase", "horizon_days": 28},
        "evidence_receipts": [receipt], "delivery_capability": {"content_hours_per_week": 10, "approvers": ["owner"], "production_capabilities": ["text", "image"]},
        "category_entry_points": entry_points,
        "strategic_tensions": {"stale_assumption": "More content automatically creates more demand.", "hidden_cost": "Generic output spends scarce review time without earning trust.", "unmet_job": "Teams need proof that can survive internal scrutiny.", "cultural_tension": "AI abundance increases skepticism toward polished claims.", "ownable_narrative": "Make the claim inspectable before asking the market to trust it."},
        "why_now": {"as_of_date": "2026-08-05", "technology": "Generation is abundant while verification remains scarce.", "economic": "Teams must show efficiency under tighter acquisition economics.", "regulatory": "Claims and data handling face stronger review expectations.", "cultural": "Audiences increasingly reject generic AI expression.", "platform": "Platforms reward useful native participation over duplicate distribution.", "evidence_receipt_sha256s": [H]},
        "strategic_wedges": wedges,
    }


def main() -> int:
    packs = [compile_strategy_decision_pack(brief(model)) for model in ("b2b", "b2c")]
    for pack in packs: verify_strategy_decision_pack(pack)
    payload = {"schema": "ProofLaunchGTMStrategyDecisionRegressionBundleV2", "synthetic_pack_count": len(packs), "packs": packs, "truth_boundary": "Synthetic packs prove contract branching, not market effect."}
    payload["content_sha256"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    output = ROOT / "evidence/v10/gtm-strategy-decision-packs-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "synthetic_pack_count": len(packs), "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
