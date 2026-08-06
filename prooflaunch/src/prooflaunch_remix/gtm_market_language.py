from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .gtm_strategy import BudgetTier, BusinessModel, CampaignStrategyInput, LifecycleStage


class MarketLanguageError(ValueError):
    """A market-language plan violated its closed, human-governed contract."""


CONTRACT_SCHEMA = "ProofLaunchMarketLanguageContractV1"
COPY_BIBLE_SCHEMA = "ProofLaunchPlatformCopyBibleV1"

B2B_CATEGORY_IDS = (
    "software_ai_data",
    "cybersecurity",
    "financial_services",
    "healthcare_life_sciences",
    "manufacturing_industrial",
    "retail_commerce",
    "professional_services",
    "media_marketing_sales",
    "education_hr",
    "logistics_mobility",
    "energy_climate",
    "public_sector",
)
B2C_CATEGORY_IDS = (
    "art_design",
    "books_reference",
    "business",
    "communications_social",
    "education",
    "entertainment_games",
    "finance",
    "food_drink",
    "health_fitness_medical",
    "lifestyle_beauty_parenting",
    "maps_navigation_travel",
    "music_audio",
    "news_magazines",
    "photo_video",
    "productivity_tools",
    "shopping",
    "sports",
    "weather",
)
B2B_ROLE_IDS = (
    "economic_buyer",
    "functional_owner",
    "technical_evaluator",
    "internal_champion",
    "end_user",
    "risk_procurement_or_compliance",
)
B2C_STATE_IDS = (
    "new_user",
    "active_user",
    "switcher",
    "advocate",
    "payer_or_household_influencer",
)

_B2B_CATEGORY_SPECS: dict[str, tuple[str, str, str, str]] = {
    "software_ai_data": ("tool sprawl versus inspectable leverage", "reproducible workflow and boundary", "precise operator language with visible inputs, handoffs and result", "autonomy theatre"),
    "cybersecurity": ("faster response versus uncontrolled risk", "threat path, control and residual risk", "calm adversarial specificity without fear inflation", "breach fearmongering"),
    "financial_services": ("economic upside versus fiduciary and model risk", "assumption ledger, audit trail and downside", "decision-grade language that separates observation, model and approval", "certain-return language"),
    "healthcare_life_sciences": ("better outcome versus evidence and patient safety", "validated workflow, population boundary and specialist review", "clinically restrained, human and evidence-bounded", "unsupported clinical implication"),
    "manufacturing_industrial": ("throughput versus downtime, safety and integration", "line-level before/after mechanism and failure mode", "concrete operational language tied to work cells and constraints", "digital transformation abstraction"),
    "retail_commerce": ("conversion versus margin, trust and repeat purchase", "merchandising or service moment with cohort economics", "customer-close language connecting choice friction to commercial consequence", "vanity conversion claim"),
    "professional_services": ("expertise scale versus trust and accountable judgment", "inspectable method, decision artifact and escalation boundary", "senior-practitioner language that makes judgment visible", "generic authority claim"),
    "media_marketing_sales": ("attention volume versus distinctive demand and revenue quality", "creative mechanism, audience response and downstream signal", "culturally current language with commercial and attribution discipline", "certain-virality language"),
    "education_hr": ("access and productivity versus learning, fairness and adoption", "use journey, competency evidence and affected-person safeguard", "supportive language that respects agency and context", "certain replacement or outcome language"),
    "logistics_mobility": ("speed versus reliability, utilization and exception cost", "route or handoff trace with exception recovery", "time-and-motion language grounded in service reality", "perfect optimization claim"),
    "energy_climate": ("transition value versus physical, regulatory and measurement reality", "system boundary, baseline and measured delta", "systems language that distinguishes modeled and observed impact", "unqualified green claim"),
    "public_sector": ("service improvement versus accessibility, procurement and public trust", "policy-to-service trace, accessibility and accountability", "plain public-value language without vendor triumphalism", "citizen-impact overclaim"),
}

_B2C_CATEGORY_SPECS: dict[str, tuple[str, str, str, str]] = {
    "art_design": ("creative freedom versus blank-canvas friction", "visible creation journey and editable result", "sensory, maker-native and identity-aware", "style imitation"),
    "books_reference": ("depth versus time and information overload", "source-clear answer, annotation or recall moment", "curious, literate and useful without borrowed authority", "summary masquerading as expertise"),
    "business": ("ambition versus operational overload", "one job completed with an inspectable artifact", "capable, economical and outcome-specific", "hustle cliché"),
    "communications_social": ("belonging versus noise, safety and performative connection", "real interaction moment and control surface", "socially fluent, inclusive and non-manipulative", "manufactured intimacy"),
    "education": ("progress versus anxiety and generic instruction", "one learning loop with feedback and mastery evidence", "encouraging, clear and learner-specific", "instant mastery promise"),
    "entertainment_games": ("novelty versus sustained delight and fair play", "play moment, mechanic and voluntary return signal", "playful, world-consistent and community-aware", "engagement compulsion"),
    "finance": ("control versus complexity, uncertainty and trust", "transparent calculation, permission and downside", "plain, calm and assumption-explicit", "certain-wealth language"),
    "food_drink": ("convenience versus taste, health, identity and occasion", "specific occasion, sensory proof and practical use", "vivid, appetite-aware and occasion-native", "unqualified health claim"),
    "health_fitness_medical": ("desired change versus effort, safety and habit fragility", "real use routine, limitation and progress measure", "empathetic, embodied and non-shaming", "certain body or health outcome language"),
    "lifestyle_beauty_parenting": ("aspiration versus authenticity, safety and daily complexity", "routine moment, material result and boundary", "warm, culturally aware and identity-respecting", "insecurity exploitation"),
    "maps_navigation_travel": ("discovery versus time, uncertainty and disruption", "door-to-door or in-trip recovery moment", "situational, vivid and confidence-building", "frictionless-everywhere claim"),
    "music_audio": ("expression versus discovery fatigue and production friction", "listen-before-after or creation control", "rhythmic, scene-aware and creator-respecting", "artist voice imitation"),
    "news_magazines": ("speed versus context, trust and overload", "source chain, update boundary and useful context", "direct, transparent and non-sensational", "certainty beyond evidence"),
    "photo_video": ("production quality versus time, control and sameness", "editable sequence from source to distinctive output", "visual, director-like and craft-specific", "cinematic adjective pile"),
    "productivity_tools": ("getting more done versus cognitive load and tool sprawl", "one interrupted job completed with control retained", "crisp, humane and workflow-specific", "productivity guilt"),
    "shopping": ("choice and value versus overload, fit and trust", "comparison or fit decision with price and return reality", "helpful, concrete and non-pressuring", "false scarcity"),
    "sports": ("performance and belonging versus effort, access and credibility", "practice, live moment or verified performance trace", "energetic, knowledgeable and fan-native", "unsupported performance promise"),
    "weather": ("preparedness versus uncertainty and alert fatigue", "location-time-specific decision and uncertainty range", "immediate, calm and action-oriented", "false precision"),
}

_B2B_ROLE_SPECS: dict[str, tuple[str, str, str, str]] = {
    "economic_buyer": ("justify priority and economic consequence", "payback, downside and opportunity cost", "approve a bounded next-step investment", "compress mechanism into decision economics without inventing ROI"),
    "functional_owner": ("improve the operating system they own", "adoption, workflow disruption and accountable result", "sponsor a controlled workflow trial", "speak in operating trade-offs, handoffs and measurable service levels"),
    "technical_evaluator": ("establish technical fit and inspectability", "integration, failure modes, security and maintainability", "run a reproducible technical evaluation", "show interfaces, constraints, observability and rollback"),
    "internal_champion": ("carry a credible case across the buying group", "being unable to answer objections or recruit peers", "relay a proof packet and convene review", "give quotable logic, objection handling and a shareable artifact"),
    "end_user": ("complete the job with less friction and more control", "workflow burden, loss of agency and unreliable output", "try one recognizable use moment", "use task-native language and make the first value visible"),
    "risk_procurement_or_compliance": ("bound exposure and verify obligations", "uncontrolled data, vendor, regulatory and exit risk", "approve or condition a governed evaluation", "lead with controls, evidence, residual risk and termination path"),
}

_B2C_STATE_SPECS: dict[str, tuple[str, str, str, str]] = {
    "new_user": ("recognize the use moment and reach first value", "setup cost, ambiguity and trust", "complete one reversible first session", "make the moment concrete and remove one real first-use barrier"),
    "active_user": ("deepen repeat value without increasing burden", "novelty decay and accumulated friction", "adopt one higher-value repeat behavior", "acknowledge existing competence and reveal a useful next layer"),
    "switcher": ("decide whether change is worth migration", "switching cost, lost history and regret", "compare on one decisive use case", "respect the current choice and prove migration plus differentiated value"),
    "advocate": ("help others receive value without social risk", "looking promotional or overclaiming", "share a useful artifact or story voluntarily", "make relay value stand alone without referral pressure"),
    "payer_or_household_influencer": ("judge value, safety and fit for another person", "waste, hidden cost and adverse impact", "review a transparent fit and control packet", "separate user delight from payer, guardian or household safeguards"),
}

_LIFECYCLE_SPECS = {
    LifecycleStage.PRE_PMF: ("falsify the sharpest problem and first-value assumption", "first-hand problem language plus a reversible prototype", "reach inflation before problem evidence"),
    LifecycleStage.LAUNCH: ("prove one narrow audience-message-channel wedge", "frozen baseline, direct response and an inspectable use or buying moment", "multi-segment launch theatre"),
    LifecycleStage.GROWTH: ("scale a repeatable mechanism without losing distinctiveness", "cohort quality, retention and downstream action", "copying the latest format without incrementality evidence"),
    LifecycleStage.MATURE: ("renew relevance, defend trust and create expansion", "segment-level incrementality, retention and category-memory movement", "brand refresh detached from customer behavior"),
}

_BUDGET_SPECS = {
    BudgetTier.ZERO: ("owned, earned, community, partner and product-loop distribution only", False, "one hero proof object, modular derivatives and manual high-fit participation"),
    BudgetTier.SMALL: ("organic core with bounded paid amplification only after an organic and conversion signal", True, "reuse proven components; cap experiments with preregistered stop rules"),
    BudgetTier.SCALED: ("organic learning remains the control; paid scales only incremental qualified outcomes", True, "parallel production with holdouts, fatigue monitoring and contribution-margin gates"),
}

_PLATFORM_SPECS: dict[str, tuple[str, str, tuple[str, ...], str, str]] = {
    "linkedin": ("operator-specific and defensible", "a work contradiction with an accountable consequence", ("text_post", "document_carousel", "expert_video"), "qualified dwell, saves, expert replies and qualified conversation", "audience-activity two-slot holdout in the owner timezone"),
    "tiktok": ("spoken, immediate, visually demonstrable and participation-ready", "a legible tension or payoff in the first beat", ("short_video", "reply_video", "creator_native_demo"), "first-seconds retention, completion, rewatch, share and qualified action", "same-format two-slot holdout; no universal best time"),
    "instagram": ("visually led, identity-aware and save-or-share useful", "one ownable visual rule and recognizable tension", ("reel", "carousel", "story_sequence"), "non-follower reach, saves, shares and qualified profile action", "account-insight two-slot holdout in the owner timezone"),
    "youtube": ("promise-matched, explanatory and retention-sustaining", "fulfil title or thumbnail expectation immediately", ("short", "demonstration_video", "evidence_explainer"), "appeal, retention, watch time, satisfaction and returning viewers", "audience analytics two-slot holdout by format"),
    "reddit": ("community-contextual, candid and useful before any ask", "the unresolved local problem under community norms", ("discussion", "useful_resource", "method_breakdown"), "substantive replies, moderator acceptance and voluntary relay", "community-observed window; moderator norms override schedule"),
    "x": ("compressed, timely, conversational and point-of-view led", "one falsifiable observation without preamble", ("single_post", "bounded_thread", "evidence_reply"), "qualified replies, bookmarks, quoted relays and qualified click", "same-topic two-slot holdout; event timing may be a declared covariate"),
    "email": ("permission-aware, reader-specific and state-transition led", "one recognized trigger or unresolved job in the subject and first line", ("plain_text_note", "proof_email", "lifecycle_sequence"), "qualified reply, evidence click, activation and unsubscribe or complaint", "send-time holdout within the owner-approved lifecycle window"),
    "seo_geo": ("answer-first, entity-clear, evidence-located and citation-friendly", "give the direct answer before brand narrative", ("decision_page", "comparison_page", "evidence_faq"), "qualified search entry, cited answer inclusion, evidence engagement and downstream action", "query-cohort and refresh-window comparison; ranking alone is not causal evidence"),
}

_COPY_BIBLE_DETAILS: dict[str, dict[str, object]] = {
    "linkedin": {
        "platform_job": "Earn professional attention and a decision-grade conversation from one named buying role.",
        "voice_rules": ["operator-to-operator", "specific business consequence", "defensible point of view", "short paragraphs"],
        "hook_rules": ["open with a work contradiction or observed decision cost", "name who owns the consequence", "avoid engagement bait"],
        "proof_rules": ["bind one inspectable claim", "show mechanism before outcome", "state whether the result is observed or hypothetical"],
        "cta_rules": ["request one bounded professional action", "prefer inspect, compare, reply, or run over generic learn-more"],
        "forbidden_patterns": ["thought-leadership cliché", "broetry", "fake confession", "pipeline certainty language", "unearned certainty"],
        "accessibility_rules": ["plain-text meaning survives without image", "carousel has reading order and alt text", "video has captions"],
    },
    "reddit": {
        "platform_job": "Contribute standalone utility inside a specific community before asking for attention.",
        "voice_rules": ["candid peer", "community vocabulary", "limitations volunteered", "no brand-first framing"],
        "hook_rules": ["start with the unresolved local problem", "show work or method", "respect title conventions"],
        "proof_rules": ["include reproducible detail", "separate experience from generalization", "disclose affiliation"],
        "cta_rules": ["invite critique or comparison", "links remain optional and policy-compliant"],
        "forbidden_patterns": ["astroturfing", "link drop", "manufactured testimonial", "cross-post template", "vote manipulation"],
        "accessibility_rules": ["descriptive link text", "tables have a prose summary", "media has transcript or alt text"],
    },
    "x": {
        "platform_job": "Create a compact, falsifiable point of view that earns qualified relay and reply.",
        "voice_rules": ["compressed", "conversational", "timely when relevant", "one idea per post"],
        "hook_rules": ["lead with the observation", "remove preamble", "make the claim quotable but bounded"],
        "proof_rules": ["attach the decisive datum or source", "threads add evidence rather than restating", "label inference"],
        "cta_rules": ["ask for a counterexample, test, or exact next step", "do not request empty engagement"],
        "forbidden_patterns": ["vague thread promise", "rage bait", "context collapse", "copy-pasted LinkedIn post", "certainty from one anecdote"],
        "accessibility_rules": ["image descriptions", "camel-case hashtags", "video captions", "links retain context"],
    },
    "tiktok": {
        "platform_job": "Make a problem, proof or transformation legible in the first beat and sustain watch intent.",
        "voice_rules": ["spoken-native", "immediate", "visually anchored", "creator-scale rather than ad-read"],
        "hook_rules": ["first frame contains tension or payoff", "spoken and visual hooks agree", "product relationship is visible by second three"],
        "proof_rules": ["demonstrate rather than describe", "use on-screen evidence", "do not imply universal outcome"],
        "cta_rules": ["one low-friction continuation", "match CTA to demonstrated value"],
        "forbidden_patterns": ["article read-aloud", "slow logo intro", "trend pasted onto product", "fake reaction", "retention trick without payoff"],
        "accessibility_rules": ["burned and machine-readable captions", "safe-area text", "speech remains intelligible without music"],
    },
    "instagram": {
        "platform_job": "Build visual recognition and save-or-share utility around one identity-relevant use moment.",
        "voice_rules": ["visually led", "identity-aware", "caption complements rather than narrates", "recognizable brand grammar"],
        "hook_rules": ["cover or first frame states the value", "one ownable visual rule", "reel motion begins immediately"],
        "proof_rules": ["show material or workflow evidence", "carousels progress rather than repeat", "disclose generated or sponsored context when required"],
        "cta_rules": ["save, share, compare, or inspect according to asset job", "avoid multi-action caption endings"],
        "forbidden_patterns": ["generic inspiration", "visual identity drift", "caption dumping", "false scarcity", "hashtag wall"],
        "accessibility_rules": ["alt text", "high-contrast overlays", "captioned reels", "carousel reading order"],
    },
    "youtube": {
        "platform_job": "Fulfil a precise title-thumbnail promise and compound trust through useful watch time.",
        "voice_rules": ["promise-matched", "explanatory", "editorially paced", "audience sophistication respected"],
        "hook_rules": ["confirm the promised outcome immediately", "open a specific information gap", "no unrelated cold open"],
        "proof_rules": ["show the method and limitation", "chapters map to viewer decisions", "source consequential claims"],
        "cta_rules": ["place CTA after delivered value", "choose one next video, tool, or decision step"],
        "forbidden_patterns": ["thumbnail-content mismatch", "length inflation", "generic montage", "unsupported before-after", "subscribe before value"],
        "accessibility_rules": ["edited captions", "chapter labels", "audible dialogue", "visual evidence described when necessary"],
    },
    "email": {
        "platform_job": "Move one permissioned reader from a known lifecycle state to one useful next state.",
        "voice_rules": ["reader-specific", "plainspoken", "one sender identity", "state and context aware"],
        "hook_rules": ["subject reflects a real trigger or job", "first line earns continuity", "no false reply prefix"],
        "proof_rules": ["one relevant proof object", "claims resolve to a source", "personalization never invents facts"],
        "cta_rules": ["one primary action", "destination and expected commitment are explicit"],
        "forbidden_patterns": ["fake urgency", "dark-pattern unsubscribe", "bulk-personalized fiction", "multiple competing CTAs", "unearned familiarity"],
        "accessibility_rules": ["semantic headings", "descriptive links", "plain-text alternative", "mobile-readable line length"],
    },
    "seo_geo": {
        "platform_job": "Resolve a search or answer-engine decision with original, citable information gain.",
        "voice_rules": ["answer-first", "entity-clear", "source-located", "updated and limitation-aware"],
        "hook_rules": ["state the direct answer", "match the declared intent", "surface the decision boundary early"],
        "proof_rules": ["include original evidence, tool, data, framework, or decision utility", "cite primary sources", "mark update date"],
        "cta_rules": ["offer the next logical decision aid", "do not interrupt the answer before value"],
        "forbidden_patterns": ["keyword padding", "citation laundering", "brand insertion without relevance", "AI-summary filler", "ranking claim as outcome"],
        "accessibility_rules": ["semantic document structure", "descriptive anchors", "table summaries", "structured data matches visible content"],
    },
}

_CATEGORY_ALIASES = {
    "ai gtm orchestration": "software_ai_data",
    "saas": "software_ai_data",
    "developer tools": "software_ai_data",
    "health and fitness": "health_fitness_medical",
    "health & fitness": "health_fitness_medical",
    "photo and video": "photo_video",
    "social": "communications_social",
    "travel": "maps_navigation_travel",
    "productivity": "productivity_tools",
}

_TOKEN = re.compile(r"[^a-z0-9]+")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _key(value: str) -> str:
    return _TOKEN.sub("_", value.strip().casefold()).strip("_")


def build_platform_copy_bible() -> dict[str, Any]:
    platforms: dict[str, Any] = {}
    for platform, detail in _COPY_BIBLE_DETAILS.items():
        native_formats = list(_PLATFORM_SPECS[platform][2])
        platforms[platform] = {
            "platform_job": detail["platform_job"],
            "native_formats": native_formats,
            "voice_rules": detail["voice_rules"],
            "hook_rules": detail["hook_rules"],
            "proof_rules": detail["proof_rules"],
            "cta_rules": detail["cta_rules"],
            "forbidden_patterns": detail["forbidden_patterns"],
            "accessibility_rules": detail["accessibility_rules"],
            "primary_measurement": _PLATFORM_SPECS[platform][3],
            "timing_experiment": _PLATFORM_SPECS[platform][4],
        }
    payload: dict[str, Any] = {
        "schema": COPY_BIBLE_SCHEMA,
        "platform_count": len(platforms),
        "platforms": platforms,
        "cross_platform_rules": {
            "same_campaign_spine_required": True,
            "identical_copy_across_platforms_allowed": False,
            "platform_job_must_change_the_asset": True,
            "universal_best_time_allowed": False,
            "algorithm_hack_claim_allowed": False,
            "human_release_required": True,
        },
        "truth_boundary": (
            "These are platform-native production contracts, not assurances of algorithmic reach, "
            "virality, conversion, ranking or answer-engine inclusion."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def resolve_reference_family(product_category: str, business_model: BusinessModel) -> tuple[str, str]:
    declared = _key(product_category)
    registry = _B2B_CATEGORY_SPECS if business_model is BusinessModel.B2B else _B2C_CATEGORY_SPECS
    if declared in registry:
        return declared, "exact_owner_declared_registry_match"
    alias = _CATEGORY_ALIASES.get(product_category.strip().casefold())
    if alias in registry:
        return alias, "bounded_alias_candidate_owner_confirmation_required"
    return "owner_declared_other", "unmapped_owner_category_requires_human_mapping"


def _resolve_role(role: str, business_model: BusinessModel) -> tuple[str, str]:
    key = _key(role)
    registry = _B2B_ROLE_SPECS if business_model is BusinessModel.B2B else _B2C_STATE_SPECS
    if key in registry:
        return key, "exact_owner_declared_role_match"
    return "owner_declared_other", "unmapped_primary_role_requires_human_mapping"


def _fallback_category(business_model: BusinessModel) -> tuple[str, str, str, str]:
    if business_model is BusinessModel.B2B:
        return ("category promise versus accountable adoption", "one owner-approved workflow and limitation", "owner-category language grounded in one decision", "generic enterprise language")
    return ("desired use moment versus trust and friction", "one owner-approved use journey and limitation", "owner-category language grounded in one use moment", "generic lifestyle language")


def _fallback_role(business_model: BusinessModel) -> tuple[str, str, str, str]:
    if business_model is BusinessModel.B2B:
        return ("complete one named buying decision", "role-specific objection remains unconfirmed", "request a bounded human-reviewed next step", "use owner-supplied decision language; do not infer a committee-average persona")
    return ("complete one named use or influence decision", "state-specific friction remains unconfirmed", "request a bounded human-reviewed next step", "use owner-supplied use-moment language; do not infer a mass-market persona")


def compile_market_language_contract(request: CampaignStrategyInput) -> dict[str, Any]:
    business_model = request.audience.business_model
    family, category_resolution = resolve_reference_family(request.product_category, business_model)
    role, role_resolution = _resolve_role(request.audience_role, business_model)
    category_registry = _B2B_CATEGORY_SPECS if business_model is BusinessModel.B2B else _B2C_CATEGORY_SPECS
    role_registry = _B2B_ROLE_SPECS if business_model is BusinessModel.B2B else _B2C_STATE_SPECS
    tension, proof_mode, category_language, category_anti_pattern = category_registry.get(
        family, _fallback_category(business_model)
    )
    decision_job, skepticism, action, role_language = role_registry.get(
        role, _fallback_role(business_model)
    )
    lifecycle_job, lifecycle_evidence, lifecycle_anti_pattern = _LIFECYCLE_SPECS[request.lifecycle]
    organic_posture, paid_allowed, production_constraint = _BUDGET_SPECS[request.budget]
    platform_key = _key(request.distribution_platform)
    platform = _PLATFORM_SPECS.get(
        platform_key,
        (
            "native to the owner-declared platform and one decision",
            "context-specific value before brand explanation",
            ("platform_native_primary_format",),
            "qualified attention, voluntary relay and downstream action",
            "same-format two-slot holdout in the owner timezone",
        ),
    )
    copy_bible = build_platform_copy_bible()
    copy_bible_entry = copy_bible["platforms"].get(platform_key)
    language_signature_input = {
        "business_model": business_model.value,
        "family": family,
        "role": role,
        "lifecycle": request.lifecycle.value,
        "budget": request.budget.value,
        "platform": platform_key,
        "surface": request.product_surface.value,
        "category_language": category_language,
        "role_language": role_language,
    }
    payload: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "context": {
            "business_model": business_model.value,
            "owner_declared_industry": request.industry,
            "owner_declared_product_category": request.product_category,
            "resolved_reference_family": family,
            "category_resolution": category_resolution,
            "product_surface": request.product_surface.value,
            "owner_declared_audience_role": request.audience_role,
            "resolved_primary_role": role,
            "role_resolution": role_resolution,
            "primary_named_audience": request.audience.name,
            "lifecycle": request.lifecycle.value,
            "budget": request.budget.value,
            "distribution_platform": request.distribution_platform,
        },
        "category_contract": {
            "market_tension": tension,
            "proof_mode": proof_mode,
            "language_shape": category_language,
            "anti_pattern": category_anti_pattern,
        },
        "primary_audience_contract": {
            "primary_role_count": 1,
            "decision_or_use_job": decision_job,
            "dominant_skepticism": skepticism,
            "bounded_action": action,
            "language_shape": role_language,
            "committee_or_mass_average_voice_forbidden": True,
        },
        "lifecycle_contract": {
            "operating_job": lifecycle_job,
            "minimum_evidence": lifecycle_evidence,
            "forbidden_shortcut": lifecycle_anti_pattern,
        },
        "budget_contract": {
            "organic_posture": organic_posture,
            "paid_activation_allowed": paid_allowed,
            "production_constraint": production_constraint,
            "organic_breakout_is_not_paid_reach": True,
        },
        "platform_translation": {
            "language_shape": platform[0],
            "opening_contract": platform[1],
            "primary_formats": list(platform[2]),
            "qualified_signals": platform[3],
            "timing_method": platform[4],
            "cross_platform_copy_paste_forbidden": True,
            "universal_best_time_assumed": False,
        },
        "platform_copy_bible_binding": {
            "schema": COPY_BIBLE_SCHEMA,
            "platform": platform_key,
            "copy_bible_sha256": copy_bible["content_sha256"],
            "binding_status": (
                "sealed_platform_contract"
                if isinstance(copy_bible_entry, Mapping)
                else "owner_platform_requires_human_authored_contract"
            ),
            "platform_contract": copy_bible_entry,
            "copy_paste_across_platforms_allowed": False,
        },
        "last_mile_message_spine": {
            "one_audience": request.audience.name,
            "one_role": role,
            "one_tension": tension,
            "one_proof_object": proof_mode,
            "one_platform_opening": platform[1],
            "one_bounded_action": action,
            "required_original_recombination_dimensions": [
                "category_tension",
                "role_decision_job",
                "owner_approved_proof",
                "platform_native_structure",
            ],
        },
        "audience_asset_contract": {
            "allowed_assets": [
                "owner-consented first-party aggregate behavior",
                "owner-approved interview themes",
                "public aggregate category signals",
                "de-identified qualified outcome cohorts",
            ],
            "raw_personal_identity_ingestion_allowed": False,
            "source_creator_identity_exposed_to_generator": False,
            "owner_confirmation_required": True,
        },
        "open_source_reuse_contract": {
            "program_optimization_shadow": "stanfordnlp/dspy@c69136b29aca4c00ca6da7667f7b80783188980e",
            "drift_shadow": "online-ml/river@f5a1db99765b8660d86a3f424acc68409d8f3e45",
            "change_point_shadow": "deepcharles/ruptures@ee1c8ff8a548d54c641b2bb471562165931f31c7",
            "holdout_shadow": "growthbook/growthbook@4ad7fe7c5c587ff979a9408d566013d32a2a4fb2",
            "offline_policy_shadow": "VowpalWabbit/vowpal_wabbit@5801d8203d646b989180665753744ccc72d24065",
            "automatic_install_or_promotion": False,
            "frozen_replay_and_human_promotion_required": True,
        },
        "evaluation_scorecard": {
            "gates": [
                "role_specificity",
                "category_truth",
                "platform_nativeness",
                "proof_inspectability",
                "brand_distinctiveness",
                "qualified_action_clarity",
                "expression_originality",
            ],
            "vanity_reach_is_success": False,
            "named_human_blind_review_required": True,
            "three_to_six_month_live_comparator_required_for_breakout_claim": True,
        },
        "self_evolution_boundary": {
            "next_run_candidate_only": True,
            "current_run_mutation_allowed": False,
            "automatic_publish_send_or_spend_allowed": False,
            "feedback_windows_days": [7, 28, 90, 180],
        },
        "language_signature_sha256": _digest(language_signature_input),
        "external_action_count": 0,
        "human_release_required": True,
        "truth_boundary": (
            "This contract binds an owner-declared market, role, lifecycle, budget and platform "
            "to a differentiated language job. It does not classify an app, prove virality, "
            "attribute revenue, authorize copying, or establish superiority over a named product."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_market_language_contract(payload)
    return payload


def verify_market_language_contract(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != CONTRACT_SCHEMA:
        raise MarketLanguageError("market-language schema is invalid")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise MarketLanguageError("market-language digest is invalid")
    context = payload.get("context")
    if not isinstance(context, Mapping):
        raise MarketLanguageError("market-language context is missing")
    if context.get("business_model") not in {item.value for item in BusinessModel}:
        raise MarketLanguageError("market-language business model is invalid")
    if payload.get("primary_audience_contract", {}).get("primary_role_count") != 1:
        raise MarketLanguageError("market-language plan must bind exactly one primary role")
    if payload.get("audience_asset_contract", {}).get("owner_confirmation_required") is not True:
        raise MarketLanguageError("market-language category and role lost owner confirmation")
    if payload.get("audience_asset_contract", {}).get("raw_personal_identity_ingestion_allowed") is not False:
        raise MarketLanguageError("market-language plan enabled raw identity ingestion")
    if context.get("budget") == BudgetTier.ZERO.value and payload.get("budget_contract", {}).get("paid_activation_allowed") is not False:
        raise MarketLanguageError("zero-budget market-language plan enabled paid activation")
    platform = payload.get("platform_translation")
    if not isinstance(platform, Mapping) or platform.get("cross_platform_copy_paste_forbidden") is not True:
        raise MarketLanguageError("market-language platform translation is invalid")
    copy_bible_binding = payload.get("platform_copy_bible_binding")
    if not isinstance(copy_bible_binding, Mapping):
        raise MarketLanguageError("platform Copy Bible binding is missing")
    if copy_bible_binding.get("platform") != _key(str(context.get("distribution_platform", ""))):
        raise MarketLanguageError("platform Copy Bible binding drifted")
    if copy_bible_binding.get("copy_paste_across_platforms_allowed") is not False:
        raise MarketLanguageError("platform Copy Bible enabled cross-platform copy-paste")
    if copy_bible_binding.get("binding_status") == "sealed_platform_contract":
        expected = build_platform_copy_bible()
        if (
            copy_bible_binding.get("copy_bible_sha256") != expected["content_sha256"]
            or copy_bible_binding.get("platform_contract")
            != expected["platforms"].get(copy_bible_binding.get("platform"))
        ):
            raise MarketLanguageError("platform Copy Bible seal is invalid")
    if payload.get("self_evolution_boundary", {}).get("current_run_mutation_allowed") is not False:
        raise MarketLanguageError("market-language plan enabled current-run mutation")
    if payload.get("external_action_count") != 0 or payload.get("human_release_required") is not True:
        raise MarketLanguageError("market-language release boundary is invalid")
    signature = payload.get("language_signature_sha256")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise MarketLanguageError("market-language signature is invalid")
