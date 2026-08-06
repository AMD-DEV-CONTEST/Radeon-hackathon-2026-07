from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from prooflaunch_remix.gtm_market_language import (
    B2B_CATEGORY_IDS,
    B2B_ROLE_IDS,
    B2C_CATEGORY_IDS,
    B2C_STATE_IDS,
    compile_market_language_contract,
)
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
    ProductSurface,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "evidence/v10/gtm-market-language-matrix-v1.json"
PLATFORMS = ("linkedin", "tiktok", "instagram", "youtube", "reddit", "x")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _template() -> CampaignStrategyInput:
    return CampaignStrategyInput(
        org_id="org-market-language",
        project_id="project-market-language",
        campaign_id="market-language-matrix",
        owner="matrix-compiler",
        industry="owner-declared industry",
        lifecycle=LifecycleStage.LAUNCH,
        budget=BudgetTier.ZERO,
        industry_risk=IndustryRisk.STANDARD,
        brand=BrandConstitution(
            brand_name="ProofLaunch",
            purpose="Make GTM decisions inspectable.",
            customer_promise="One evidence-bound next step.",
            voice_principles=("specific", "calm", "distinctive"),
            prohibited_tactics=("copied expression", "fabricated proof"),
        ),
        audience=AudienceICP(
            audience_id="matrix-audience",
            name="one owner-declared audience",
            business_model=BusinessModel.B2B,
            core_problem="generic content does not resolve a real decision",
            desired_outcome="receive one useful, original and evidence-bound next step",
            buying_context="owner-declared decision context",
        ),
        objective="earn a qualified next step",
        offer="one inspectable proof object",
        landing_url="https://example.test/market-language",
        claims=(
            ClaimEvidence(
                claim_id="claim-market-language",
                text="This matrix is a deterministic contract fixture.",
                evidence_uri="project://market-language/matrix#fixture",
                evidence_sha256="b" * 64,
                rights=EvidenceRights.OWNED,
                rights_reference="fixture-owner",
                valid_from="2026-08-03T00:00:00Z",
                valid_until=None,
                approved_by="fixture-owner",
            ),
        ),
    )


def compile_market_language_matrix() -> dict[str, Any]:
    template = _template()
    rows: list[dict[str, Any]] = []
    combinations = (
        (BusinessModel.B2B, B2B_CATEGORY_IDS, B2B_ROLE_IDS, ProductSurface.WEB_AGENT),
        (BusinessModel.B2C, B2C_CATEGORY_IDS, B2C_STATE_IDS, ProductSurface.MOBILE_APP),
    )
    for business_model, categories, roles, surface in combinations:
        audience = replace(template.audience, business_model=business_model)
        for category in categories:
            for role in roles:
                for lifecycle in LifecycleStage:
                    for budget in BudgetTier:
                        for platform in PLATFORMS:
                            request = replace(
                                template,
                                audience=audience,
                                campaign_id=(
                                    f"ml-{business_model.value}-{category}-{role}-"
                                    f"{lifecycle.value}-{budget.value}-{platform}"
                                ),
                                product_category=category,
                                product_surface=surface,
                                audience_role=role,
                                lifecycle=lifecycle,
                                budget=budget,
                                distribution_platform=platform,
                            )
                            contract = compile_market_language_contract(request)
                            rows.append(
                                {
                                    "case_id": request.campaign_id,
                                    "business_model": business_model.value,
                                    "product_category": category,
                                    "primary_audience_role": role,
                                    "lifecycle": lifecycle.value,
                                    "budget": budget.value,
                                    "distribution_platform": platform,
                                    "product_surface": surface.value,
                                    "language_signature_sha256": contract[
                                        "language_signature_sha256"
                                    ],
                                    "contract_sha256": contract["content_sha256"],
                                    "category_language_shape": contract[
                                        "category_contract"
                                    ]["language_shape"],
                                    "audience_language_shape": contract[
                                        "primary_audience_contract"
                                    ]["language_shape"],
                                    "primary_formats": contract[
                                        "platform_translation"
                                    ]["primary_formats"],
                                    "paid_activation_allowed": contract[
                                        "budget_contract"
                                    ]["paid_activation_allowed"],
                                    "owner_confirmation_required": contract[
                                        "audience_asset_contract"
                                    ]["owner_confirmation_required"],
                                    "external_action_count": contract[
                                        "external_action_count"
                                    ],
                                }
                            )
    expected_b2b = (
        len(B2B_CATEGORY_IDS)
        * len(B2B_ROLE_IDS)
        * len(LifecycleStage)
        * len(BudgetTier)
        * len(PLATFORMS)
    )
    expected_b2c = (
        len(B2C_CATEGORY_IDS)
        * len(B2C_STATE_IDS)
        * len(LifecycleStage)
        * len(BudgetTier)
        * len(PLATFORMS)
    )
    signatures = {row["language_signature_sha256"] for row in rows}
    payload: dict[str, Any] = {
        "schema": "ProofLaunchMarketLanguageMatrixV1",
        "as_of": "2026-08-03",
        "reference_surface_policy": {
            "b2b": ProductSurface.WEB_AGENT.value,
            "b2c": ProductSurface.MOBILE_APP.value,
            "supported_product_surfaces": [item.value for item in ProductSurface],
            "surface_is_runtime_bound_but_not_multiplied_into_this_matrix": True,
        },
        "coverage": {
            "b2b_category_count": len(B2B_CATEGORY_IDS),
            "b2b_primary_role_count": len(B2B_ROLE_IDS),
            "b2b_case_count": expected_b2b,
            "b2c_category_count": len(B2C_CATEGORY_IDS),
            "b2c_primary_state_count": len(B2C_STATE_IDS),
            "b2c_case_count": expected_b2c,
            "lifecycle_count": len(LifecycleStage),
            "budget_count": len(BudgetTier),
            "platform_count": len(PLATFORMS),
            "total_case_count": len(rows),
            "distinct_language_signature_count": len(signatures),
            "zero_budget_paid_activation_count": sum(
                1
                for row in rows
                if row["budget"] == BudgetTier.ZERO.value
                and row["paid_activation_allowed"]
            ),
            "missing_owner_confirmation_count": sum(
                1 for row in rows if not row["owner_confirmation_required"]
            ),
            "automatic_external_action_count": sum(
                int(row["external_action_count"]) for row in rows
            ),
        },
        "case_rows": rows,
        "truth_boundary": (
            "This matrix proves deterministic differentiation and safety across declared "
            "contexts. It does not prove creative preference, organic breakout, acquisition, "
            "conversion, revenue causality or superiority over a named product."
        ),
    }
    if len(rows) != expected_b2b + expected_b2c:
        raise RuntimeError("market-language matrix coverage is incomplete")
    if len(signatures) != len(rows):
        raise RuntimeError("market-language signatures are not context-distinct")
    if payload["coverage"]["zero_budget_paid_activation_count"] != 0:
        raise RuntimeError("market-language matrix enabled zero-budget paid activation")
    if payload["coverage"]["missing_owner_confirmation_count"] != 0:
        raise RuntimeError("market-language matrix lost owner confirmation")
    if payload["coverage"]["automatic_external_action_count"] != 0:
        raise RuntimeError("market-language matrix executed an external action")
    payload["content_sha256"] = _digest(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = compile_market_language_matrix()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "case_count": payload["coverage"]["total_case_count"],
                "distinct_language_signature_count": payload["coverage"][
                    "distinct_language_signature_count"
                ],
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
