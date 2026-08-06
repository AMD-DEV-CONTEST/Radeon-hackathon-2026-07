from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .gtm_strategy import BusinessModel, CampaignStrategyInput, LifecycleStage


class GTMTeamCapabilityError(ValueError):
    """The human-equivalent GTM team contract is incomplete or unsafe."""


CONTRACT_SCHEMA = "ProofLaunchGTMTeamCapabilityContractV1"
REGISTRY_SCHEMA = "ProofLaunchGTMSkillRegistryV1"
SKILLS_PER_ROLE = 10


def _role(
    mission: str,
    skills: Sequence[str],
    work_products: Sequence[str],
    quality_gate: str,
    leading_kpis: Sequence[str],
    lagging_kpis: Sequence[str],
) -> dict[str, Any]:
    if len(skills) != SKILLS_PER_ROLE:
        raise RuntimeError("every GTM role requires exactly ten atomic skills")
    return {
        "mission": mission,
        "atomic_skill_ids": list(skills),
        "required_work_products": list(work_products),
        "quality_gate": quality_gate,
        "leading_kpi_ids": list(leading_kpis),
        "lagging_kpi_ids": list(lagging_kpis),
    }


ROLE_REGISTRY: dict[str, dict[str, Any]] = {
    "gtm_general_manager": _role(
        "choose a coherent market, message, channel and operating sequence under real constraints",
        ("portfolio_strategy", "stage_budget_diagnosis", "market_sequencing", "resource_allocation", "decision_rights", "cross_function_arbitration", "premortem", "scenario_tradeoffs", "operating_cadence", "narrative_coherence"),
        ("one-page GTM thesis", "decision-rights map", "stage-gated operating review"),
        "every priority has one owner, one evidence threshold, one stop rule and one handoff",
        ("decision_cycle_time", "priority_evidence_coverage"),
        ("qualified_growth_efficiency", "portfolio_incrementality"),
    ),
    "market_intelligence_lead": _role(
        "maintain a point-in-time view of category change without copying source expression",
        ("query_lattice_design", "source_triangulation", "entity_resolution", "category_taxonomy", "temporal_change_detection", "growth_residual_analysis", "saturation_detection", "signal_rights_review", "uncertainty_labeling", "competitor_mechanism_abstraction"),
        ("dated market map", "comparable growth-case cohort", "mechanism-not-expression brief"),
        "every inference is separated from observation and tied to a dated source digest",
        ("fresh_source_coverage", "comparable_case_admission_rate"),
        ("validated_signal_precision", "research_to_test_conversion"),
    ),
    "product_marketing_lead": _role(
        "translate product truth into category position, message hierarchy and proof",
        ("positioning", "category_design", "jobs_to_be_done", "value_proposition", "message_hierarchy", "proof_architecture", "objection_mapping", "competitive_contrast", "launch_narrative", "sales_story_alignment"),
        ("positioning spine", "message-proof matrix", "objection and contrast map"),
        "each promise points to approved evidence, a named audience and a falsifiable boundary",
        ("message_proof_coverage", "priority_objection_coverage"),
        ("qualified_message_resonance", "positioning_win_rate"),
    ),
    "audience_research_lead": _role(
        "model one real decision or use moment without averaging incompatible people",
        ("interview_design", "behavioral_segmentation", "decision_unit_mapping", "use_moment_mapping", "switching_cost_analysis", "anxiety_and_desire_language", "first_party_cohort_analysis", "accessibility_inclusion", "consent_provenance", "persona_falsification"),
        ("primary-role card", "decision or use journey", "language-and-objection evidence set"),
        "one asset binds exactly one primary role and owner-confirmed evidence",
        ("owner_confirmed_insight_rate", "single_role_asset_rate"),
        ("qualified_audience_action_rate", "segment_retention_or_progression"),
    ),
    "creative_strategy_director": _role(
        "turn the GTM thesis into distinctive, transferable creative systems",
        ("big_idea_development", "creative_territory_design", "cultural_tension_framing", "proof_sequence", "format_mechanic_transfer", "participation_design", "brand_memory_device", "concept_divergence", "creative_premortem", "senior_critique"),
        ("three distinct territories", "creative system rules", "concept review board"),
        "territories share proof but differ in structure, voice and participation mechanism",
        ("territory_distinctness", "proof_spine_fidelity"),
        ("blind_creative_preference", "brand_distinctiveness_lift"),
    ),
    "senior_social_copywriter": _role(
        "write platform-native social language that earns voluntary attention and action",
        ("hook_writing", "voice_matching", "spoken_rhythm", "compression", "humor_control", "comment_prompt_design", "cta_design", "claim_safe_persuasion", "variant_generation", "line_editing"),
        ("platform-native post", "three hook variants", "comment and response playbook"),
        "copy is role-specific, speakable, original, claim-safe and impossible to swap unchanged across platforms",
        ("hook_hold_rate", "platform_native_review_rate"),
        ("qualified_relay_rate", "qualified_action_rate"),
    ),
    "longform_editorial_director": _role(
        "produce deep, useful editorial work with an original thesis and inspectable evidence",
        ("thesis_development", "reporting_plan", "source_hierarchy", "argument_architecture", "expert_interview_editing", "fact_checking", "narrative_pacing", "structural_editing", "headline_deck", "citation_integrity"),
        ("editorial brief", "source-traceable draft", "fact-check and structural edit memo"),
        "the piece adds first-hand reasoning beyond source summaries and survives source-by-source verification",
        ("citation_coverage", "editorial_revision_closure"),
        ("qualified_read_depth", "citation_or_save_rate"),
    ),
    "short_video_director": _role(
        "direct short-form video where every beat advances tension, proof or payoff",
        ("beat_sheet", "first_frame_direction", "visual_storytelling", "shot_design", "performance_direction", "retention_pacing", "product_demo_blocking", "continuity", "edit_notes", "platform_cut_strategy"),
        ("beat sheet", "shot list and performance notes", "edit decision list"),
        "the first beat resolves the viewing promise and every shot has a narrative job",
        ("first_beat_clarity", "shot_job_coverage"),
        ("qualified_completion_rate", "voluntary_rewatch_or_share"),
    ),
    "art_design_director": _role(
        "create ownable visual systems that preserve product truth across variants",
        ("art_direction", "visual_metaphor", "layout_hierarchy", "typography", "color_system", "product_fidelity", "identity_consistency", "accessibility", "multiformat_adaptation", "visual_quality_review"),
        ("visual rulebook", "key art", "cross-format adaptation board"),
        "the product remains accurate, the hierarchy is legible and the visual cannot be mistaken for source trade dress",
        ("product_fidelity_pass_rate", "accessibility_pass_rate"),
        ("blind_visual_preference", "distinctive_asset_recall"),
    ),
    "audio_voice_producer": _role(
        "make speech, sound and music support meaning, brand and platform context",
        ("voice_casting", "pronunciation_direction", "performance_pacing", "sound_design", "music_briefing", "mixing", "loudness_mastering", "audio_branding", "rights_clearance", "listening_review"),
        ("voice direction sheet", "sound and music cue sheet", "mastering and rights receipt"),
        "speech is intelligible, emotionally appropriate, rights-clear and reviewed by a named listener",
        ("pronunciation_pass_rate", "technical_master_pass_rate"),
        ("blind_audio_preference", "message_recall_after_listen"),
    ),
    "platform_distribution_strategist": _role(
        "translate one idea into native formats, seeding paths and timing tests per platform",
        ("platform_grammar", "format_selection", "community_norms", "seeding_map", "cadence_design", "timing_holdout", "frequency_control", "cross_platform_rewrite", "distribution_bridge", "algorithm_change_monitoring"),
        ("platform translation matrix", "human-approved calendar", "two-slot timing test"),
        "no cross-platform copy-paste, universal timing claim or unapproved activation",
        ("native_format_coverage", "schedule_constraint_pass_rate"),
        ("qualified_organic_reach", "earned_distribution_depth"),
    ),
    "organic_growth_community_lead": _role(
        "earn durable community participation and product-led distribution without spam",
        ("community_mapping", "listen_before_speak", "participation_ritual", "utility_asset", "ambassador_path", "referral_mechanic", "moderator_alignment", "feedback_loop", "anti_spam_control", "community_health"),
        ("community contribution plan", "useful participation object", "moderator and feedback log"),
        "the contribution has stand-alone value and respects community and platform rules",
        ("substantive_participation_rate", "moderator_acceptance_rate"),
        ("voluntary_relay_depth", "community_sourced_qualified_action"),
    ),
    "creator_partnerships_lead": _role(
        "choose credible audience bridges and co-create without audience or creator extraction",
        ("creator_fit", "audience_overlap", "authenticity_screening", "brief_co_creation", "creative_freedom_boundary", "disclosure_compliance", "rights_and_usage", "fraud_robustness", "earned_propagation", "partnership_incrementality"),
        ("creator fit shortlist", "co-creation brief", "rights and disclosure record"),
        "fit, rights, disclosure and human approval precede any contact or release",
        ("qualified_creator_fit_rate", "rights_disclosure_completeness"),
        ("incremental_qualified_reach", "creator_sourced_conversion_quality"),
    ),
    "seo_geo_editor": _role(
        "make the brand useful and citable in search and answer systems",
        ("intent_mapping", "information_gain", "entity_clarity", "source_citation", "technical_seo", "structured_data", "answer_extractability", "expertise_signals", "content_refresh", "visibility_measurement"),
        ("intent-content map", "source-clear answer asset", "technical and citation audit"),
        "content serves the user decision first and adds original, source-clear value",
        ("indexability_and_entity_pass_rate", "citation_ready_answer_coverage"),
        ("qualified_organic_search_action", "answer_engine_citation_share"),
    ),
    "lifecycle_crm_strategist": _role(
        "move opted-in audiences through useful lifecycle moments with respectful frequency",
        ("lifecycle_state_model", "trigger_design", "message_sequence", "personalization_boundary", "frequency_capping", "deliverability", "holdout_design", "churn_signal", "winback_strategy", "consent_management"),
        ("lifecycle state map", "triggered sequence", "holdout and consent plan"),
        "every send has consent, state relevance, frequency protection and a measurable holdout",
        ("eligible_trigger_coverage", "deliverability_health"),
        ("incremental_activation_or_retention", "negative_feedback_rate"),
    ),
    "demand_generation_lead": _role(
        "convert category demand into qualified B2B conversations without masking channel economics",
        ("demand_capture", "demand_creation", "account_selection", "offer_design", "campaign_architecture", "lead_quality", "channel_economics", "pipeline_stage_alignment", "incrementality", "budget_stop_rules"),
        ("demand portfolio", "offer and account matrix", "source-bound pipeline review"),
        "pipeline stages, cost, quality and incrementality remain separate from booked revenue",
        ("qualified_account_engagement", "sales_acceptance_rate"),
        ("incremental_pipeline_quality", "contribution_margin_after_demand_cost"),
    ),
    "product_led_growth_lead": _role(
        "turn first value and repeated product value into measurable organic growth loops",
        ("activation_definition", "first_value_design", "onboarding_experiment", "habit_loop", "collaboration_loop", "referral_loop", "paywall_value", "retention_cohort", "friction_diagnosis", "product_experimentation"),
        ("activation map", "first-value experiment", "retention and loop cohort review"),
        "growth loops depend on delivered product value, not dark patterns or notification pressure",
        ("first_value_completion", "loop_invitation_quality"),
        ("retained_activation", "organic_product_loop_coefficient"),
    ),
    "sales_enablement_revops_lead": _role(
        "equip revenue teams with consistent evidence while preserving funnel and data truth",
        ("stage_definition", "qualification", "enablement_asset", "demo_narrative", "objection_coaching", "crm_hygiene", "routing", "forecast_calibration", "handoff_sla", "revenue_reconciliation"),
        ("stage and field dictionary", "evidence-led enablement kit", "marketing-sales handoff review"),
        "no pipeline record is counted as revenue and every handoff has owner, timestamp and evidence",
        ("required_field_completeness", "handoff_sla_adherence"),
        ("qualified_stage_progression", "forecast_calibration_error"),
    ),
    "growth_data_experimentation_lead": _role(
        "separate signal, causality and uncertainty so iteration improves decisions rather than dashboards",
        ("metric_tree", "instrumentation", "identity_safe_join", "experiment_design", "power_analysis", "sequential_monitoring", "causal_inference", "uplift_modeling", "uncertainty_calibration", "decision_analysis"),
        ("metric contract", "preregistered analysis plan", "effect and uncertainty report"),
        "observational association is never labeled causal and targets require a baseline plus owner approval",
        ("instrumentation_coverage", "preregistration_compliance"),
        ("incremental_qualified_outcome", "decision_calibration"),
    ),
    "agent_quality_learning_engineer": _role(
        "convert failures into bounded skill improvements without uncontrolled self-modification",
        ("task_taxonomy", "trajectory_eval", "failure_slicing", "golden_fixture", "adversarial_eval", "judge_calibration", "prompt_program_optimization", "offline_policy_replay", "drift_detection", "human_promotion_gate"),
        ("failure-coordinate ledger", "frozen replay suite", "next-run promotion candidate"),
        "a learning candidate must beat the frozen control without safety, calibration or latency regression",
        ("failure_slice_coverage", "replay_reproducibility"),
        ("human_adjudicated_quality_gain", "regression_escape_rate"),
    ),
    "brand_safety_claims_lead": _role(
        "protect people, evidence, rights and brand trust across every generated asset",
        ("claim_review", "evidence_validity", "regulated_review", "copyright_boundary", "likeness_and_voice_rights", "privacy_review", "platform_policy", "accessibility_review", "crisis_premortem", "release_authority"),
        ("claim-evidence ledger", "rights and policy checklist", "named release decision"),
        "no unsupported claim, restricted source, identity imitation or high-risk external action passes",
        ("pre_release_gate_coverage", "rights_traceability"),
        ("blocking_defect_escape_rate", "substantiated_complaint_rate"),
    ),
    "localization_cultural_editor": _role(
        "adapt meaning, humor and participation to a locale without flattening the brand",
        ("transcreation", "cultural_context", "dialect_register", "humor_localization", "taboo_screening", "local_platform_norms", "inclusive_language", "local_claim_context", "back_translation", "native_editor_review"),
        ("locale voice brief", "transcreated asset", "native-editor difference log"),
        "a named native editor verifies meaning, register, risk and platform fit before release",
        ("native_review_completion", "meaning_preservation_pass_rate"),
        ("locale_specific_quality_preference", "qualified_locale_action_rate"),
    ),
}


REFERENCE_COHORTS: dict[str, list[dict[str, str]]] = {
    "b2b_enterprise_ai_product_reference_cohort": [
        {"company": "Microsoft", "capability_surface": "enterprise copilots and agent building", "official_url": "https://www.microsoft.com/en-us/microsoft-copilot/microsoft-copilot-studio"},
        {"company": "Google Cloud", "capability_surface": "enterprise search, assistants and agentic workflows", "official_url": "https://docs.cloud.google.com/gemini/enterprise/docs?hl=en"},
        {"company": "Salesforce", "capability_surface": "CRM-native agent orchestration, testing and governance", "official_url": "https://www.salesforce.com/platform/agentforce-platform"},
        {"company": "ServiceNow", "capability_surface": "workflow-native enterprise AI agents", "official_url": "https://www.servicenow.com/products/ai-agents.html"},
        {"company": "Palantir", "capability_surface": "ontology-grounded operational AI", "official_url": "https://www.palantir.com/platforms/aip/"},
        {"company": "Databricks", "capability_surface": "data-to-model lifecycle, agents and monitoring", "official_url": "https://docs.databricks.com/en/machine-learning/index.html"},
        {"company": "Snowflake", "capability_surface": "governed data-native AI and agents", "official_url": "https://www.snowflake.com/en/product/features/cortex/"},
        {"company": "Adobe", "capability_surface": "governed enterprise content supply chain", "official_url": "https://business.adobe.com/products/genstudio-for-performance-marketing.html"},
        {"company": "HubSpot", "capability_surface": "customer-platform AI across marketing, sales and service", "official_url": "https://www.hubspot.com/products/artificial-intelligence"},
        {"company": "Glean", "capability_surface": "permissions-aware enterprise knowledge and agents", "official_url": "https://docs.glean.com/user-guide/about/what-is-glean"},
    ],
    "b2c_ai_product_reference_cohort": [
        {"company": "OpenAI", "capability_surface": "multimodal general assistant across web and mobile", "official_url": "https://help.openai.com/en/articles/12677804-what-is-chatgpt-faq"},
        {"company": "Anthropic", "capability_surface": "general assistant, research, creation and computer use", "official_url": "https://www.anthropic.com/claude"},
        {"company": "Google", "capability_surface": "consumer multimodal assistant", "official_url": "https://gemini.google.com/"},
        {"company": "Microsoft", "capability_surface": "consumer copilot across devices", "official_url": "https://copilot.microsoft.com/"},
        {"company": "Meta", "capability_surface": "socially distributed consumer assistant", "official_url": "https://www.meta.ai/"},
        {"company": "Perplexity", "capability_surface": "answer and research product", "official_url": "https://www.perplexity.ai/"},
        {"company": "Midjourney", "capability_surface": "consumer visual creation", "official_url": "https://www.midjourney.com/"},
        {"company": "Runway", "capability_surface": "consumer and professional generative video workflow", "official_url": "https://runwayml.com/product/ai-video-generator"},
        {"company": "Canva", "capability_surface": "accessible AI-assisted visual communication", "official_url": "https://www.canva.com/newsroom/news/magic-studio/"},
        {"company": "Character.AI", "capability_surface": "consumer character and conversational experiences", "official_url": "https://character.ai/"},
    ],
}

_LIFECYCLE_OBJECTIVES = {
    LifecycleStage.PRE_PMF: "falsify the narrow problem and first-value assumptions before scaling reach",
    LifecycleStage.LAUNCH: "establish one evidence-backed audience-message-channel wedge",
    LifecycleStage.GROWTH: "increase repeatable qualified outcomes while protecting distinctiveness and trust",
    LifecycleStage.MATURE: "renew category relevance, retention and expansion with measured incrementality",
}

_CORE_ROLES = (
    "gtm_general_manager",
    "market_intelligence_lead",
    "product_marketing_lead",
    "audience_research_lead",
    "creative_strategy_director",
    "platform_distribution_strategist",
    "growth_data_experimentation_lead",
    "agent_quality_learning_engineer",
    "brand_safety_claims_lead",
    "localization_cultural_editor",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _platform_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def _active_role_ids(request: CampaignStrategyInput) -> list[str]:
    roles = list(_CORE_ROLES)
    platform = _platform_key(request.distribution_platform)
    roles.extend(("senior_social_copywriter", "organic_growth_community_lead"))
    if platform in {"tiktok", "instagram", "youtube"}:
        roles.extend(("short_video_director", "art_design_director", "audio_voice_producer"))
    if platform in {"linkedin", "reddit", "x", "youtube"}:
        roles.append("longform_editorial_director")
    if request.audience.business_model is BusinessModel.B2B:
        roles.extend(("demand_generation_lead", "sales_enablement_revops_lead"))
    else:
        roles.extend(("product_led_growth_lead", "creator_partnerships_lead"))
    if request.lifecycle in {LifecycleStage.GROWTH, LifecycleStage.MATURE}:
        roles.append("lifecycle_crm_strategist")
    if platform in {"youtube", "reddit"}:
        roles.append("seo_geo_editor")
    return list(dict.fromkeys(roles))


def compile_gtm_team_capability_contract(request: CampaignStrategyInput) -> dict[str, Any]:
    active_ids = _active_role_ids(request)
    active_roles = [
        {"role_id": role_id, **ROLE_REGISTRY[role_id]}
        for role_id in active_ids
    ]
    registry_payload = {
        "schema": REGISTRY_SCHEMA,
        "role_count": len(ROLE_REGISTRY),
        "skills_per_role": SKILLS_PER_ROLE,
        "atomic_skill_count": sum(
            len(role["atomic_skill_ids"]) for role in ROLE_REGISTRY.values()
        ),
        "roles": ROLE_REGISTRY,
    }
    cohort_key = (
        "b2b_enterprise_ai_product_reference_cohort"
        if request.audience.business_model is BusinessModel.B2B
        else "b2c_ai_product_reference_cohort"
    )
    payload: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "context": {
            "business_model": request.audience.business_model.value,
            "industry": request.industry,
            "product_category": request.product_category,
            "product_surface": request.product_surface.value,
            "primary_audience_role": request.audience_role,
            "lifecycle": request.lifecycle.value,
            "budget": request.budget.value,
            "distribution_platform": request.distribution_platform,
        },
        "reference_cohort_contract": {
            "cohort_id": cohort_key,
            "company_count": len(REFERENCE_COHORTS[cohort_key]),
            "companies": REFERENCE_COHORTS[cohort_key],
            "selection_is_authoritative_ranking": False,
            "public_product_capability_reference_only": True,
            "internal_org_chart_or_private_performance_inferred": False,
            "owner_review_required_before_comparative_claim": True,
        },
        "full_skill_registry": {
            "schema": REGISTRY_SCHEMA,
            "role_count": registry_payload["role_count"],
            "skills_per_role": registry_payload["skills_per_role"],
            "atomic_skill_count": registry_payload["atomic_skill_count"],
            "registry_sha256": _digest(registry_payload),
        },
        "active_virtual_team": {
            "active_role_count": len(active_roles),
            "active_atomic_skill_count": sum(
                len(role["atomic_skill_ids"]) for role in active_roles
            ),
            "roles": active_roles,
            "one_accountable_general_manager": True,
            "specialist_outputs_cannot_be_replaced_by_committee_average_copy": True,
        },
        "team_okr_contract": {
            "objective": _LIFECYCLE_OBJECTIVES[request.lifecycle],
            "key_results": [
                {"id": "kr_evidence", "definition": "all released claims have current approved evidence and rights", "target": "100_percent_structural_gate"},
                {"id": "kr_role_fit", "definition": "each asset binds one owner-confirmed role and decision or use moment", "target": "100_percent_structural_gate"},
                {"id": "kr_originality", "definition": "each admitted concept passes expression and identity-imitation review", "target": "zero_blocking_originality_defects"},
                {"id": "kr_organic_quality", "definition": "improve qualified organic attention and downstream action against a frozen control", "target": None, "target_status": "requires_28_day_baseline_owner_approval_and_power_check"},
                {"id": "kr_business_outcome", "definition": "improve verified qualified conversion, retention or revenue contribution when observable", "target": None, "target_status": "requires_source_bound_baseline_and_causal_design"},
            ],
            "kpi_dictionary": {
                "qualified_organic_attention_rate": "qualified organic attention divided by eligible organic impressions or exposures",
                "qualified_action_rate": "verified qualified actions divided by eligible sessions or conversations",
                "voluntary_relay_rate": "unprompted saves, shares, citations or remixes divided by qualified exposures",
                "brand_distinctiveness": "source-hidden human recognition of the intended brand without logo dependence",
                "b2b_sales_acceptance_rate": "sales-accepted qualified conversations divided by marketing-qualified handoffs",
                "b2c_retained_activation": "activated users retaining the defined value behavior at the owner-approved horizon",
                "verified_contribution_margin": "recognized revenue less reconciled variable delivery, media, refund and chargeback costs",
                "blocking_defect_escape_rate": "released assets with a later verified blocking defect divided by released assets",
                "experiment_decision_calibration": "agreement between preregistered decision thresholds and adjudicated outcomes",
                "cycle_time_to_reviewable_asset": "elapsed time from frozen brief to artifact eligible for named human review",
            },
            "vanity_views_are_key_results": False,
            "pipeline_is_revenue": False,
        },
        "handoff_graph": [
            "market_intelligence_lead -> audience_research_lead -> product_marketing_lead",
            "product_marketing_lead -> creative_strategy_director -> craft_specialists",
            "craft_specialists -> brand_safety_claims_lead -> named_human_release",
            "named_human_release -> platform_distribution_strategist -> aggregate_observation",
            "aggregate_observation -> growth_data_experimentation_lead -> agent_quality_learning_engineer",
            "agent_quality_learning_engineer -> frozen_replay -> gtm_general_manager_next_run_decision",
        ],
        "failure_curriculum_contract": {
            "coordinate_axes": ["market_domain", "role_capability", "atomic_skill", "failure_difficulty"],
            "failure_difficulties": ["audience_ambiguity", "evidence_conflict", "platform_constraint", "multi_asset_consistency", "longitudinal_drift", "tool_failure", "originality_boundary", "regulated_constraint"],
            "failed_output_becomes_automatic_training_data": False,
            "named_human_adjudication_required": True,
            "gold_repair_prefix_allowed_for_offline_shadow": True,
            "next_run_candidate_only": True,
        },
        "open_source_composition": [
            {"project": "pydantic/pydantic-ai", "revision": "bf2c7315ecc26d446b872c544bb501a01066b4e2", "reuse": "typed agent and tool contracts"},
            {"project": "temporalio/temporal", "revision": "ce1e067e41facf31e588f65da3b5eacd324e8fa3", "reuse": "durable workflow and recovery shadow"},
            {"project": "stanfordnlp/dspy", "revision": "c69136b29aca4c00ca6da7667f7b80783188980e", "reuse": "frozen-split prompt program optimization shadow"},
            {"project": "promptfoo/promptfoo", "revision": "82ca3c24ec445cf1734face46042c187b659b954", "reuse": "isolated adversarial and regression evaluation"},
            {"project": "mem0ai/mem0", "revision": "38e47ac2619b625ead46733db081251087f0c64b", "reuse": "tenant-scoped memory comparison shadow"},
            {"project": "getzep/graphiti", "revision": "4f62cfe7a2d519e55bfdf2dc4a2fd06649dc00b3", "reuse": "temporal knowledge graph comparison shadow"},
            {"project": "gitroomhq/postiz-app", "revision": "cf4c432c00c9db775ea1b1f12480a8e2b89aec32", "reuse": "isolated scheduling service reference"},
        ],
        "automatic_dependency_install_or_promotion": False,
        "automatic_external_action_count": 0,
        "human_release_required": True,
        "truth_boundary": (
            "This contract decomposes public product capability references into inspectable GTM "
            "craft roles, skills, artifacts and metrics. The cohorts are not rankings, public product "
            "surfaces are not internal org charts, and structural coverage does not prove human-level "
            "craft, organic growth, conversion, revenue causality or comparative superiority."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_gtm_team_capability_contract(payload)
    return payload


def verify_gtm_team_capability_contract(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != CONTRACT_SCHEMA:
        raise GTMTeamCapabilityError("GTM team capability schema is invalid")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMTeamCapabilityError("GTM team capability digest is invalid")
    registry = payload.get("full_skill_registry")
    if not isinstance(registry, Mapping) or registry.get("role_count") != len(ROLE_REGISTRY):
        raise GTMTeamCapabilityError("GTM role registry coverage drifted")
    if registry.get("skills_per_role") != SKILLS_PER_ROLE or registry.get("atomic_skill_count") != len(ROLE_REGISTRY) * SKILLS_PER_ROLE:
        raise GTMTeamCapabilityError("GTM atomic skill coverage drifted")
    active = payload.get("active_virtual_team")
    if not isinstance(active, Mapping) or active.get("active_role_count") != len(active.get("roles", [])):
        raise GTMTeamCapabilityError("GTM active team coverage drifted")
    if not active.get("one_accountable_general_manager") or "gtm_general_manager" not in {row.get("role_id") for row in active.get("roles", []) if isinstance(row, Mapping)}:
        raise GTMTeamCapabilityError("GTM team lacks one accountable general manager")
    if any(len(row.get("atomic_skill_ids", [])) != SKILLS_PER_ROLE for row in active.get("roles", []) if isinstance(row, Mapping)):
        raise GTMTeamCapabilityError("GTM active role skill coverage drifted")
    cohort = payload.get("reference_cohort_contract")
    if not isinstance(cohort, Mapping) or cohort.get("company_count") != 10:
        raise GTMTeamCapabilityError("GTM reference cohort coverage drifted")
    if cohort.get("selection_is_authoritative_ranking") is not False or cohort.get("internal_org_chart_or_private_performance_inferred") is not False:
        raise GTMTeamCapabilityError("GTM reference cohort overstates public evidence")
    okrs = payload.get("team_okr_contract")
    if not isinstance(okrs, Mapping) or okrs.get("vanity_views_are_key_results") is not False or okrs.get("pipeline_is_revenue") is not False:
        raise GTMTeamCapabilityError("GTM OKR truth boundary drifted")
    curriculum = payload.get("failure_curriculum_contract")
    if not isinstance(curriculum, Mapping) or curriculum.get("failed_output_becomes_automatic_training_data") is not False or curriculum.get("named_human_adjudication_required") is not True:
        raise GTMTeamCapabilityError("GTM failure curriculum is unsafe")
    if payload.get("automatic_dependency_install_or_promotion") is not False or payload.get("automatic_external_action_count") != 0 or payload.get("human_release_required") is not True:
        raise GTMTeamCapabilityError("GTM team capability release boundary drifted")
