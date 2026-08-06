#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_production_pack import ProductionPackCompiler
from prooflaunch_remix.gtm_strategy import (
    BudgetTier,
    BusinessModel,
    LifecycleStage,
    ProductSurface,
    StrategyCompiler,
)
from prooflaunch_remix.gtm_text_challenger import verify_text_challenger_plan
from scripts.compile_gtm_market_language_matrix import _template


OUTPUT = ROOT / "evidence/v10/gtm-craft-handoff-matrix-v1.json"
AT = "2026-08-03T12:00:00Z"
PLATFORMS = ("linkedin", "tiktok", "reddit", "youtube", "instagram", "x")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def compile_gtm_craft_handoff_matrix() -> dict[str, Any]:
    template = _template()
    cases: list[dict[str, Any]] = []
    all_roles: set[str] = set()
    workflow_digests: set[str] = set()
    total_work_orders = 0
    selected_skill_assignments = 0
    professional_axis_assignments = 0
    surface_specialist_lens_assignments = 0
    unconventional_edge_play_bindings = 0
    automatic_external_actions = 0
    review_separation_passes = 0
    human_release_required = 0

    for business_model in BusinessModel:
        for lifecycle in LifecycleStage:
            for budget in BudgetTier:
                for platform in PLATFORMS:
                    is_b2b = business_model is BusinessModel.B2B
                    request = replace(
                        template,
                        campaign_id=(
                            f"craft-{business_model.value}-{lifecycle.value}-{budget.value}-{platform}"
                        ),
                        audience=replace(
                            template.audience,
                            business_model=business_model,
                            buying_context=(
                                "multi-role committee evaluation"
                                if is_b2b
                                else "individual use-moment evaluation"
                            ),
                        ),
                        lifecycle=lifecycle,
                        budget=budget,
                        product_category=(
                            "software_ai_data" if is_b2b else "productivity_tools"
                        ),
                        product_surface=(
                            ProductSurface.WEB_AGENT
                            if is_b2b
                            else ProductSurface.MOBILE_APP
                        ),
                        audience_role=("internal_champion" if is_b2b else "new_user"),
                        distribution_platform=platform,
                    )
                    strategy = StrategyCompiler().compile(request, at=AT)
                    pack = ProductionPackCompiler().compile(request, strategy)
                    plan = pack.text_creative_challenger_plan
                    verify_text_challenger_plan(plan)
                    territory_rows = []
                    for handoff in plan["craft_handoff_plans"]:
                        producers = {
                            row["role_id"]
                            for row in handoff["work_orders"]
                            if row["stage"] == "produce"
                        }
                        reviewers = {
                            row["role_id"]
                            for row in handoff["work_orders"]
                            if row["stage"] == "review"
                        }
                        review_separated = not bool(producers & reviewers)
                        review_separation_passes += int(review_separated)
                        all_roles.update(
                            row["role_id"] for row in handoff["work_orders"]
                        )
                        total_work_orders += handoff["work_order_count"]
                        selected_skill_assignments += sum(
                            len(row["selected_atomic_skill_ids"])
                            for row in handoff["work_orders"]
                        )
                        professional_axis_assignments += sum(
                            len(row["selected_professional_skill_card_ids"])
                            * len(row["required_professional_axis_ids"])
                            for row in handoff["work_orders"]
                        )
                        surface_specialist_lens_assignments += sum(
                            len(row["surface_specialist_lens_ids"])
                            for row in handoff["work_orders"]
                        )
                        unconventional_edge_play_bindings += sum(
                            "unconventional_edge_play" in row
                            for row in handoff["work_orders"]
                        )
                        automatic_external_actions += handoff["harness"][
                            "automatic_external_action_count"
                        ]
                        human_release_required += int(
                            handoff["harness"]["named_human_release_required"]
                        )
                        workflow_signature = {
                            "context": handoff["context_binding"],
                            "orders": [
                                {
                                    "stage": row["stage"],
                                    "role_id": row["role_id"],
                                    "skills": row["selected_atomic_skill_ids"],
                                    "professional_skill_cards": row[
                                        "selected_professional_skill_card_ids"
                                    ],
                                    "professional_axes": row[
                                        "required_professional_axis_ids"
                                    ],
                                    "surface": row["surface_id"],
                                    "surface_specialist_lenses": row[
                                        "surface_specialist_lens_ids"
                                    ],
                                    "unconventional_edge_play_id": row[
                                        "unconventional_edge_play"
                                    ]["edge_play_card_id"],
                                    "channel": row["channel"],
                                }
                                for row in handoff["work_orders"]
                            ],
                        }
                        workflow_digest = _digest(workflow_signature)
                        workflow_digests.add(workflow_digest)
                        territory_rows.append(
                            {
                                "territory_id": handoff["territory_id"],
                                "handoff_sha256": handoff["content_sha256"],
                                "workflow_signature_sha256": workflow_digest,
                                "work_order_count": handoff["work_order_count"],
                                "selected_skill_assignment_count": sum(
                                    len(row["selected_atomic_skill_ids"])
                                    for row in handoff["work_orders"]
                                ),
                                "professional_axis_assignment_count": sum(
                                    len(row["selected_professional_skill_card_ids"])
                                    * len(row["required_professional_axis_ids"])
                                    for row in handoff["work_orders"]
                                ),
                                "surface_specialist_lens_assignment_count": sum(
                                    len(row["surface_specialist_lens_ids"])
                                    for row in handoff["work_orders"]
                                ),
                                "unconventional_edge_play_binding_count": sum(
                                    "unconventional_edge_play" in row
                                    for row in handoff["work_orders"]
                                ),
                                "producer_roles": sorted(producers),
                                "reviewer_roles": sorted(reviewers),
                                "producer_reviewer_separation_passed": review_separated,
                                "maximum_total_model_calls": handoff[
                                    "model_execution_contract"
                                ]["maximum_total_model_calls_per_territory"],
                                "maximum_revision_rounds": handoff["harness"][
                                    "maximum_revision_rounds"
                                ],
                                "automatic_external_action_count": handoff["harness"][
                                    "automatic_external_action_count"
                                ],
                                "named_human_release_required": handoff["harness"][
                                    "named_human_release_required"
                                ],
                            }
                        )
                    cases.append(
                        {
                            "case_id": request.campaign_id,
                            "context": {
                                "business_model": business_model.value,
                                "lifecycle": lifecycle.value,
                                "budget": budget.value,
                                "distribution_platform": platform,
                                "product_surface": request.product_surface.value,
                                "audience_role": request.audience_role,
                            },
                            "plan_sha256": plan["content_sha256"],
                            "territories": territory_rows,
                        }
                    )

    territory_count = sum(len(row["territories"]) for row in cases)
    payload: dict[str, Any] = {
        "schema": "ProofLaunchGTMCraftHandoffMatrixV1",
        "generated_at": AT,
        "matrix_design": {
            "business_models": [item.value for item in BusinessModel],
            "lifecycles": [item.value for item in LifecycleStage],
            "budgets": [item.value for item in BudgetTier],
            "platforms": list(PLATFORMS),
            "territories_per_context": 3,
            "method": "compile_real_production_pack_and_verify_every_craft_handoff",
        },
        "coverage": {
            "context_count": len(cases),
            "territory_handoff_count": territory_count,
            "distinct_workflow_signature_count": len(workflow_digests),
            "total_work_order_count": total_work_orders,
            "selected_atomic_skill_assignment_count": selected_skill_assignments,
            "professional_axis_assignment_count": professional_axis_assignments,
            "surface_specialist_lens_assignment_count": surface_specialist_lens_assignments,
            "unconventional_edge_play_binding_count": unconventional_edge_play_bindings,
            "activated_handoff_role_count": len(all_roles),
            "activated_handoff_role_ids": sorted(all_roles),
            "producer_reviewer_separation_pass_count": review_separation_passes,
            "human_release_required_count": human_release_required,
            "maximum_model_calls_across_all_territories": territory_count * 8,
            "automatic_external_action_count": automatic_external_actions,
        },
        "cases": cases,
        "truth_boundary": (
            "This sealed matrix proves typed specialist assignment, prompt binding, bounded "
            "review/repair topology and safety coverage across 144 contexts and 432 territories. "
            "It does not prove that model outputs match top human craft, win named-product "
            "blind tests, grow organic distribution, convert, or create revenue."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def main() -> int:
    payload = compile_gtm_craft_handoff_matrix()
    atomic_write_text(
        OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(payload["coverage"], ensure_ascii=False, indent=2, sort_keys=True))
    print(payload["content_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
