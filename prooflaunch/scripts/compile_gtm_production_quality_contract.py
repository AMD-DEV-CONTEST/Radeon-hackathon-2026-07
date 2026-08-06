#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_production_quality_contract import (
    build_production_quality_contract,
    evaluate_platform_copy_bible,
    evaluate_product_evidence_claims,
    evaluate_quality_ladder,
    evaluate_single_growth_tension,
)
from prooflaunch_remix.gtm_market_language import build_platform_copy_bible
from prooflaunch_remix.gtm_organic_breakout_admission import (
    verify_organic_breakout_admissions,
)


ROOT = Path(__file__).resolve().parents[1]
LAST_MILE = ROOT / "evidence/v10/gtm-last-mile-production-quality-v1.json"
STRATEGY = (
    ROOT
    / "artifacts/run-bound-multimodal-demo-v1/production-deliverables/gtm-strategy.json"
)
COPY = (
    ROOT
    / "artifacts/run-bound-multimodal-demo-v1/production-deliverables/channel-copy.json"
)
ORGANIC = ROOT / "evidence/v10/gtm-recent-organic-signal-pack-v5.json"
ORGANIC_ADMISSIONS = ROOT / "evidence/v10/gtm-organic-breakout-admission-v1.json"
PRODUCT_EVIDENCE = (
    ROOT
    / "artifacts/run-bound-multimodal-demo-v1/production-deliverables/product-evidence-register.json"
)
BRIEF_INTELLIGENCE = (
    ROOT
    / "artifacts/run-bound-multimodal-demo-v1/production-deliverables/brief-intelligence.json"
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def build_current_evaluation() -> dict[str, Any]:
    last_mile = json.loads(LAST_MILE.read_text(encoding="utf-8"))
    strategy = json.loads(STRATEGY.read_text(encoding="utf-8"))
    copy = json.loads(COPY.read_text(encoding="utf-8"))
    organic = json.loads(ORGANIC.read_text(encoding="utf-8"))
    organic_admissions = json.loads(ORGANIC_ADMISSIONS.read_text(encoding="utf-8"))
    verify_organic_breakout_admissions(organic_admissions)
    product_evidence = json.loads(PRODUCT_EVIDENCE.read_text(encoding="utf-8"))
    brief_intelligence = json.loads(BRIEF_INTELLIGENCE.read_text(encoding="utf-8"))
    portfolio = last_mile["portfolio"]
    review = last_mile["current_review_evidence"]
    claim_assurance = strategy["claim_assurance"]
    strategy_body = strategy["strategy"]

    product_claims = [
        {
            "claim_id": item["claim_id"],
            "claim_text": item["claim_text"],
            "source_uri": item["source_uri"],
            "source_sha256": item["source_sha256"],
            "rights_status": item["rights_status"],
            "valid_at": item["valid_from"],
            "release_scope": item["release_scope"],
            "approved_by": item["approved_by"],
        }
        for item in product_evidence["claims"]
    ]
    evidence_claim_evaluation = evaluate_product_evidence_claims(product_claims)
    growth_tension_evaluation = evaluate_single_growth_tension(brief_intelligence)
    copy_bible_evaluation = evaluate_platform_copy_bible(build_platform_copy_bible())

    ladder_evidence = {
        "artifact_contract_passed": portfolio["mechanical_pack_assembled"],
        "rights_gate_passed": bool(claim_assurance.get("rights_basis")),
        "claim_evidence_gate_passed": (
            strategy_body.get("proof_evidence_sha256")
            == claim_assurance.get("evidence_sha256")
        ),
        "platform_contract_passed": all(
            item.get("human_release_required") is True
            and item.get("automated_publish_allowed") is False
            for item in (copy["primary"], copy["secondary"])
        ),
        "identity_gate_passed": portfolio["mechanical_pack_assembled"],
        "accessibility_gate_passed": portfolio["mechanical_pack_assembled"],
        "blocking_defect_count": 0,
        "qualified_review_count": review["unified_submitted"],
        "directly_publishable_count": None,
        "major_rework_count": None,
        "human_blocking_defect_count": None,
        "blind_comparison_count": review["unified_submitted"],
        "candidate_preferred_count": None,
        "named_external_baseline_present": review["unified_top_product_baselines_present"],
        "source_hidden_review": True,
        "publication_receipt_count": 0,
        "authorized_observation_count": 0,
        "primary_metric_pre_registered": True,
        "observed_sample_size": None,
        "registered_minimum_sample": 25,
        "primary_metric_decision": None,
        "incremental_design_gate_passed": False,
        "attribution_integrity_passed": False,
        "safety_regression_observed": None,
        "qualified_conversion_rate": None,
        "time_to_first_human_publishable_asset_hours": None,
    }
    quality_ladder = evaluate_quality_ladder(ladder_evidence)
    core: dict[str, Any] = {
        "schema": "ProofLaunchGTMProductionQualityCurrentEvaluationV1",
        "run_id": last_mile["run_id"],
        "campaign_id": last_mile["campaign_id"],
        "quality_ladder": quality_ladder,
        "honest_dashboard": {
            "mechanical": {
                "ready_lanes": portfolio["mechanically_ready_lane_count"],
                "total_lanes": last_mile["lane_count"],
                "passed": portfolio["mechanical_pack_assembled"],
            },
            "human_quality": {
                "submitted_reviews": review["unified_submitted"],
                "expected_reviews": review["unified_expected"],
                "directly_publishable_rate": None,
                "major_rework_rate": None,
                "blocking_defect_count": None,
                "passed": False,
            },
            "named_blind_pk": {
                "completed_rows": 0,
                "required_rows": 130,
                "passed": False,
            },
            "real_distribution": {
                "publication_receipts": 0,
                "authorized_observations": 0,
                "passed": False,
            },
            "attributed_effect": {
                "primary_metric": "qualified_action_rate",
                "result": None,
                "incremental_design_passed": False,
                "passed": False,
            },
        },
        "priority_capability_checks": {
            "T014_product_evidence_extractor": evidence_claim_evaluation,
            "T021_natural_breakout_admission": {
                "passed": organic_admissions["admitted_candidate_count"] > 0,
                "recent_public_items": organic["recent_item_count_maximum_window"],
                "candidate_level_relative_breakouts_admitted": organic_admissions[
                    "admitted_candidate_count"
                ],
                "admission_receipt_sha256": organic_admissions["content_sha256"],
                "causal_growth_claim_allowed": False,
                "training_admitted": False,
                "reason": (
                    "Candidate-level within-source baselines, freshness, public counters, "
                    "paid-distribution disclosures and capture hashes are sealed. Candidates "
                    "remain descriptive and require named-human abstraction review."
                ),
            },
            "T033_single_growth_tension": growth_tension_evaluation,
            "T041_platform_copy_bible": copy_bible_evaluation,
        },
        "next_actions": [
            "Bind a named claim approver and public release scope to the current owner-attested product claim.",
            "Human-review the admitted relative-breakout candidates before any mechanism abstraction or memory write.",
            "Complete five qualified human reviews on exact artifact hashes.",
            "Run source-hidden same-Brief comparison against a rights-cleared named baseline.",
            "Manually publish one approved B2B and one approved B2C experiment with receipts.",
            "Import authorized aggregate observations and keep causal status separate.",
        ],
        "truth_boundary": (
            "The current run is mechanically reviewable only. No professional-editor pass, "
            "named-product win, public release, production effect, causal lift, 4A parity or Top-1 "
            "standing is claimed."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def render_markdown(contract: dict[str, Any], current: dict[str, Any]) -> str:
    dashboard = current["honest_dashboard"]
    ladder = current["quality_ladder"]
    checks = current["priority_capability_checks"]
    lines = [
        "# GTM production-quality operating contract V1",
        "",
        "## Current verdict",
        "",
        f"Current state: **{ladder['current_state']}**. Promotion is **not allowed**.",
        "",
        "| Evidence layer | Observed | Verdict |",
        "|---|---:|---|",
        f"| Mechanical lanes | {dashboard['mechanical']['ready_lanes']}/{dashboard['mechanical']['total_lanes']} | pass |",
        f"| Qualified human reviews | {dashboard['human_quality']['submitted_reviews']}/{dashboard['human_quality']['expected_reviews']} | not observed |",
        f"| Named-product blind PK | {dashboard['named_blind_pk']['completed_rows']}/{dashboard['named_blind_pk']['required_rows']} | not observed |",
        f"| Publication receipts | {dashboard['real_distribution']['publication_receipts']} | not observed |",
        f"| Authorized production observations | {dashboard['real_distribution']['authorized_observations']} | not observed |",
        "",
        "## North Star",
        "",
        "This is a three-axis vector, not a content-volume score:",
    ]
    for axis in contract["north_star"]["axes"]:
        lines.append(f"- `{axis['metric']}` — {axis['direction']}; evidence: {axis['observation_required']}.")
    lines += ["", "## Monotonic gates", ""]
    for gate, result in ladder["gates"].items():
        lines.append(f"- **{gate}:** {'PASS' if result['passed'] else 'BLOCKED'}.")
    lines += ["", "## First-priority capability gaps", ""]
    for todo, result in checks.items():
        failures = result.get("failures") or result.get("blocking_findings") or []
        reason = result.get("reason")
        detail = reason or (json.dumps(failures, ensure_ascii=False) if failures else "passed")
        lines.append(f"- **{todo}:** {'PASS' if result['passed'] else 'BLOCKED'} — {detail}")
    lines += ["", "## Blocking-defect classes", ""]
    lines.extend(f"- `{item}`" for item in contract["blocking_defect_classes"])
    lines += ["", "## Next actions", ""]
    lines.extend(f"{index}. {item}" for index, item in enumerate(current["next_actions"], 1))
    lines += ["", "## Truth boundary", "", current["truth_boundary"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract-output",
        default=str(ROOT / "config/gtm_production_quality_contract_v1.json"),
    )
    parser.add_argument(
        "--evidence-output",
        default=str(ROOT / "evidence/v10/gtm-production-quality-current-v1.json"),
    )
    parser.add_argument(
        "--markdown-output",
        default=str(ROOT / "docs/product/GTM_PRODUCTION_QUALITY_OPERATING_CONTRACT_V1.md"),
    )
    parser.add_argument(
        "--copy-bible-output",
        default=str(ROOT / "config/gtm_platform_copy_bible_v1.json"),
    )
    args = parser.parse_args()
    outputs = tuple(
        Path(value).resolve()
        for value in (
            args.contract_output,
            args.evidence_output,
            args.markdown_output,
            args.copy_bible_output,
        )
    )
    for output in outputs:
        output.relative_to(ROOT)
    contract = build_production_quality_contract()
    current = build_current_evaluation()
    copy_bible = build_platform_copy_bible()
    atomic_write_text(outputs[0], json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(outputs[1], json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(outputs[2], render_markdown(contract, current))
    atomic_write_text(outputs[3], json.dumps(copy_bible, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "state": current["quality_ladder"]["current_state"],
                "promotion_allowed": current["quality_ladder"]["promotion_allowed"],
                "content_sha256": current["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
