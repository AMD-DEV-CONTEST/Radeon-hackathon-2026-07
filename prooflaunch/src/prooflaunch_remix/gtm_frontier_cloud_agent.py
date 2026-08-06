from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from .inference_gateway import GatewayResult, InferenceScope
from .gtm_named_capability_distillation import (
    GTMNamedCapabilityDistillationError,
    verify_named_capability_distillation,
)
from .gtm_genome_learning_memory import (
    GTMGenomeLearningMemoryError,
    verify_genome_learning_memory,
)
from .gtm_human_capability_kernel import (
    GTMHumanCapabilityKernelError,
    verify_gtm_human_capability_kernel,
)
from .gtm_recent_organic_signal_pack import (
    RecentOrganicSignalPackError,
    verify_recent_organic_signal_pack,
)


SCHEMA = "ProofLaunchFrontierGTMEmployeeRunV1"
REQUIRED_BRIEF_FIELDS = {
    "brief_id", "business_model", "industry", "category", "lifecycle", "product_surface",
    "audience", "audience_problem", "audience_outcome", "product_truth", "brand_voice",
    "budget", "market", "primary_goal",
    "recent_organic_signal_context", "signal_provenance",
}


class FrontierGTMAgentError(ValueError):
    pass


class FrontierClient(Protocol):
    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        scope: InferenceScope,
        purpose: str,
        max_tokens: int,
        temperature: float,
        timeout_seconds: float,
    ) -> GatewayResult: ...


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _object(content: str) -> dict[str, Any]:
    start = content.find("{")
    if start < 0:
        raise FrontierGTMAgentError("frontier model returned no JSON object")
    try:
        value, _ = json.JSONDecoder().raw_decode(content[start:])
    except json.JSONDecodeError as error:
        raise FrontierGTMAgentError("frontier model returned invalid JSON") from error
    if not isinstance(value, dict):
        raise FrontierGTMAgentError("frontier model response must be one object")
    return value


def _closed_fields(value: Mapping[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise FrontierGTMAgentError(f"{label} is missing required fields: {missing}")


_STRATEGY_FIELDS = {
        "market_diagnosis", "audience_decision", "category_default_to_reject", "non_consensus_bet",
        "zero_budget_wedge", "research_queries", "evidence_boundaries", "kill_conditions",
        "primary_distribution_surface", "secondary_distribution_surface",
        "primary_search_surface", "primary_geo_surface", "surface_selection_reason",
    }


def _validate_strategy(value: Mapping[str, Any]) -> None:
    _closed_fields(value, _STRATEGY_FIELDS, "strategy")


_TERRITORY_FIELDS = {
    "territory_id", "human_truth", "organizing_conflict", "campaign_name", "primary_platform",
    "secondary_platform", "first_line", "portable_decision_tool", "key_visual_metaphor",
    "first_1500ms_video", "participation_mechanic", "zero_budget_relay_object", "proof_integration",
    "why_it_could_fail", "kill_rule",
}


def _validate_concepts(value: Mapping[str, Any]) -> set[str]:
    territories = value.get("territories")
    if not isinstance(territories, list) or len(territories) != 3:
        raise FrontierGTMAgentError("creative board must return exactly three territories")
    identities: set[str] = set()
    for territory in territories:
        if not isinstance(territory, Mapping):
            raise FrontierGTMAgentError("creative territory must be an object")
        _closed_fields(territory, _TERRITORY_FIELDS, "creative territory")
        identity = territory.get("territory_id")
        if not isinstance(identity, str) or not identity.strip() or identity in identities:
            raise FrontierGTMAgentError("creative territory identities must be distinct nonblank strings")
        identities.add(identity)
    return identities


def _validate_jury(value: Mapping[str, Any], territory_ids: set[str]) -> None:
    _closed_fields(value, {
        "selected_territory_id", "selection_reason", "territory_verdicts", "blocking_defects",
        "mandatory_repairs", "rejected_patterns",
    }, "creative jury")
    if value.get("selected_territory_id") not in territory_ids:
        raise FrontierGTMAgentError("creative jury selected an unknown territory")


_PRODUCTION_FIELDS = {
    "campaign_platform", "strategy_rationale", "primary_native_text", "image_system", "video_system",
    "search_and_geo", "zero_budget_activation", "measurement", "claim_inventory", "release_checklist",
    "channel_portfolio", "team_handoffs", "skill_coverage_receipt",
}


def _required_object_fields(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FrontierGTMAgentError(f"{label} must be an object")
    _closed_fields(value, fields, label)
    return value


def _validate_production(
    value: Mapping[str, Any], approved_truth: str, activated: Mapping[str, Any]
) -> None:
    _closed_fields(value, _PRODUCTION_FIELDS, "production pack")
    if approved_truth not in _canonical(value):
        raise FrontierGTMAgentError("production pack does not preserve the exact approved product truth")
    _required_object_fields(
        value.get("primary_native_text"),
        {"hook", "body_blocks", "first_comment", "objection_replies", "participation", "cta"},
        "primary native text",
    )
    _required_object_fields(
        value.get("image_system"),
        {"key_visual", "feed_4x5", "story_9x16", "editorial_16x9", "overlay_copy", "negative_constraints"},
        "image system",
    )
    _required_object_fields(
        value.get("video_system"),
        {"15_to_30_second_script", "six_shot_plan", "first_1500ms", "voice", "sound", "captions", "continuity"},
        "video system",
    )
    _required_object_fields(
        value.get("search_and_geo"),
        {"owned_search_page", "answer_engine_unit"},
        "search and GEO system",
    )
    _required_object_fields(
        value.get("zero_budget_activation"),
        {"primary", "secondary", "four_step_sequence", "relay_object"},
        "zero-budget activation",
    )
    _required_object_fields(
        value.get("measurement"),
        {"frozen_baseline", "primary_metric", "guardrails", "seven_day_window", "kill_rule"},
        "measurement",
    )
    portfolio = _required_object_fields(
        value.get("channel_portfolio"),
        {"primary_distribution", "secondary_distribution", "search", "geo"},
        "channel portfolio",
    )
    expected_surfaces = {
        "primary_distribution": activated["staffing_manifest"]["distribution_platform"],
        "secondary_distribution": next(
            surface_id
            for surface_id, playbook in activated["selected_surface_playbooks"].items()
            if playbook["category"] == "social"
            and surface_id != activated["staffing_manifest"]["distribution_platform"]
        ),
        "search": next(
            surface_id for surface_id, playbook in activated["selected_surface_playbooks"].items()
            if playbook["category"] == "search"
        ),
        "geo": next(
            surface_id for surface_id, playbook in activated["selected_surface_playbooks"].items()
            if playbook["category"] == "geo"
        ),
    }
    channel_fields = {"surface_id", "native_asset", "why_native", "proof_object", "qualified_metric", "release_state"}
    for channel, surface_id in expected_surfaces.items():
        row = _required_object_fields(portfolio.get(channel), channel_fields, f"channel portfolio {channel}")
        if row.get("surface_id") != surface_id:
            raise FrontierGTMAgentError(f"channel portfolio {channel} selected the wrong surface")
        if row.get("release_state") not in {"draft_for_human_review", "blocked"}:
            raise FrontierGTMAgentError("channel release state exceeded authority")
    handoffs = value.get("team_handoffs")
    if not isinstance(handoffs, list) or len(handoffs) < 4:
        raise FrontierGTMAgentError("team handoffs must contain at least four finished-work transitions")
    for row in handoffs:
        _required_object_fields(
            row,
            {"accountable_role_id", "input", "finished_work_product", "receiving_role_id", "acceptance_gate"},
            "team handoff",
        )
    coverage = _required_object_fields(
        value.get("skill_coverage_receipt"),
        {"demonstrated_role_ids", "work_product_evidence", "omitted_role_ids_with_reason"},
        "skill coverage receipt",
    )
    demonstrated = coverage.get("demonstrated_role_ids")
    if not isinstance(demonstrated, list) or set(demonstrated) != set(activated["staffing_manifest"]["active_role_ids"]):
        raise FrontierGTMAgentError("skill coverage receipt does not cover every activated role")
    if coverage.get("omitted_role_ids_with_reason") not in ({}, []):
        raise FrontierGTMAgentError("an activated role was omitted from the production pack")


def _validate_audit(value: Mapping[str, Any]) -> None:
    _closed_fields(value, {
        "status", "direct_publishability", "blocking_defects", "claim_violations", "platform_mismatches",
        "generic_language", "cross_modal_breaks", "zero_budget_breaks", "exact_repair_orders",
        "skill_gate_failures", "surface_gate_failures", "evidence_gate_failures",
        "named_product_gap_summary",
    }, "release audit")
    if value.get("status") not in {"pass", "repair"}:
        raise FrontierGTMAgentError("release audit status must be pass or repair")
    if value.get("direct_publishability") not in {"ready_for_human_release_review", "blocked"}:
        raise FrontierGTMAgentError("release audit direct_publishability is invalid")
    failure_fields = (
        "blocking_defects", "claim_violations", "platform_mismatches", "generic_language",
        "cross_modal_breaks", "zero_budget_breaks", "skill_gate_failures", "surface_gate_failures",
        "evidence_gate_failures",
    )
    for field in failure_fields:
        if not isinstance(value.get(field), list):
            raise FrontierGTMAgentError(f"release audit {field} must be a list")
    named_gap = value.get("named_product_gap_summary")
    if not isinstance(named_gap, Mapping) or named_gap.get("completed_named_product_pk_count") != 0:
        raise FrontierGTMAgentError("named-product gap summary must preserve zero completed PK truth")
    if value.get("status") == "pass":
        if value.get("direct_publishability") != "ready_for_human_release_review":
            raise FrontierGTMAgentError("audit pass must route to human release review")
        if any(value.get(field) for field in failure_fields):
            raise FrontierGTMAgentError("audit cannot pass with an unresolved failure")
    elif value.get("direct_publishability") != "blocked":
        raise FrontierGTMAgentError("repair audit must remain blocked")


def normalize_frontier_brief(brief: Mapping[str, Any]) -> dict[str, str]:
    if set(brief) != REQUIRED_BRIEF_FIELDS:
        raise FrontierGTMAgentError("frontier brief fields violate the closed contract")
    normalized: dict[str, str] = {}
    for field in sorted(REQUIRED_BRIEF_FIELDS):
        value = brief[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 8_000 or "\x00" in value:
            raise FrontierGTMAgentError(f"{field} must be a nonblank bounded string")
        normalized[field] = value.strip()
    if normalized["business_model"] not in {"b2b", "b2c"}:
        raise FrontierGTMAgentError("business_model must be b2b or b2c")
    if normalized["budget"] not in {"zero", "lean", "scaled"}:
        raise FrontierGTMAgentError("budget must be zero, lean or scaled")
    if normalized["lifecycle"] not in {"pre_pmf", "launch", "growth", "mature"}:
        raise FrontierGTMAgentError("lifecycle must be pre_pmf, launch, growth or mature")
    return normalized


def _runtime_capability_context(
    kernel: Mapping[str, Any], brief: Mapping[str, str]
) -> dict[str, Any]:
    try:
        verify_gtm_human_capability_kernel(kernel)
    except GTMHumanCapabilityKernelError as error:
        raise FrontierGTMAgentError("human capability kernel is invalid") from error
    surface_os = kernel["surface_operating_system"]
    playbooks = {row["surface_id"]: row for row in surface_os["playbooks"]}
    councils: dict[str, list[Mapping[str, Any]]] = {}
    for row in surface_os["specialist_council"]:
        councils.setdefault(str(row["surface_id"]), []).append(row)
    edge_cards = {
        row["surface_id"]: row
        for row in surface_os["unconventional_edge_play_contract"]["cards"]
        if row["business_model"] == brief["business_model"]
    }
    okrs = {row["okr_id"].removeprefix("okr:"): row for row in kernel["role_okrs"]}
    role_skills: dict[str, list[dict[str, Any]]] = {}
    for card in kernel["professional_skill_cards"]:
        role_skills.setdefault(str(card["role_id"]), []).append(
            {
                "skill_card_id": card["skill_card_id"],
                "skill_id": card["skill_id"],
                "job_to_be_done": card["job_to_be_done"],
                "required_work_products": card["required_work_products"],
                "mechanical_gate_count": len(card["evaluation_pyramid"]["level_1_code_assertions"]),
                "binary_craft_gate_count": len(card["evaluation_pyramid"]["level_2_binary_judges"]),
                "human_gate_count": len(card["evaluation_pyramid"]["level_3_human_review"]),
            }
        )
    role_contracts = {
        role_id: {
            "role_id": role_id,
            "objective": okrs[role_id]["objective"],
            "leading_kpi_ids": okrs[role_id]["leading_kpi_ids"],
            "lagging_kpi_ids": okrs[role_id]["lagging_kpi_ids"],
            "skills": sorted(rows, key=lambda item: item["skill_id"]),
        }
        for role_id, rows in role_skills.items()
    }
    return {
        "kernel_content_sha256": kernel["content_sha256"],
        "coverage": kernel["coverage"],
        "professional_axis_ids": [
            axis["axis_id"]
            for axis in kernel["professional_skill_cards"][0]["professional_contract_axes"]
        ],
        "surface_playbooks": playbooks,
        "surface_specialist_councils": councils,
        "edge_play_cards": edge_cards,
        "role_contracts": role_contracts,
        "staffing_manifests": kernel["staffing_manifests"],
    }


def _activate_capability_context(
    runtime: Mapping[str, Any], brief: Mapping[str, str], strategy: Mapping[str, Any]
) -> dict[str, Any]:
    playbooks = runtime["surface_playbooks"]
    selections = {
        "primary_distribution_surface": strategy.get("primary_distribution_surface"),
        "secondary_distribution_surface": strategy.get("secondary_distribution_surface"),
        "primary_search_surface": strategy.get("primary_search_surface"),
        "primary_geo_surface": strategy.get("primary_geo_surface"),
    }
    for field, surface_id in selections.items():
        if surface_id not in playbooks:
            raise FrontierGTMAgentError(f"strategy selected an unknown surface for {field}")
    if playbooks[selections["primary_distribution_surface"]]["category"] != "social":
        raise FrontierGTMAgentError("primary distribution surface must be social")
    if playbooks[selections["secondary_distribution_surface"]]["category"] != "social":
        raise FrontierGTMAgentError("secondary distribution surface must be social")
    if selections["primary_distribution_surface"] == selections["secondary_distribution_surface"]:
        raise FrontierGTMAgentError("primary and secondary distribution surfaces must differ")
    if playbooks[selections["primary_search_surface"]]["category"] != "search":
        raise FrontierGTMAgentError("primary search surface must be search")
    if playbooks[selections["primary_geo_surface"]]["category"] != "geo":
        raise FrontierGTMAgentError("primary GEO surface must be an answer surface")
    budget = {"zero": "zero", "lean": "small", "scaled": "scaled"}[brief["budget"]]
    manifest = next(
        (
            row for row in runtime["staffing_manifests"]
            if row["business_model"] == brief["business_model"]
            and row["lifecycle"] == brief["lifecycle"]
            and row["budget"] == budget
            and row["distribution_platform"] == selections["primary_distribution_surface"]
        ),
        None,
    )
    if manifest is None:
        raise FrontierGTMAgentError("no staffing manifest matches the selected execution context")
    selected_surfaces = list(dict.fromkeys(selections.values()))
    active_roles = list(manifest["active_role_ids"])
    return {
        "staffing_manifest": manifest,
        "active_role_contracts": [runtime["role_contracts"][role_id] for role_id in active_roles],
        "active_role_count": len(active_roles),
        "active_skill_card_count": len(manifest["active_skill_card_ids"]),
        "professional_axis_ids": runtime["professional_axis_ids"],
        "selected_surface_playbooks": {
            surface_id: runtime["surface_playbooks"][surface_id]
            for surface_id in selected_surfaces
        },
        "selected_surface_specialist_councils": {
            surface_id: runtime["surface_specialist_councils"][surface_id]
            for surface_id in selected_surfaces
        },
        "selected_unconventional_edge_cards": {
            surface_id: runtime["edge_play_cards"][surface_id]
            for surface_id in selected_surfaces
        },
        "execution_rule": (
            "Produce the specialist work products, not role-play commentary. Every selected surface must visibly differ in "
            "grammar, hook, progression, proof object, interaction and qualified metric. Unconventional means non-consensus "
            "and high-utility, never deceptive."
        ),
    }


def _call(
    client: FrontierClient,
    *,
    purpose: str,
    system: str,
    payload: Mapping[str, Any],
    max_tokens: int,
    temperature: float,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    messages = [
        {"role": "system", "content": system + " Return exactly one JSON object and no markdown."},
        {"role": "user", "content": _canonical(payload)},
    ]
    result = client.complete(
        messages,
        scope=InferenceScope.DEVELOPMENT_CORE,
        purpose=purpose,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
    )
    if result.route in {"local_ollama", "local_mlx"} or result.provider.endswith("_local"):
        raise FrontierGTMAgentError("frontier GTM run forbids local-model fallback")
    value = _object(result.content)
    receipt = {
        "purpose": purpose,
        "provider": result.provider,
        "model": result.model,
        "route": result.route,
        "response_id": result.response_id,
        "usage": dict(result.usage),
        "request_sha256": _digest(messages),
        "response_sha256": hashlib.sha256(result.content.encode()).hexdigest(),
        "competition_core_eligible": False,
        "external_action_count": 0,
    }
    return value, receipt


def execute_frontier_gtm_agent(
    brief: Mapping[str, Any],
    client: FrontierClient,
    *,
    named_capability_distillation: Mapping[str, Any],
    human_capability_kernel: Mapping[str, Any],
    recent_signal_pack: Mapping[str, Any] | None = None,
    learning_memory: Mapping[str, Any] | None = None,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """Execute a cloud-frontier creative board; never publish, send or spend."""

    effective_brief = dict(brief)
    if recent_signal_pack is not None:
        try:
            verify_recent_organic_signal_pack(recent_signal_pack)
        except RecentOrganicSignalPackError as error:
            raise FrontierGTMAgentError("recent organic signal pack is invalid") from error
        effective_brief.update(
            recent_organic_signal_context=recent_signal_pack["recent_organic_signal_context"],
            signal_provenance=recent_signal_pack["signal_provenance"],
        )
    normalized = normalize_frontier_brief(effective_brief)
    try:
        verify_named_capability_distillation(named_capability_distillation)
    except GTMNamedCapabilityDistillationError as error:
        raise FrontierGTMAgentError("named-product capability distillation is invalid") from error
    categories = named_capability_distillation["categories"]
    capability_stress_pack = [
        {
            "category_id": row["category_id"],
            "ten_named_products": row["reference_products"],
            "mechanisms_to_absorb_without_copying_expression": row["mechanism_repertoire"],
            "effect_pk_question": row["effect_pk_question"],
            "quality_axes": row["quality_axes"],
            "pinned_oss_candidates": row["pinned_oss_candidates"],
        }
        for row in categories
    ]
    if len(capability_stress_pack) != 13 or any(len(row["ten_named_products"]) != 10 for row in capability_stress_pack):
        raise FrontierGTMAgentError("frontier run requires the complete 13-by-10 named-product stress pack")
    capability_runtime = _runtime_capability_context(human_capability_kernel, normalized)
    if learning_memory is not None:
        try:
            verify_genome_learning_memory(learning_memory)
        except GTMGenomeLearningMemoryError as error:
            raise FrontierGTMAgentError("human-approved learning memory is invalid") from error
    learning_records = [] if learning_memory is None else learning_memory.get("records", [])
    calls: list[dict[str, Any]] = []
    shared = {
        "brief": normalized,
        "named_product_capability_stress_pack": capability_stress_pack,
        "human_capability_kernel_summary": {
            "kernel_content_sha256": capability_runtime["kernel_content_sha256"],
            "coverage": capability_runtime["coverage"],
            "professional_axis_ids": capability_runtime["professional_axis_ids"],
            "role_okrs_and_skill_catalog": capability_runtime["role_contracts"],
            "surface_playbooks": capability_runtime["surface_playbooks"],
            "business_model_specific_unconventional_edge_cards": capability_runtime["edge_play_cards"],
        },
        "human_approved_learning_memory": learning_records,
        "learning_policy": (
            "Use approved memory as a prior, never as a rule. Preserve at least 25% exploration. Do not write memory during "
            "this run; only a later named-human PK or observed-market decision may promote, repair or retire a mechanism."
        ),
        "unconventional_growth_contract": {
            "definition": (
                "Find an overlooked but truthful platform behavior, counter-intuitive content hook, useful participation ritual "
                "or relay object that earns disproportionate qualified attention without paid media."
            ),
            "required": [
                "one non-consensus audience truth", "one platform-native curiosity gap",
                "one action valuable before conversion", "one identity-safe peer relay object",
                "one falsifiable mechanism and stop condition",
            ],
            "forbidden": [
                "deception", "fabricated proof", "engagement bait", "spam", "impersonation",
                "dark patterns", "platform-rule evasion", "copied competitor expression", "guaranteed virality",
            ],
        },
        "virtual_4a_team": [
            "portfolio strategy partner", "category and audience intelligence lead", "quantitative organic-growth researcher",
            "executive creative director", "platform-native senior copy chief", "social editorial director",
            "visual art director", "short-form film director", "audio and voice director", "SEO and GEO editor",
            "lifecycle and CRM architect", "measurement and causal-inference lead", "claims and release red team",
        ],
        "operating_rules": [
            "Use product_truth as the only approved product fact.",
            "Separate fact, inference, hypothesis and missing evidence.",
            "Zero budget means organic utility, participation and earned distribution; never simulated virality.",
            "Create platform-native work, not one master caption reformatted everywhere.",
            "No competitor imitation, fake customer, fake metric, fake UI, unavailable link or invented capability.",
        ],
    }
    strategy, receipt = _call(
        client,
        purpose="frontier_gtm_market_and_strategy_board",
        system=(
            "Act as a top-tier 4A global strategy director and quantitative growth strategist. Diagnose the audience's "
            "current decision, category saturation, non-consensus tension, recent-signal research questions and the smallest "
            "zero-budget wedge. Produce fields: market_diagnosis, audience_decision, category_default_to_reject, "
            "non_consensus_bet, zero_budget_wedge, research_queries, evidence_boundaries, kill_conditions, "
            "primary_distribution_surface, secondary_distribution_surface, primary_search_surface, primary_geo_surface and "
            "surface_selection_reason. Distribution surfaces must be two distinct social surfaces; search and GEO must use "
            "their respective playbooks. Select supplied surface ids only."
        ),
        payload=shared,
        max_tokens=2400,
        temperature=.35,
        timeout_seconds=timeout_seconds,
    )
    _validate_strategy(strategy)
    activated_capabilities = _activate_capability_context(capability_runtime, normalized, strategy)
    execution_shared = {
        **{key: value for key, value in shared.items() if key != "human_capability_kernel_summary"},
        "human_capability_kernel_summary": {
            "kernel_content_sha256": capability_runtime["kernel_content_sha256"],
            "coverage": capability_runtime["coverage"],
        },
        "activated_execution_contract": activated_capabilities,
    }
    calls.append(receipt)
    concepts, receipt = _call(
        client,
        purpose="frontier_gtm_three_mutually_exclusive_creative_platforms",
        system=(
            "Act as a 4A executive creative director, senior platform copy lead and film director. Create exactly three "
            "mutually exclusive campaign platforms, not three headlines. Each must contain: territory_id, human_truth, "
            "organizing_conflict, campaign_name, primary_platform, secondary_platform, first_line, portable_decision_tool, "
            "key_visual_metaphor, first_1500ms_video, participation_mechanic, zero_budget_relay_object, proof_integration, "
            "why_it_could_fail, kill_rule. The three concepts must differ in conflict, narrative engine and participation."
        ),
        payload={**execution_shared, "strategy": strategy},
        max_tokens=4000,
        temperature=.72,
        timeout_seconds=timeout_seconds,
    )
    territory_ids = _validate_concepts(concepts)
    calls.append(receipt)
    jury, receipt = _call(
        client,
        purpose="frontier_gtm_executive_creative_jury",
        system=(
            "Act as a source-hidden executive creative jury. Reject generic AI language, category cliches, slogan-only ideas, "
            "weak platform behavior, proof decoration, fake participation and concepts that need media spend. Return: "
            "selected_territory_id, selection_reason, territory_verdicts, blocking_defects, mandatory_repairs, rejected_patterns. "
            "Select one only if it can sustain text, image, video, replies, search and a seven-day organic test."
        ),
        payload={**execution_shared, "strategy": strategy, "concepts": concepts},
        max_tokens=2600,
        temperature=.18,
        timeout_seconds=timeout_seconds,
    )
    _validate_jury(jury, territory_ids)
    calls.append(receipt)
    production, receipt = _call(
        client,
        purpose="frontier_gtm_multimodal_last_mile_production",
        system=(
            "Act as the integrated senior copy, art, film, social, SEO/GEO and growth production team. Apply every mandatory "
            "repair and produce one coherent release-review pack. Required fields: campaign_platform; strategy_rationale; "
            "primary_native_text with hook, body_blocks, first_comment, three objection replies, participation and cta; "
            "image_system with key_visual, feed_4x5, story_9x16, editorial_16x9, overlay_copy and negative_constraints; "
            "video_system with 15_to_30_second_script, six_shot_plan, first_1500ms, voice, sound, captions and continuity; "
            "search_and_geo with owned_search_page and answer_engine_unit; zero_budget_activation with primary, secondary, "
            "four_step_sequence and relay_object; measurement with frozen_baseline, primary_metric, guardrails, seven_day_window "
            "and kill_rule; claim_inventory; release_checklist; channel_portfolio with distinct primary_distribution, "
            "secondary_distribution, search and geo artifacts; team_handoffs with accountable role, input, finished work product "
            "and receiving role; skill_coverage_receipt mapping every active role to demonstrated work products and named omissions. "
            "Each channel row must contain surface_id, native_asset, why_native, proof_object, qualified_metric and release_state "
            "draft_for_human_review or blocked. Every handoff must contain accountable_role_id, input, finished_work_product, "
            "receiving_role_id and acceptance_gate. skill_coverage_receipt must contain demonstrated_role_ids, work_product_evidence "
            "and omitted_role_ids_with_reason. Make every audience-facing line directly reviewable."
        ),
        payload={**execution_shared, "strategy": strategy, "concepts": concepts, "jury": jury},
        max_tokens=7000,
        temperature=.48,
        timeout_seconds=timeout_seconds,
    )
    _validate_production(production, normalized["product_truth"], activated_capabilities)
    calls.append(receipt)
    audit, receipt = _call(
        client,
        purpose="frontier_gtm_adversarial_release_audit",
        system=(
            "Act as an independent 4A craft chief, platform-native editor, claims counsel and organic-growth skeptic. Audit the "
            "full pack line by line. Return status pass or repair, direct_publishability, blocking_defects, claim_violations, "
            "platform_mismatches, generic_language, cross_modal_breaks, zero_budget_breaks, skill_gate_failures, "
            "surface_gate_failures, evidence_gate_failures, named_product_gap_summary and exact_repair_orders. Pass only "
            "when no blocking defect remains; do not infer preference, virality, conversion or revenue. direct_publishability must "
            "be ready_for_human_release_review only for pass, otherwise blocked. named_product_gap_summary must be an object with "
            "completed_named_product_pk_count fixed to 0, mechanism_coverage_gaps and effect_claim_boundary."
        ),
        payload={**execution_shared, "strategy": strategy, "jury": jury, "production": production},
        max_tokens=3600,
        temperature=.12,
        timeout_seconds=timeout_seconds,
    )
    _validate_audit(audit)
    calls.append(receipt)
    final_pack = production
    repair = None
    final_audit = audit
    if audit.get("status") != "pass":
        repair, receipt = _call(
            client,
            purpose="frontier_gtm_bounded_last_mile_repair",
            system=(
                "Act as the senior production team. Repair every audit defect without changing the approved product truth, "
                "campaign platform or measurement boundary. Return the complete corrected production object using the identical schema."
            ),
            payload={**execution_shared, "production": production, "audit": audit},
            max_tokens=7000,
            temperature=.28,
            timeout_seconds=timeout_seconds,
        )
        calls.append(receipt)
        _validate_production(repair, normalized["product_truth"], activated_capabilities)
        final_pack = repair
        final_audit, receipt = _call(
            client,
            purpose="frontier_gtm_post_repair_release_audit",
            system=(
                "Repeat the independent line-by-line release audit on the repaired pack. Return the identical audit schema. "
                "Pass only if every prior repair is present and no new claim, platform, craft, coherence or zero-budget defect remains."
            ),
            payload={**execution_shared, "previous_audit": audit, "repaired_production": repair},
            max_tokens=3600,
            temperature=.08,
            timeout_seconds=timeout_seconds,
        )
        calls.append(receipt)
        _validate_audit(final_audit)
    result = {
        "schema": SCHEMA,
        "brief": normalized,
        "named_capability_distillation_sha256": named_capability_distillation["content_sha256"],
        "human_capability_kernel_sha256": human_capability_kernel["content_sha256"],
        "recent_signal_pack_sha256": (
            recent_signal_pack.get("content_sha256") if recent_signal_pack is not None else None
        ),
        "activated_capability_contract": activated_capabilities,
        "activated_role_count": activated_capabilities["active_role_count"],
        "activated_skill_card_count": activated_capabilities["active_skill_card_count"],
        "learning_memory_sha256": learning_memory.get("content_sha256") if learning_memory else None,
        "human_approved_learning_record_count": len(learning_records),
        "named_product_stress_count": 130,
        "capability_category_count": 13,
        "strategy": strategy,
        "concepts": concepts,
        "jury": jury,
        "initial_production": production,
        "audit": audit,
        "final_audit": final_audit,
        "repair": repair,
        "final_production": final_pack,
        "cloud_model_call_count": len(calls),
        "local_model_call_count": 0,
        "calls": calls,
        "external_publish_executed": False,
        "external_send_executed": False,
        "media_spend_executed": False,
        "human_release_required": True,
        "release_review_status": (
            "ready_for_named_human_release_review" if final_audit.get("status") == "pass"
            else "blocked_frontier_quality_gate"
        ),
        "winner_selected": False,
        "learning_memory_mutated": False,
        "truth_boundary": (
            "This cloud-frontier run produces a strategy-to-last-mile release-review pack. Its model audit is advisory, not an "
            "independent human preference result, observed organic breakout, conversion, revenue result or named-product win."
        ),
    }
    result["content_sha256"] = _digest(result)
    return result


__all__ = [
    "FrontierGTMAgentError", "REQUIRED_BRIEF_FIELDS", "SCHEMA",
    "execute_frontier_gtm_agent", "normalize_frontier_brief",
]
