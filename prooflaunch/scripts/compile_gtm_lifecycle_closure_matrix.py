#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_industry_profile import (
    IndustryArchetype,
    industry_archetype_contracts,
)
from prooflaunch_remix.gtm_lifecycle_closure import compile_lifecycle_closure_case
from prooflaunch_remix.gtm_production_pack import ProductionPackCompiler
from prooflaunch_remix.gtm_strategy import (
    AudienceICP,
    BrandConstitution,
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    ClaimEvidence,
    EvidenceRights,
    IndustryRisk,
    LifecycleStage,
    StrategyCompiler,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-lifecycle-closure-matrix-v1.json"
NOW = "2026-08-02T12:00:00Z"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _request(
    *,
    industry: str,
    archetype: str,
    business_model: BusinessModel,
    lifecycle: LifecycleStage,
    budget: BudgetTier,
    risk: IndustryRisk,
) -> CampaignStrategyInput:
    slug = f"{archetype}-{business_model.value}-{lifecycle.value}-{budget.value}"
    return CampaignStrategyInput(
        org_id="org-lifecycle-matrix",
        project_id="project-lifecycle-matrix",
        campaign_id=f"campaign-{slug}",
        owner="lifecycle-matrix-owner",
        industry=industry,
        lifecycle=lifecycle,
        budget=budget,
        industry_risk=risk,
        brand=BrandConstitution(
            brand_name="ProofLaunch Lifecycle Matrix",
            purpose="Exercise a full governed GTM lifecycle without external effects.",
            customer_promise="A traceable lifecycle decision contract.",
            voice_principles=("specific", "evidence-first", "noncausal"),
            prohibited_tactics=(
                "spam",
                "fabricated testimonials",
                "automated publishing",
            ),
        ),
        audience=AudienceICP(
            audience_id=f"audience-{slug}",
            name=f"{business_model.value} decision participants",
            business_model=business_model,
            core_problem="the next GTM decision lacks a shared evidence threshold",
            desired_outcome="make one governed next-cycle decision",
            buying_context=(
                "committee review"
                if business_model is BusinessModel.B2B
                else "self-serve and household review"
            ),
        ),
        objective="request one evidence review",
        offer="an industry-specific decision packet",
        landing_url=f"https://example.test/{slug}",
        claims=(
            ClaimEvidence(
                claim_id="claim-lifecycle-001",
                text="The owner supplied this synthetic case for lifecycle validation.",
                evidence_uri=f"matrix://{slug}/claim-lifecycle-001",
                evidence_sha256=_digest({"case": slug}),
                rights=EvidenceRights.OWNED,
                rights_reference="synthetic-owner-fixture",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                approved_by="matrix-claim-owner",
                specialist_approved_by=(
                    "matrix-licensed-specialist"
                    if risk is IndustryRisk.HIGH_REGULATION
                    else None
                ),
            ),
        ),
    )


def main() -> int:
    contracts = industry_archetype_contracts()
    specific = [
        item
        for item in IndustryArchetype
        if item not in {IndustryArchetype.GENERAL_B2B, IndustryArchetype.GENERAL_B2C}
    ]
    pairs = [
        (archetype, model)
        for archetype in specific
        for model in BusinessModel
    ] + [
        (IndustryArchetype.GENERAL_B2B, BusinessModel.B2B),
        (IndustryArchetype.GENERAL_B2C, BusinessModel.B2C),
    ]
    cases: list[dict[str, object]] = []
    scenario_counts: Counter[str] = Counter()
    compiler = StrategyCompiler()
    pack_compiler = ProductionPackCompiler()
    for archetype, business_model in pairs:
        contract = contracts[archetype.value]
        industry = (
            str(contract["keywords"][0])
            if contract["keywords"]
            else f"unclassified synthetic {business_model.value} category"
        )
        risk = (
            IndustryRisk.HIGH_REGULATION
            if contract["default_high_regulation"]
            else IndustryRisk.STANDARD
        )
        for lifecycle in LifecycleStage:
            for budget in BudgetTier:
                request = _request(
                    industry=industry,
                    archetype=archetype.value,
                    business_model=business_model,
                    lifecycle=lifecycle,
                    budget=budget,
                    risk=risk,
                )
                strategy = compiler.compile(request, at=NOW)
                pack = pack_compiler.compile(request, strategy)
                closure = compile_lifecycle_closure_case(
                    request,
                    strategy,
                    pack,
                    compiled_at=NOW,
                    schedule_timezone="America/New_York",
                )
                for scenario in closure["scenarios"]:
                    scenario_counts[str(scenario["scenario"])] += 1
                cases.append(closure)

    expected = (len(specific) * len(BusinessModel) + 2) * len(LifecycleStage) * len(BudgetTier)
    if len(cases) != expected or len({row["campaign_id"] for row in cases}) != expected:
        raise RuntimeError("lifecycle closure case coverage is incomplete")
    if set(scenario_counts) != {
        "qualified_positive_requires_human",
        "insufficient_sample",
        "complaint_regression",
        "negative_contribution",
        "zero_budget_spend_breach",
    } or min(scenario_counts.values()) < 50:
        raise RuntimeError("lifecycle failure-mode eval coverage is below 50 cases")
    if any(
        not all(row["capabilities"].values())
        or row["last_mile_workspace"]["artifact_count"] != 9
        or row["last_mile_workspace"]["same_evidence_spine"] is not True
        or row["last_mile_workspace"]["all_activation_disabled"] is not True
        or row["post_selection_omnichannel_probe"]["lane_count"] != 9
        or row["post_selection_omnichannel_probe"][
            "same_creative_system_across_lanes"
        ]
        is not True
        or row["post_selection_omnichannel_probe"][
            "same_evidence_spine_across_lanes"
        ]
        is not True
        or row["post_selection_omnichannel_probe"][
            "all_external_actions_disabled"
        ]
        is not True
        or row["external_actions_executed"] != 0
        or row["four_a_effect_proven"] is not False
        or row["causal_revenue_proven"] is not False
        for row in cases
    ):
        raise RuntimeError("lifecycle matrix violated a capability or truth gate")

    local_pack_path = (
        ROOT
        / "evidence/v10/local-campaign-pack-v1/delivery-v5/campaign-pack-manifest.json"
    )
    memory_demo_path = ROOT / "evidence/v10/gtm-revenue-memory-demo.json"
    local_pack = json.loads(local_pack_path.read_text(encoding="utf-8"))
    memory_demo = json.loads(memory_demo_path.read_text(encoding="utf-8"))
    matrix: dict[str, object] = {
        "schema": "ProofLaunchGTMLifecycleClosureMatrixV1",
        "observed_at": "2026-08-02",
        "autonomy_level": "L2_deterministic_workflow_with_bounded_node_loops",
        "case_count": len(cases),
        "expected_case_count": expected,
        "scenario_count": sum(scenario_counts.values()),
        "named_failure_mode_count": len(scenario_counts),
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "minimum_cases_per_failure_mode": min(scenario_counts.values()),
        "business_model_count": len(BusinessModel),
        "lifecycle_count": len(LifecycleStage),
        "budget_count": len(BudgetTier),
        "industry_archetype_count": len(IndustryArchetype),
        "zero_budget_case_count": sum(
            row["budget"] == BudgetTier.ZERO.value for row in cases
        ),
        "all_ten_lifecycle_capabilities_connected": all(
            len(row["capabilities"]) == 10 and all(row["capabilities"].values())
            for row in cases
        ),
        "all_zero_budget_paid_channels_excluded": all(
            row["budget"] != BudgetTier.ZERO.value
            or row["zero_budget_paid_channels_excluded"] is True
            for row in cases
        ),
        "all_positive_paths_require_human_review": all(
            next(
                item
                for item in row["scenarios"]
                if item["scenario"] == "qualified_positive_requires_human"
            )["human_review_required"]
            is True
            for row in cases
        ),
        "all_external_actions_disabled": all(
            row["external_actions_executed"] == 0 for row in cases
        ),
        "campaign_workspace_artifact_count": 9,
        "all_campaign_workspaces_same_evidence_spine": all(
            row["last_mile_workspace"]["same_evidence_spine"] is True
            for row in cases
        ),
        "all_campaign_workspace_activations_disabled": all(
            row["last_mile_workspace"]["all_activation_disabled"] is True
            and row["last_mile_workspace"]["external_actions_executed"] == 0
            for row in cases
        ),
        "post_selection_omnichannel_lane_count": 9,
        "all_post_selection_campaign_identities_bound": all(
            row["post_selection_omnichannel_probe"]["campaign_id"]
            == row["campaign_id"]
            and row["post_selection_omnichannel_probe"]["strategy_id"]
            == row["strategy_id"]
            for row in cases
        ),
        "all_post_selection_creative_systems_connected": all(
            row["post_selection_omnichannel_probe"][
                "same_creative_system_across_lanes"
            ]
            is True
            for row in cases
        ),
        "all_post_selection_evidence_spines_connected": all(
            row["post_selection_omnichannel_probe"][
                "same_evidence_spine_across_lanes"
            ]
            is True
            for row in cases
        ),
        "all_post_selection_external_actions_disabled": all(
            row["post_selection_omnichannel_probe"][
                "all_external_actions_disabled"
            ]
            is True
            for row in cases
        ),
        "post_selection_human_observations": 0,
        "cross_device_memory_evidence": {
            "receipt_path": str(memory_demo_path.relative_to(ROOT)),
            "receipt_sha256": sha256_file(memory_demo_path),
            "content_sha256": memory_demo["content_sha256"],
            "data_class": memory_demo["data_class"],
            "external_publish_executed": memory_demo["external_publish_executed"],
        },
        "local_multimodal_delivery_evidence": {
            "manifest_path": str(local_pack_path.relative_to(ROOT)),
            "manifest_sha256": sha256_file(local_pack_path),
            "content_sha256": local_pack["content_sha256"],
            "source_model": local_pack["source_generation"]["model"],
            "source_accelerator": local_pack["source_generation"]["accelerator"],
            "mechanical_ready": local_pack["quality_gates"][
                "mechanical_campaign_pack_ready"
            ],
            "product_admission_passed": local_pack["quality_gates"][
                "product_admission_passed"
            ],
        },
        "cases": cases,
        "production_outcomes_observed": 0,
        "human_blind_reviews_observed": 0,
        "four_a_effect_proven": False,
        "top1_claim_eligible": False,
        "truth_boundary": (
            "This matrix proves deterministic cross-capability integration and failure "
            "handling on synthetic fixtures. It does not prove live reach, publication, "
            "production outcomes, annual breakout performance, causal revenue, human "
            "preference, 4A quality, Top-1 standing or Radeon execution."
        ),
    }
    matrix["content_sha256"] = _digest(matrix)
    atomic_write_text(
        OUTPUT,
        json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "cases": len(cases),
                "scenarios": matrix["scenario_count"],
                "minimum_per_failure_mode": matrix[
                    "minimum_cases_per_failure_mode"
                ],
                "content_sha256": matrix["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
