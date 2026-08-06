#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_industry_profile import (
    IndustryArchetype,
    industry_archetype_contracts,
)
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
OUTPUT = ROOT / "evidence/v10/gtm-industry-profile-matrix-v1.json"
SOURCE = ROOT / "src/prooflaunch_remix/gtm_industry_profile.py"
NOW = "2026-08-02T12:00:00Z"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
    case_slug = f"{archetype}-{business_model.value}-{lifecycle.value}-{budget.value}"
    return CampaignStrategyInput(
        org_id="org-industry-matrix",
        project_id="project-industry-matrix",
        campaign_id=f"campaign-{case_slug}",
        owner="industry-matrix-owner",
        industry=industry,
        lifecycle=lifecycle,
        budget=budget,
        industry_risk=risk,
        brand=BrandConstitution(
            brand_name="ProofLaunch Matrix",
            purpose="Test industry-specific GTM operating contracts without external activation.",
            customer_promise="A traceable industry execution hypothesis.",
            voice_principles=("specific", "evidence-first", "noncausal"),
            prohibited_tactics=("spam", "fabricated testimonials", "automated publishing"),
        ),
        audience=AudienceICP(
            audience_id=f"audience-{case_slug}",
            name=f"{business_model.value} decision participants",
            business_model=business_model,
            core_problem="the buying motion and evidence threshold are not yet explicit",
            desired_outcome="make one governed next-step decision",
            buying_context="committee review" if business_model is BusinessModel.B2B else "self-serve and household review",
        ),
        objective="request one evidence review",
        offer="an industry-specific decision packet",
        landing_url=f"https://example.test/{case_slug}",
        claims=(
            ClaimEvidence(
                claim_id="claim-matrix-001",
                text="The owner supplied this synthetic matrix case for contract validation.",
                evidence_uri=f"matrix://{case_slug}/claim-matrix-001",
                evidence_sha256=_digest({"case": case_slug}),
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
    cases: list[dict[str, object]] = []
    specific_archetypes = [
        archetype
        for archetype in IndustryArchetype
        if archetype not in {IndustryArchetype.GENERAL_B2B, IndustryArchetype.GENERAL_B2C}
    ]
    archetype_market_pairs = [
        (archetype, business_model)
        for archetype in specific_archetypes
        for business_model in BusinessModel
    ] + [
        (IndustryArchetype.GENERAL_B2B, BusinessModel.B2B),
        (IndustryArchetype.GENERAL_B2C, BusinessModel.B2C),
    ]
    for archetype, business_model in archetype_market_pairs:
        contract = contracts[archetype.value]
        keywords = contract["keywords"]
        industry = (
            str(keywords[0])
            if keywords
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
                strategy = StrategyCompiler().compile(request, at=NOW)
                pack = ProductionPackCompiler().compile(request, strategy)
                profile = pack.industry_gtm_profile
                cases.append(
                    {
                        "case_id": f"{archetype.value}:{business_model.value}:{lifecycle.value}:{budget.value}",
                        "input_archetype": archetype.value,
                        "compiled_archetype": profile["industry_archetype"],
                        "business_model": business_model.value,
                        "business_model_fit": profile["business_model_fit"],
                        "lifecycle": lifecycle.value,
                        "budget": budget.value,
                        "industry_risk": risk.value,
                        "human_classification_confirmation_required": profile[
                            "human_classification_confirmation_required"
                        ],
                        "profile_sha256": profile["content_sha256"],
                        "zero_budget_engine_sha256": _digest(profile["zero_budget_growth_engine"]),
                        "conversion_unit_sha256": _digest(profile["conversion_unit"]),
                        "unit_economics_signature": _digest(profile["unit_economics_metrics"]),
                        "external_activation_executed": profile["external_activation_executed"],
                        "automatic_budget_allocation_enabled": profile[
                            "automatic_budget_allocation_enabled"
                        ],
                        "causal_revenue_claim_allowed": profile[
                            "causal_revenue_claim_allowed"
                        ],
                    }
                )
    expected_count = (len(specific_archetypes) * len(BusinessModel) + 2) * len(LifecycleStage) * len(BudgetTier)
    if len(cases) != expected_count:
        raise RuntimeError("industry matrix case count is incomplete")
    if len({row["case_id"] for row in cases}) != expected_count:
        raise RuntimeError("industry matrix case identities are not unique")
    if any(
        row["external_activation_executed"]
        or row["automatic_budget_allocation_enabled"]
        or row["causal_revenue_claim_allowed"]
        for row in cases
    ):
        raise RuntimeError("industry matrix violated an external-action or causal-claim gate")
    matrix = {
        "schema": "ProofLaunchIndustryGTMProfileMatrixV1",
        "observed_at": "2026-08-02",
        "source_sha256": sha256_file(SOURCE),
        "archetype_count": len(IndustryArchetype),
        "specific_archetype_count": len(specific_archetypes),
        "business_model_count": len(BusinessModel),
        "lifecycle_count": len(LifecycleStage),
        "budget_count": len(BudgetTier),
        "case_count": len(cases),
        "expected_case_count": expected_count,
        "zero_budget_case_count": sum(row["budget"] == BudgetTier.ZERO.value for row in cases),
        "regulated_case_count": sum(row["industry_risk"] == IndustryRisk.HIGH_REGULATION.value for row in cases),
        "business_model_mismatch_case_count": sum(not row["business_model_fit"] for row in cases),
        "human_confirmation_case_count": sum(row["human_classification_confirmation_required"] for row in cases),
        "distinct_zero_budget_engine_count": len({row["zero_budget_engine_sha256"] for row in cases}),
        "distinct_conversion_unit_count": len({row["conversion_unit_sha256"] for row in cases}),
        "distinct_unit_economics_signature_count": len({row["unit_economics_signature"] for row in cases}),
        "all_external_activation_disabled": all(not row["external_activation_executed"] for row in cases),
        "all_automatic_budget_allocation_disabled": all(not row["automatic_budget_allocation_enabled"] for row in cases),
        "all_causal_revenue_claims_disabled": all(not row["causal_revenue_claim_allowed"] for row in cases),
        "cases": cases,
        "truth_boundary": (
            "This matrix proves deterministic contract coverage and industry differentiation over synthetic cases. "
            "It does not prove universal industry fit, market quality, creative preference, production execution, "
            "causal lift, revenue, or external release."
        ),
    }
    matrix["content_sha256"] = _digest(matrix)
    atomic_write_text(OUTPUT, json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "cases": len(cases),
                "archetypes": len(IndustryArchetype),
                "zero_budget_engines": matrix["distinct_zero_budget_engine_count"],
                "unit_economics_signatures": matrix["distinct_unit_economics_signature_count"],
                "content_sha256": matrix["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
