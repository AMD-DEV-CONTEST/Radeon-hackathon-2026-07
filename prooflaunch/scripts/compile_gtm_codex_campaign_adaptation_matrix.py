#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.gtm_codex_campaign_work_order import (  # noqa: E402
    MATRIX_SCHEMA,
    compile_codex_campaign_generation_protocol,
    compile_codex_campaign_work_order,
    verify_codex_campaign_adaptation_matrix,
)
from prooflaunch_remix.gtm_industry_profile import (  # noqa: E402
    bind_industry_profile_strategy,
    compile_industry_gtm_profile,
    industry_archetype_contracts,
)
from prooflaunch_remix.gtm_strategy import (  # noqa: E402
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
    StrategyCompiler,
)


INDUSTRY_MATRIX = ROOT / "evidence/v10/gtm-industry-profile-matrix-v1.json"
OUTPUT = ROOT / "evidence/v10/gtm-codex-campaign-adaptation-matrix-v1.json"
NOW = "2026-08-03T12:00:00Z"


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _product_surface(archetype: str, model: BusinessModel) -> ProductSurface:
    if archetype in {"hardware_iot", "manufacturing_industrial", "cpg_retail"}:
        return ProductSurface.PHYSICAL_PRODUCT
    if archetype in {"professional_services", "local_services", "nonprofit_public"}:
        return ProductSurface.SERVICE
    if model is BusinessModel.B2C and archetype in {
        "consumer_app",
        "media_gaming",
        "travel_hospitality",
    }:
        return ProductSurface.MOBILE_APP
    return ProductSurface.WEB_APP


def _request(
    *,
    archetype: str,
    contract: dict[str, Any],
    business_model: BusinessModel,
    lifecycle: LifecycleStage,
    budget: BudgetTier,
    risk: IndustryRisk,
) -> CampaignStrategyInput:
    slug = f"{archetype}-{business_model.value}-{lifecycle.value}-{budget.value}"
    industry = str(contract["keywords"][0]) if contract["keywords"] else f"general {business_model.value}"
    decision_unit = ", ".join(str(item) for item in contract["decision_unit"])
    conversion_unit = str(contract["conversion_unit"])
    return CampaignStrategyInput(
        org_id="org-codex-adaptation-matrix",
        project_id="project-codex-adaptation-matrix",
        campaign_id=f"campaign-{slug}",
        owner="named-human-campaign-owner-required",
        industry=industry,
        lifecycle=lifecycle,
        budget=budget,
        industry_risk=risk,
        brand=BrandConstitution(
            brand_name=f"Owner Brand {archetype.replace('_', ' ').title()}",
            purpose=(
                "Compile an industry-native campaign hypothesis while preserving exact owner evidence and a human release boundary."
            ),
            customer_promise="Make one governed next-step decision from an inspectable proof object.",
            voice_principles=(
                "industry-native",
                "specific",
                "human",
                "evidence-first",
                "noncausal",
            ),
            prohibited_tactics=(
                "fabricated customer stories",
                "copied competitor expression",
                "hidden sponsorship or affiliation",
                "manipulative urgency",
                "automated external publishing",
            ),
        ),
        audience=AudienceICP(
            audience_id=f"audience-{slug}",
            name=f"Primary {business_model.value.upper()} decision unit: {decision_unit}",
            business_model=business_model,
            core_problem=(
                f"The team has not yet proven how to move through this buying motion: {contract['buying_motion']}"
            ),
            desired_outcome=f"Reach this verified conversion unit: {conversion_unit}",
            buying_context=str(contract["buying_motion"]),
        ),
        objective=f"request one evidence-bound decision toward {conversion_unit}",
        offer=f"an industry-native decision packet for {archetype.replace('_', ' ')}",
        landing_url=f"https://example.test/codex-adaptation/{slug}",
        claims=(
            ClaimEvidence(
                claim_id=f"claim-{_digest({'slug': slug})[:16]}",
                text=(
                    "The owner supplied this synthetic adaptation case to validate a campaign-generation work-order contract."
                ),
                evidence_uri=f"fixture://codex-adaptation/{slug}",
                evidence_sha256=_digest({"fixture": slug, "class": "synthetic_contract_case"}),
                rights=EvidenceRights.OWNED,
                rights_reference="synthetic-owner-fixture",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                approved_by="named-matrix-claim-owner",
                specialist_approved_by=(
                    "named-licensed-specialist"
                    if risk is IndustryRisk.HIGH_REGULATION
                    else None
                ),
            ),
        ),
        product_category=archetype.replace("_", " "),
        product_surface=_product_surface(archetype, business_model),
        distribution_platform="deterministic_channel_portfolio",
        audience_role=str(contract["decision_unit"][0]),
        schedule_timezone="America/New_York",
    )


def compile_from_files() -> dict[str, Any]:
    source_matrix = json.loads(INDUSTRY_MATRIX.read_text(encoding="utf-8"))
    unsigned_source = dict(source_matrix)
    source_sha = unsigned_source.pop("content_sha256", None)
    if source_sha != _digest(unsigned_source) or source_matrix.get("case_count") != 456:
        raise RuntimeError("industry profile matrix source is invalid")
    contracts = industry_archetype_contracts()
    protocol = compile_codex_campaign_generation_protocol()
    work_orders: list[dict[str, Any]] = []
    case_bindings: list[dict[str, Any]] = []
    for source_case in source_matrix["cases"]:
        archetype = str(source_case["input_archetype"])
        contract = contracts[archetype]
        business_model = BusinessModel(str(source_case["business_model"]))
        lifecycle = LifecycleStage(str(source_case["lifecycle"]))
        budget = BudgetTier(str(source_case["budget"]))
        risk = IndustryRisk(str(source_case["industry_risk"]))
        request = _request(
            archetype=archetype,
            contract=contract,
            business_model=business_model,
            lifecycle=lifecycle,
            budget=budget,
            risk=risk,
        )
        strategy = StrategyCompiler().compile(request, at=NOW)
        profile = compile_industry_gtm_profile(
            request,
            source_strategy_sha256=_digest(strategy),
        )
        profile = bind_industry_profile_strategy(
            profile,
            strategy_id=strategy.strategy_id,
        )
        work_order = compile_codex_campaign_work_order(
            request,
            strategy,
            profile,
            protocol=protocol,
        )
        work_orders.append(work_order)
        case_bindings.append(
            {
                "case_id": source_case["case_id"],
                "source_profile_sha256": source_case["profile_sha256"],
                "work_order_id": work_order["work_order_id"],
                "work_order_sha256": work_order["content_sha256"],
            }
        )

    matrix: dict[str, Any] = {
        "schema": MATRIX_SCHEMA,
        "observed_at": "2026-08-03",
        "source_industry_matrix_sha256": source_matrix["content_sha256"],
        "source_module_sha256": sha256_file(
            ROOT / "src/prooflaunch_remix/gtm_codex_campaign_work_order.py"
        ),
        "generation_protocol": protocol,
        "generation_protocol_sha256": protocol["content_sha256"],
        "industry_archetype_count": source_matrix["archetype_count"],
        "business_model_count": source_matrix["business_model_count"],
        "lifecycle_count": source_matrix["lifecycle_count"],
        "budget_count": source_matrix["budget_count"],
        "case_count": len(work_orders),
        "work_order_count": len(work_orders),
        "zero_budget_work_order_count": sum(
            row["immutable_brief"]["budget"] == "zero" for row in work_orders
        ),
        "regulated_work_order_count": sum(
            row["immutable_brief"]["industry_risk"] == "high_regulation"
            for row in work_orders
        ),
        "human_classification_confirmation_required_count": sum(
            row["industry_operating_contract"][
                "human_classification_confirmation_required"
            ]
            for row in work_orders
        ),
        "distinct_primary_channel_count": len(
            {row["strategy_contract"]["primary_channel"] for row in work_orders}
        ),
        "overlapping_platform_work_order_count": sum(
            bool(row["strategy_contract"]["overlapping_platform_surfaces"])
            for row in work_orders
        ),
        "fully_overlapping_channel_surface_work_order_count": sum(
            set(row["strategy_contract"]["secondary_platform_surfaces"])
            <= set(row["strategy_contract"]["primary_platform_surfaces"])
            for row in work_orders
        ),
        "empty_secondary_platform_surface_work_order_count": sum(
            not row["strategy_contract"]["secondary_platform_surfaces"]
            for row in work_orders
        ),
        "surface_contract_count_per_work_order": 13,
        "lifecycle_phase_contract_count_per_work_order": 4,
        "email_contract_count_per_work_order": 4,
        "multimodal_direction_contract_count_per_work_order": 3,
        "search_geo_contract_count_per_work_order": 7,
        "flight_slot_contract_count_per_work_order": 7,
        "experiment_contract_count_per_work_order": 4,
        "model_call_count": 0,
        "candidate_output_count": 0,
        "human_review_completed_count": 0,
        "release_eligible_count": 0,
        "external_publish_executed_count": 0,
        "production_effect_observed_count": 0,
        "causal_effect_claim_allowed_count": 0,
        "case_bindings": case_bindings,
        "work_orders": work_orders,
        "truth_boundary": (
            "This matrix proves that all 456 synthetic industry, business-model, lifecycle and budget cases compile into bounded Codex-ready campaign work orders. "
            "It does not prove model inference, generated execution quality, universal fit, human preference, publication, causal lift, revenue or named-product superiority."
        ),
    }
    matrix["content_sha256"] = _digest(matrix)
    verify_codex_campaign_adaptation_matrix(matrix)
    return matrix


def main() -> int:
    matrix = compile_from_files()
    atomic_write_text(
        OUTPUT,
        json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "content_sha256": matrix["content_sha256"],
                "work_orders": matrix["work_order_count"],
                "zero_budget": matrix["zero_budget_work_order_count"],
                "regulated": matrix["regulated_work_order_count"],
                "primary_channels": matrix["distinct_primary_channel_count"],
                "model_calls": matrix["model_call_count"],
                "candidate_outputs": matrix["candidate_output_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
