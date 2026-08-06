from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prooflaunch_remix.gtm_strategy import BudgetTier, BusinessModel, LifecycleStage, ProductSurface
from prooflaunch_remix.gtm_team_capability_os import (
    REFERENCE_COHORTS,
    ROLE_REGISTRY,
    SKILLS_PER_ROLE,
    compile_gtm_team_capability_contract,
)
from scripts.compile_gtm_market_language_matrix import PLATFORMS, _template


DEFAULT_OUTPUT = ROOT / "evidence/v10/gtm-team-capability-matrix-v1.json"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def compile_gtm_team_capability_matrix() -> dict[str, Any]:
    template = _template()
    rows: list[dict[str, Any]] = []
    configurations = (
        (BusinessModel.B2B, "software_ai_data", "internal_champion", ProductSurface.WEB_AGENT),
        (BusinessModel.B2C, "productivity_tools", "new_user", ProductSurface.MOBILE_APP),
    )
    activated: set[str] = set()
    for business_model, category, role, surface in configurations:
        for lifecycle in LifecycleStage:
            for budget in BudgetTier:
                for platform in PLATFORMS:
                    request = replace(
                        template,
                        audience=replace(template.audience, business_model=business_model),
                        campaign_id=(
                            f"team-{business_model.value}-{lifecycle.value}-"
                            f"{budget.value}-{platform}"
                        ),
                        product_category=category,
                        product_surface=surface,
                        audience_role=role,
                        lifecycle=lifecycle,
                        budget=budget,
                        distribution_platform=platform,
                    )
                    contract = compile_gtm_team_capability_contract(request)
                    active_roles = [
                        item["role_id"]
                        for item in contract["active_virtual_team"]["roles"]
                    ]
                    activated.update(active_roles)
                    rows.append(
                        {
                            "case_id": request.campaign_id,
                            "business_model": business_model.value,
                            "lifecycle": lifecycle.value,
                            "budget": budget.value,
                            "distribution_platform": platform,
                            "active_role_count": len(active_roles),
                            "active_atomic_skill_count": contract[
                                "active_virtual_team"
                            ]["active_atomic_skill_count"],
                            "active_role_ids": active_roles,
                            "reference_cohort_id": contract[
                                "reference_cohort_contract"
                            ]["cohort_id"],
                            "reference_company_count": contract[
                                "reference_cohort_contract"
                            ]["company_count"],
                            "contract_sha256": contract["content_sha256"],
                            "automatic_external_action_count": contract[
                                "automatic_external_action_count"
                            ],
                        }
                    )
    payload: dict[str, Any] = {
        "schema": "ProofLaunchGTMTeamCapabilityMatrixV1",
        "as_of": "2026-08-03",
        "reference_cohorts": {
            "status": "non_ranked_public_product_capability_references",
            "authoritative_company_ranking_claimed": False,
            "internal_company_org_charts_inferred": False,
            "cohorts": REFERENCE_COHORTS,
        },
        "role_skill_registry": {
            "role_count": len(ROLE_REGISTRY),
            "skills_per_role": SKILLS_PER_ROLE,
            "atomic_skill_count": len(ROLE_REGISTRY) * SKILLS_PER_ROLE,
            "roles": ROLE_REGISTRY,
            "registry_sha256": _digest(ROLE_REGISTRY),
        },
        "coverage": {
            "business_model_count": len(BusinessModel),
            "lifecycle_count": len(LifecycleStage),
            "budget_count": len(BudgetTier),
            "platform_count": len(PLATFORMS),
            "staffing_context_count": len(rows),
            "distinct_contract_count": len(
                {row["contract_sha256"] for row in rows}
            ),
            "activated_role_count": len(activated),
            "unactivated_role_ids": sorted(set(ROLE_REGISTRY) - activated),
            "automatic_external_action_count": sum(
                row["automatic_external_action_count"] for row in rows
            ),
        },
        "staffing_contexts": rows,
        "operating_boundary": {
            "baseline_required_before_numeric_growth_targets": True,
            "named_human_release_required": True,
            "failed_outputs_auto_admitted_to_training": False,
            "current_run_self_modification_allowed": False,
        },
        "truth_boundary": (
            "The artifact proves role, skill, work-product, quality-gate and KPI decomposition "
            "plus deterministic staffing. It does not prove the system performs at the level of "
            "the referenced companies or human craft specialists."
        ),
    }
    expected = len(BusinessModel) * len(LifecycleStage) * len(BudgetTier) * len(PLATFORMS)
    if len(rows) != expected or len({row["contract_sha256"] for row in rows}) != expected:
        raise RuntimeError("GTM staffing context coverage is incomplete")
    if activated != set(ROLE_REGISTRY):
        raise RuntimeError("one or more GTM craft roles never enters an active team")
    if payload["coverage"]["automatic_external_action_count"] != 0:
        raise RuntimeError("GTM team matrix executed an external action")
    payload["content_sha256"] = _digest(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = compile_gtm_team_capability_matrix()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "staffing_context_count": payload["coverage"][
                    "staffing_context_count"
                ],
                "role_count": payload["role_skill_registry"]["role_count"],
                "atomic_skill_count": payload["role_skill_registry"][
                    "atomic_skill_count"
                ],
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
