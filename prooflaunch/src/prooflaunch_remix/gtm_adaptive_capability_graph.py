from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_text, sha256_file
from .gtm_hybrid_quality_control import LANE_CONTRACTS, SCHEMA as HYBRID_SCHEMA
from .gtm_strategy import (
    BudgetTier,
    BusinessModel,
    CompanyScale,
    ContentCapacity,
    DistributionStrength,
    IndustryRisk,
    LifecycleStage,
    SalesMotion,
)
from .gtm_unified_offline_review import seal, sha256_json


SCHEMA = "ProofLaunchGTMAdaptiveCapabilityGraphMatrixV1"
CANDIDATE_SCHEMA = "ProofLaunchAdaptiveOSSSkillCandidatesV1"
RADAR_SCHEMA = "ProofLaunchGTMOpenSourceCapabilityRadarV2"
EXPECTED_CONTEXT_COUNT = 6912
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DISTRIBUTION_RANK = {
    DistributionStrength.NONE: 0,
    DistributionStrength.EMERGING: 1,
    DistributionStrength.ESTABLISHED: 2,
    DistributionStrength.STRONG: 3,
}


class AdaptiveCapabilityGraphError(ValueError):
    pass


@dataclass(frozen=True)
class AdaptiveContext:
    business_model: BusinessModel
    lifecycle: LifecycleStage
    budget: BudgetTier
    industry_risk: IndustryRisk
    company_scale: CompanyScale
    distribution_strength: DistributionStrength
    content_capacity: ContentCapacity
    sales_motion: SalesMotion

    @property
    def context_id(self) -> str:
        return ":".join(value.value for value in asdict(self).values())


LANE_BASE_SCORES: dict[str, int] = {
    "cross_device_memory": 52,
    "data_strategy_intelligence": 67,
    "content_scheduling_operations": 46,
    "image_generation_editing": 41,
    "video_generation_production": 37,
    "audio_voice_music": 31,
    "text_content_generation": 62,
    "product_marketing_analytics": 61,
    "geo_ai_visibility": 47,
    "seo_operations": 51,
    "employee_agent_platforms": 69,
    "advertising_activation": 28,
    "gtm_lifecycle_orchestration": 100,
}


GRAPH_TEMPLATE: dict[str, Any] = {
    "graph_contract": "stable_typed_replayable_graph_dynamic_context_instantiation",
    "nodes": [
        {"id": "diagnose", "depends_on": [], "loop": "evidence_gap_repair"},
        {"id": "research", "depends_on": ["diagnose"], "loop": "source_conflict_repair"},
        {"id": "strategize", "depends_on": ["research"], "loop": "constraint_and_counterfactual_repair"},
        {"id": "design_system", "depends_on": ["strategize"], "loop": "cross_asset_concept_repair"},
        {"id": "produce", "depends_on": ["design_system"], "loop": "lane_quality_failure_repair"},
        {"id": "prepare_release", "depends_on": ["produce"], "loop": "format_rights_and_claim_repair"},
        {"id": "human_release", "depends_on": ["prepare_release"], "loop": "none"},
        {"id": "observe", "depends_on": ["human_release"], "loop": "measurement_integrity_repair"},
        {"id": "learn_next_cycle", "depends_on": ["observe"], "loop": "bounded_policy_candidate_repair"},
    ],
    "global_harness": {
        "deny_by_default_tools": True,
        "typed_inputs_outputs": True,
        "tenant_scope": True,
        "rights_claim_and_consent_gates": True,
        "idempotency_and_compensation": True,
        "rate_cost_latency_caps": True,
        "tamper_evident_trace": True,
        "human_approval_before_external_action": True,
        "automatic_publish_send_spend_or_strategy_mutation": False,
    },
}


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AdaptiveCapabilityGraphError(f"unsafe or missing input: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AdaptiveCapabilityGraphError(f"invalid JSON input: {path}") from error
    if not isinstance(value, dict):
        raise AdaptiveCapabilityGraphError(f"JSON input must be an object: {path}")
    return value


def _verify_hybrid(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != HYBRID_SCHEMA:
        raise AdaptiveCapabilityGraphError("hybrid quality control schema is invalid")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != sha256_json(unsigned):
        raise AdaptiveCapabilityGraphError("hybrid quality control digest is invalid")
    lanes = payload.get("lanes")
    if not isinstance(lanes, list) or {row.get("category_id") for row in lanes} != set(LANE_CONTRACTS):
        raise AdaptiveCapabilityGraphError("hybrid quality control lane coverage drifted")


def _validate_candidate_registry(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != CANDIDATE_SCHEMA:
        raise AdaptiveCapabilityGraphError("adaptive OSS/skill candidate schema is invalid")
    policy = payload.get("policy")
    candidates = payload.get("candidates")
    if not isinstance(policy, dict) or not isinstance(candidates, list) or len(candidates) != 4:
        raise AdaptiveCapabilityGraphError("adaptive OSS/skill candidate registry is incomplete")
    forbidden_flags = (
        "automatic_install_enabled",
        "automatic_framework_migration_enabled",
        "automatic_skill_script_execution_enabled",
        "automatic_online_training_enabled",
    )
    if any(policy.get(flag) is not False for flag in forbidden_flags):
        raise AdaptiveCapabilityGraphError("candidate registry enabled an automatic mutation")
    expected = {"agent_lightning", "stagehand", "anthropic_skills", "openai_skills"}
    if {row.get("id") for row in candidates} != expected:
        raise AdaptiveCapabilityGraphError("candidate identity coverage drifted")
    for row in candidates:
        if not _REVISION.fullmatch(str(row.get("revision", ""))):
            raise AdaptiveCapabilityGraphError("candidate revision is not immutable")
        if not row.get("admission_gates") or not row.get("candidate_lanes"):
            raise AdaptiveCapabilityGraphError("candidate admission contract is incomplete")


def iter_contexts() -> tuple[AdaptiveContext, ...]:
    contexts = tuple(
        AdaptiveContext(*values)
        for values in itertools.product(
            BusinessModel,
            LifecycleStage,
            BudgetTier,
            IndustryRisk,
            CompanyScale,
            DistributionStrength,
            ContentCapacity,
            SalesMotion,
        )
    )
    if len(contexts) != EXPECTED_CONTEXT_COUNT:
        raise AdaptiveCapabilityGraphError("adaptive context cartesian product drifted")
    return contexts


def distribution_operating_floor(
    *strengths: DistributionStrength,
) -> DistributionStrength:
    """Return the weakest observed distribution asset for safe capability planning.

    The full strategy compiler still scores brand, owned audience, community and
    partner access separately.  The adaptive capability matrix uses their floor
    so it never allocates a high-throughput production portfolio merely because
    one surface is strong while a required distribution link is absent.
    """

    if len(strengths) != 4 or any(
        not isinstance(value, DistributionStrength) for value in strengths
    ):
        raise AdaptiveCapabilityGraphError(
            "distribution operating floor requires four typed strengths"
        )
    return min(strengths, key=_DISTRIBUTION_RANK.__getitem__)


def _add(scores: dict[str, int], amount: int, *lanes: str) -> None:
    for lane in lanes:
        scores[lane] += amount


def _lane_scores(context: AdaptiveContext) -> dict[str, int]:
    scores = dict(LANE_BASE_SCORES)
    if context.business_model is BusinessModel.B2B:
        _add(scores, 14, "data_strategy_intelligence")
        _add(scores, 10, "text_content_generation", "seo_operations")
        _add(scores, 8, "geo_ai_visibility", "employee_agent_platforms")
    else:
        _add(scores, 16, "image_generation_editing", "video_generation_production")
        _add(scores, 11, "content_scheduling_operations")
        _add(scores, 8, "audio_voice_music", "advertising_activation")

    stage_additions = {
        LifecycleStage.PRE_PMF: (20, ("data_strategy_intelligence", "product_marketing_analytics")),
        LifecycleStage.LAUNCH: (17, ("text_content_generation", "content_scheduling_operations", "image_generation_editing")),
        LifecycleStage.GROWTH: (18, ("product_marketing_analytics", "seo_operations", "geo_ai_visibility", "advertising_activation")),
        LifecycleStage.MATURE: (17, ("cross_device_memory", "employee_agent_platforms", "data_strategy_intelligence")),
    }
    amount, lanes = stage_additions[context.lifecycle]
    _add(scores, amount, *lanes)
    if context.lifecycle is LifecycleStage.PRE_PMF:
        _add(scores, -30, "advertising_activation")

    if context.budget is BudgetTier.ZERO:
        scores["advertising_activation"] = -1000
        _add(scores, 17, "seo_operations", "geo_ai_visibility", "text_content_generation")
        _add(scores, 9, "data_strategy_intelligence", "product_marketing_analytics")
    elif context.budget is BudgetTier.SCALED:
        _add(scores, 16, "advertising_activation", "product_marketing_analytics")
        _add(scores, 8, "image_generation_editing", "video_generation_production")

    if context.industry_risk is IndustryRisk.HIGH_REGULATION:
        _add(scores, 18, "data_strategy_intelligence", "employee_agent_platforms", "cross_device_memory")
        _add(scores, -10, "advertising_activation")

    scale_additions = {
        CompanyScale.SOLO: (13, ("text_content_generation", "seo_operations", "geo_ai_visibility")),
        CompanyScale.STARTUP: (9, ("data_strategy_intelligence", "text_content_generation", "product_marketing_analytics")),
        CompanyScale.SCALEUP: (11, ("employee_agent_platforms", "product_marketing_analytics", "content_scheduling_operations")),
        CompanyScale.ENTERPRISE: (17, ("cross_device_memory", "employee_agent_platforms", "data_strategy_intelligence")),
    }
    amount, lanes = scale_additions[context.company_scale]
    _add(scores, amount, *lanes)

    distribution_additions = {
        DistributionStrength.NONE: (15, ("seo_operations", "geo_ai_visibility", "text_content_generation", "data_strategy_intelligence")),
        DistributionStrength.EMERGING: (10, ("text_content_generation", "content_scheduling_operations", "product_marketing_analytics")),
        DistributionStrength.ESTABLISHED: (12, ("content_scheduling_operations", "image_generation_editing", "product_marketing_analytics")),
        DistributionStrength.STRONG: (16, ("content_scheduling_operations", "cross_device_memory", "product_marketing_analytics")),
    }
    amount, lanes = distribution_additions[context.distribution_strength]
    _add(scores, amount, *lanes)

    if context.content_capacity is ContentCapacity.LEAN:
        _add(scores, 14, "text_content_generation", "seo_operations", "geo_ai_visibility")
        _add(scores, -18, "video_generation_production")
        _add(scores, -10, "audio_voice_music")
    elif context.content_capacity is ContentCapacity.STUDIO:
        _add(scores, 22, "image_generation_editing", "video_generation_production", "audio_voice_music")
        _add(scores, 10, "content_scheduling_operations")

    if context.sales_motion is SalesMotion.SELF_SERVE:
        _add(scores, 13, "seo_operations", "geo_ai_visibility", "product_marketing_analytics")
    elif context.sales_motion is SalesMotion.SALES_LED:
        _add(scores, 13, "data_strategy_intelligence", "text_content_generation", "employee_agent_platforms", "cross_device_memory")
    else:
        _add(scores, 8, "gtm_lifecycle_orchestration", "content_scheduling_operations", "product_marketing_analytics")
    return scores


def _growth_routes(context: AdaptiveContext) -> tuple[str, str]:
    if context.distribution_strength is DistributionStrength.STRONG:
        return ("customer_evidence", "owned_social_or_customer_email")
    if context.business_model is BusinessModel.B2B:
        if context.lifecycle is LifecycleStage.PRE_PMF:
            return ("founder_problem_conversations", "community_listening")
        if context.distribution_strength is DistributionStrength.NONE:
            return ("search_education", "partner_or_expert_community")
        return ("linkedin_organic", "partner_communities")
    if context.lifecycle is LifecycleStage.PRE_PMF:
        return ("community_listening", "participatory_product_ritual")
    if context.content_capacity is ContentCapacity.STUDIO:
        return ("short_video_organic", "creator_community")
    return ("search_education", "owned_social")


def compile_context(context: AdaptiveContext) -> dict[str, Any]:
    scores = _lane_scores(context)
    ranked = sorted(scores, key=lambda lane: (-scores[lane], lane))
    focus = {
        "gtm_lifecycle_orchestration",
        *[
            lane
            for lane in ranked
            if lane != "gtm_lifecycle_orchestration"
        ][:3],
    }
    test = {lane for lane in ranked if lane not in focus}
    test = set(list(sorted(test, key=lambda lane: (-scores[lane], lane)))[:4])
    lane_states: dict[str, str] = {}
    for lane in LANE_CONTRACTS:
        if context.budget is BudgetTier.ZERO and lane == "advertising_activation":
            lane_states[lane] = "EXCLUDED"
        elif lane in focus:
            lane_states[lane] = "FOCUS"
        elif lane in test:
            lane_states[lane] = "TEST"
        else:
            lane_states[lane] = "OBSERVE"

    primary, secondary = _growth_routes(context)
    loop_cap = {
        ContentCapacity.LEAN: 1,
        ContentCapacity.STANDARD: 2,
        ContentCapacity.STUDIO: 3,
    }[context.content_capacity]
    candidate_count = {
        ContentCapacity.LEAN: 2,
        ContentCapacity.STANDARD: 3,
        ContentCapacity.STUDIO: 4,
    }[context.content_capacity]
    paid_activation_eligible = (
        context.budget is not BudgetTier.ZERO
        and context.lifecycle in {LifecycleStage.GROWTH, LifecycleStage.MATURE}
        and context.distribution_strength in {
            DistributionStrength.ESTABLISHED,
            DistributionStrength.STRONG,
        }
    )
    core = {
        "context_id": context.context_id,
        "dimensions": {key: value.value for key, value in asdict(context).items()},
        "lane_states": lane_states,
        "primary_growth_route": primary,
        "secondary_growth_route": secondary,
        "paid_activation_candidate_count": 1 if paid_activation_eligible else 0,
        "paid_activation_eligible_for_human_review": paid_activation_eligible,
        "node_loop_iteration_cap": loop_cap,
        "creative_candidate_count_per_focused_media_lane": candidate_count,
        "specialist_approval_required": context.industry_risk is IndustryRisk.HIGH_REGULATION,
        "human_release_required": True,
        "automatic_external_actions": 0,
        "next_evidence_required": "observed qualified action, retention, contribution and guardrail outcomes bound to the frozen experiment",
    }
    return {**core, "plan_sha256": sha256_json(core)}


def _render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# GTM adaptive capability graph V1",
        "",
        "The product core is a deterministic Graph/Loop/Harness contract that compiles a different bounded capability portfolio for each company context. Models, vendors and hardware remain replaceable executors.",
        "",
        f"- Deterministic contexts: **{payload['coverage']['context_count']:,}**",
        f"- Lane decisions: **{payload['coverage']['lane_decision_count']:,}**",
        f"- Zero-budget contexts with paid activation: **{payload['coverage']['zero_budget_paid_activation_count']}**",
        f"- High-regulation contexts missing specialist approval gate: **{payload['coverage']['regulated_missing_specialist_gate_count']}**",
        f"- Shadow OSS/skill candidates: **{payload['shadow_candidate_registry']['candidate_count']}**",
        "",
        "## What changes per company",
        "",
        "Business model, lifecycle, budget, regulation, scale, distribution strength, content capacity and sales motion alter lane priority, growth routes, candidate breadth and repair depth. The approval, rights, trace and external-action boundaries do not change.",
        "",
        "## Stable execution skeleton",
        "",
        "`diagnose → research → strategize → design_system → produce → prepare_release → human_release → observe → learn_next_cycle`",
        "",
        "## Shadow reuse rules",
        "",
    ]
    for row in payload["shadow_candidate_registry"]["candidates"]:
        lines.append(f"- **{row['id']}** `{row['revision'][:12]}` — {row['adapter_role']}; {row['decision']}.")
    lines.extend([
        "",
        "## Truth boundary",
        "",
        payload["truth_boundary"],
        "",
    ])
    return "\n".join(lines)


def compile_adaptive_capability_graph_matrix(
    *,
    hybrid_path: Path,
    radar_path: Path,
    candidate_registry_path: Path,
    output_json: Path | None = None,
    output_markdown: Path | None = None,
    executor_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    hybrid = _load(hybrid_path)
    radar = _load(radar_path)
    candidates = _load(candidate_registry_path)
    _verify_hybrid(hybrid)
    if radar.get("schema") != RADAR_SCHEMA or len(radar.get("projects", {})) != 111:
        raise AdaptiveCapabilityGraphError("open-source radar coverage drifted")
    _validate_candidate_registry(candidates)

    contexts = [compile_context(context) for context in iter_contexts()]
    if len({row["context_id"] for row in contexts}) != EXPECTED_CONTEXT_COUNT:
        raise AdaptiveCapabilityGraphError("adaptive context identities are not unique")
    lanes = {row["category_id"]: row for row in hybrid["lanes"]}
    if any(not row.get("local_route_ready") for row in lanes.values()):
        raise AdaptiveCapabilityGraphError("a focused capability could lack a local route")

    zero_budget = [row for row in contexts if row["dimensions"]["budget"] == BudgetTier.ZERO.value]
    regulated = [row for row in contexts if row["dimensions"]["industry_risk"] == IndustryRisk.HIGH_REGULATION.value]
    state_profiles = {
        tuple(sorted(row["lane_states"].items()))
        for row in contexts
    }
    focus_profiles = {
        tuple(sorted(lane for lane, state in row["lane_states"].items() if state == "FOCUS"))
        for row in contexts
    }
    growth_route_profiles = {
        (row["primary_growth_route"], row["secondary_growth_route"])
        for row in contexts
    }
    shadow_by_lane = {
        lane_id: [
            row["id"]
            for row in candidates["candidates"]
            if lane_id in row["candidate_lanes"]
        ]
        for lane_id in LANE_CONTRACTS
    }
    payload = seal({
        "schema": SCHEMA,
        "source_bindings": {
            "hybrid_file_sha256": sha256_file(hybrid_path),
            "hybrid_content_sha256": hybrid["content_sha256"],
            "open_source_radar_file_sha256": sha256_file(radar_path),
            "candidate_registry_file_sha256": sha256_file(candidate_registry_path),
        },
        "dimensions": {
            "business_models": [item.value for item in BusinessModel],
            "lifecycle_stages": [item.value for item in LifecycleStage],
            "budget_tiers": [item.value for item in BudgetTier],
            "industry_risk_tiers": [item.value for item in IndustryRisk],
            "company_scales": [item.value for item in CompanyScale],
            "distribution_strengths": [item.value for item in DistributionStrength],
            "content_capacities": [item.value for item in ContentCapacity],
            "sales_motions": [item.value for item in SalesMotion],
        },
        "coverage": {
            "context_count": len(contexts),
            "lane_count_per_context": len(LANE_CONTRACTS),
            "lane_decision_count": len(contexts) * len(LANE_CONTRACTS),
            "zero_budget_context_count": len(zero_budget),
            "zero_budget_paid_activation_count": sum(row["paid_activation_candidate_count"] for row in zero_budget),
            "regulated_context_count": len(regulated),
            "regulated_missing_specialist_gate_count": sum(not row["specialist_approval_required"] for row in regulated),
            "maximum_node_loop_iteration_cap": max(row["node_loop_iteration_cap"] for row in contexts),
            "automatic_external_action_count": sum(row["automatic_external_actions"] for row in contexts),
            "named_product_pk_jobs_preserved": hybrid["portfolio"]["job_count"],
            "named_product_pk_wins": hybrid["portfolio"]["candidate_wins"],
            "distinct_lane_state_profiles": len(state_profiles),
            "distinct_focus_profiles": len(focus_profiles),
            "distinct_growth_route_profiles": len(growth_route_profiles),
            "paid_activation_human_review_candidate_context_count": sum(
                row["paid_activation_candidate_count"] for row in contexts
            ),
        },
        "graph_loop_harness": GRAPH_TEMPLATE,
        "lane_execution_contracts": {
            lane_id: {
                "local_route": row["local_route"],
                "hard_gates": row["hard_gates"],
                "failure_signals": row["failure_signals"],
                "repair_policy": "repair located failed axis only within context loop cap; preserve frozen Brief and all passed axes",
                "repair_adapters": [
                    {
                        "reason_code": f"{lane_id.upper()}_FAIL_{index:02d}",
                        "failure_signal": failure,
                        "next_counterfactual_evidence": row["hard_gates"][
                            (index - 1) % len(row["hard_gates"])
                        ],
                        "incumbent_oss_project_ids": [
                            project["project_id"] for project in row["open_source_reuse"]
                        ],
                        "eligible_shadow_candidate_ids": shadow_by_lane[lane_id],
                        "automatic_adapter_switch_allowed": False,
                    }
                    for index, failure in enumerate(row["failure_signals"], start=1)
                ],
            }
            for lane_id, row in lanes.items()
        },
        "shadow_candidate_registry": {
            "candidate_count": len(candidates["candidates"]),
            "automatic_install_enabled": False,
            "automatic_skill_script_execution_enabled": False,
            "automatic_online_training_enabled": False,
            "candidates": candidates["candidates"],
            "negative_evidence": candidates["negative_evidence"],
        },
        "executor_binding": {
            "included_in_plan_identity": False,
            "observed_executor_metadata": dict(executor_metadata or {}),
            "policy": "models providers and hardware are selected after capability compilation and cannot change plan identity or safety gates",
        },
        "contexts": contexts,
        "truth_boundary": (
            "This matrix proves deterministic differentiation and bounded execution contracts over 6,912 synthetic context combinations. "
            "It does not prove universal market fit, authorized data access, installation or superiority of shadow candidates, creative preference, "
            "named-product wins, virality, 4A quality, production lift or causal revenue. Every external action and strategy change remains human-gated."
        ),
    })
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output_json, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if output_markdown is not None:
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(output_markdown, _render_markdown(payload))
    return payload
