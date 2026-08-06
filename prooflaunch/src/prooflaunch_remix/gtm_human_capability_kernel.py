from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMHumanCapabilityKernelV2"
SKILL_CARD_SCHEMA = "ProofLaunchGTMProfessionalSkillCardV2"
EXPECTED_ROLE_COUNT = 22
EXPECTED_SKILLS_PER_ROLE = 10
EXPECTED_SKILL_CARD_COUNT = 220
EXPECTED_PROFESSIONAL_AXIS_COUNT = 2_200
EXPECTED_EVAL_CHECK_COUNT = 2_200


class GTMHumanCapabilityKernelError(ValueError):
    """The human-capability kernel is incomplete, unbound, or unsafe."""


PROFESSIONAL_AXIS_IDS = (
    "01_context_diagnosis",
    "02_audience_decision_specificity",
    "03_evidence_and_proof_binding",
    "04_platform_native_grammar",
    "05_original_mechanism_synthesis",
    "06_professional_work_product",
    "07_mechanical_quality_gate",
    "08_subjective_craft_review",
    "09_bounded_failure_repair",
    "10_outcome_and_learning_handoff",
)


ROLE_STAGE: dict[str, str] = {
    "gtm_general_manager": "strategize",
    "market_intelligence_lead": "research",
    "product_marketing_lead": "strategize",
    "audience_research_lead": "diagnose",
    "creative_strategy_director": "design_system",
    "senior_social_copywriter": "produce",
    "longform_editorial_director": "produce",
    "short_video_director": "produce",
    "art_design_director": "produce",
    "audio_voice_producer": "produce",
    "platform_distribution_strategist": "prepare_release",
    "organic_growth_community_lead": "prepare_release",
    "creator_partnerships_lead": "prepare_release",
    "seo_geo_editor": "produce",
    "lifecycle_crm_strategist": "produce",
    "demand_generation_lead": "strategize",
    "product_led_growth_lead": "strategize",
    "sales_enablement_revops_lead": "observe",
    "growth_data_experimentation_lead": "observe",
    "agent_quality_learning_engineer": "learn_next_cycle",
    "brand_safety_claims_lead": "prepare_release",
    "localization_cultural_editor": "produce",
}


ROLE_SQUAD: dict[str, str] = {
    "gtm_general_manager": "01_portfolio_command",
    "market_intelligence_lead": "02_market_audience_intelligence",
    "audience_research_lead": "02_market_audience_intelligence",
    "product_marketing_lead": "03_positioning_and_proof",
    "creative_strategy_director": "04_creative_studio",
    "senior_social_copywriter": "04_creative_studio",
    "longform_editorial_director": "04_creative_studio",
    "short_video_director": "04_creative_studio",
    "art_design_director": "04_creative_studio",
    "audio_voice_producer": "04_creative_studio",
    "localization_cultural_editor": "04_creative_studio",
    "platform_distribution_strategist": "05_distribution_community",
    "organic_growth_community_lead": "05_distribution_community",
    "creator_partnerships_lead": "05_distribution_community",
    "seo_geo_editor": "05_distribution_community",
    "lifecycle_crm_strategist": "06_growth_and_lifecycle",
    "demand_generation_lead": "06_growth_and_lifecycle",
    "product_led_growth_lead": "06_growth_and_lifecycle",
    "sales_enablement_revops_lead": "07_revenue_operations",
    "growth_data_experimentation_lead": "08_measurement_learning_governance",
    "agent_quality_learning_engineer": "08_measurement_learning_governance",
    "brand_safety_claims_lead": "08_measurement_learning_governance",
}


SQUAD_MISSIONS: dict[str, str] = {
    "01_portfolio_command": "hold one coherent GTM thesis, decision rights, stop rules and portfolio trade-offs",
    "02_market_audience_intelligence": "turn current market and audience evidence into one falsifiable decision context",
    "03_positioning_and_proof": "bind category position, message hierarchy and objections to inspectable proof",
    "04_creative_studio": "produce platform-native text, image, video and audio with one creative spine and specialist craft",
    "05_distribution_community": "earn native distribution, search visibility, community participation and credible relays",
    "06_growth_and_lifecycle": "fit acquisition, activation, retention and demand work to lifecycle, budget and business model",
    "07_revenue_operations": "preserve stage, handoff, pipeline, recognized revenue and contribution-margin truth",
    "08_measurement_learning_governance": "measure, review, repair and promote changes without unsafe self-modification",
}


ROLE_OSS_PROJECTS: dict[str, tuple[str, ...]] = {
    "gtm_general_manager": ("pydantic_ai", "temporal", "openlineage"),
    "market_intelligence_lead": ("trafilatura", "crawl4ai", "bertopic", "ruptures"),
    "product_marketing_lead": ("qwen3_embedding", "graphrag", "promptfoo"),
    "audience_research_lead": ("duckdb", "polars", "sentence_transformers"),
    "creative_strategy_director": ("dspy", "promptfoo", "open_clip"),
    "senior_social_copywriter": ("dspy", "promptfoo", "qwen3_embedding"),
    "longform_editorial_director": ("docling", "trafilatura", "graphrag"),
    "short_video_director": ("comfyui", "wan22", "vbench"),
    "art_design_director": ("comfyui", "qwen_image", "open_clip", "paddleocr"),
    "audio_voice_producer": ("qwen3_tts", "ace_step15", "whisperx"),
    "platform_distribution_strategist": ("postiz", "temporal", "openlineage"),
    "organic_growth_community_lead": ("networkx", "sentence_transformers", "river"),
    "creator_partnerships_lead": ("networkx", "sentence_transformers", "dowhy"),
    "seo_geo_editor": ("open_seo", "siteone", "lighthouse", "networkx"),
    "lifecycle_crm_strategist": ("mautic", "pymc_marketing", "causalml"),
    "demand_generation_lead": ("twenty", "econml", "dowhy"),
    "product_led_growth_lead": ("posthog", "growthbook", "econml"),
    "sales_enablement_revops_lead": ("twenty", "duckdb", "openlineage"),
    "growth_data_experimentation_lead": ("growthbook", "dowhy", "econml", "meridian"),
    "agent_quality_learning_engineer": ("promptfoo", "cleanlab", "dspy", "evidently"),
    "brand_safety_claims_lead": ("opa", "presidio", "c2pa_rs", "promptfoo"),
    "localization_cultural_editor": ("weblate", "qwen3_embedding", "axe_core"),
}


B2B_ONLY = frozenset({"demand_generation_lead", "sales_enablement_revops_lead"})
B2C_ONLY = frozenset({"product_led_growth_lead", "creator_partnerships_lead"})


ROLE_PLATFORMS: dict[str, tuple[str, ...]] = {
    "short_video_director": ("tiktok", "instagram", "youtube"),
    "art_design_director": ("linkedin", "tiktok", "reddit", "youtube", "instagram", "x"),
    "audio_voice_producer": ("tiktok", "instagram", "youtube"),
    "longform_editorial_director": ("linkedin", "reddit", "youtube", "x"),
    "seo_geo_editor": ("reddit", "youtube"),
    "creator_partnerships_lead": ("tiktok", "instagram", "youtube"),
}


ROLE_LIFECYCLES: dict[str, tuple[str, ...]] = {
    "lifecycle_crm_strategist": ("growth", "mature"),
    "demand_generation_lead": ("launch", "growth", "mature"),
    "sales_enablement_revops_lead": ("launch", "growth", "mature"),
    "product_led_growth_lead": ("pre_pmf", "launch", "growth", "mature"),
    "creator_partnerships_lead": ("launch", "growth", "mature"),
}


def _surface(
    category: str,
    user_intent: str,
    native_format: str,
    strategy: str,
    copy: str,
    creative: str,
    breakout: str,
    anti_pattern: str,
) -> dict[str, str]:
    return {
        "category": category,
        "primary_user_intent": user_intent,
        "native_format_contract": native_format,
        "strategy_standard": strategy,
        "copy_editor_standard": copy,
        "creative_director_standard": creative,
        "organic_breakout_standard": breakout,
        "fail_closed_anti_pattern": anti_pattern,
    }


SURFACE_PLAYBOOKS: dict[str, dict[str, str]] = {
    "linkedin": _surface(
        "social",
        "learn from credible peers and make a professional decision",
        "expert post, document carousel, native video or evidence-led comment thread",
        "bind one decision-maker tension to an inspectable point of view and a useful professional action",
        "write with earned authority, concrete nouns, restrained claims and a line-by-line reason to continue",
        "turn proof into a portable framework, decision x-ray or before/after operating artifact",
        "measure qualified dwell, substantive comments, saves, profile-to-product progression and downstream conversations—not impressions alone",
        "generic thought leadership, engagement bait, corporate press-release voice or unsupported certainty",
    ),
    "tiktok": _surface(
        "social",
        "receive immediate entertainment, utility or surprising proof",
        "vertical short video with first-frame promise, spoken-native beats, captions and visible payoff",
        "choose one culturally legible tension and demonstrate the payoff before explanation expands",
        "use speakable language, compressed setup, pattern interruption and a CTA that belongs to the viewing moment",
        "direct performance, blocking, sound and edit rhythm so every beat changes tension, proof or payoff",
        "measure qualified 2-second hold, beat retention, completion, rewatch, share and attributable action by creative cohort",
        "horizontal-ad thinking, slow logo open, essay captions, copied trend expression or empty spectacle",
    ),
    "reddit": _surface(
        "social",
        "solve a specific problem through candid peer evidence and discussion",
        "community-native text, evidence post, transparent case analysis or useful comment contribution",
        "listen first, select the exact community norm and contribute stand-alone value before any product relevance",
        "write candidly, disclose affiliation, show trade-offs and answer the question without promotional throat-clearing",
        "make the evidence, comparison or teardown useful even if the reader never clicks",
        "measure moderator survival, substantive replies, saves, credible follow-up questions and qualified self-initiated visits",
        "astroturfing, copied cross-post, concealed affiliation, link drop, manufactured consensus or sales copy",
    ),
    "youtube": _surface(
        "social",
        "satisfy a durable information or entertainment session",
        "search-aware title and thumbnail, first-30-second contract, chaptered long video or native Short",
        "match one viewing intent, promise a specific payoff and design the sequence that earns the full session",
        "write title, thumbnail language, opening and transitions as one non-duplicative promise system",
        "direct visual proof, demonstrations, pattern changes and narrative escalation across the full retention curve",
        "measure qualified click-through, first-30-second retention, chapter retention, completion, return viewers and attributable action",
        "clickbait-promise mismatch, logo montage, narration without visual jobs or Shorts simply cut from longform",
    ),
    "instagram": _surface(
        "social",
        "discover visually legible identity, utility and shareable taste",
        "Reel, carousel, Story or visual post with image-first hierarchy and caption support",
        "select a save/share-worthy visual idea and make the brand role legible without relying on a logo",
        "keep on-frame language scannable; use caption for context, nuance and action rather than transcription",
        "build an ownable visual grammar, cover, sequence and motion system that survives silent viewing",
        "measure qualified hold, carousel completion, saves, shares, profile progression and attributable product action",
        "template sameness, caption-image duplication, illegible text, trend cloning or aesthetic without product truth",
    ),
    "x": _surface(
        "social",
        "scan timely arguments, compressed insight and live expert conversation",
        "single high-density post, evidence thread, visual data post or context-rich reply",
        "enter an existing conversation with a falsifiable thesis, useful evidence or a sharp conceptual compression",
        "write quotable but precise lines, remove throat-clearing and ensure every thread turn adds information",
        "pair text with one evidence object or visual model only when it increases comprehension",
        "measure qualified profile visits, bookmarks, informed replies, citations, thread completion and attributable action",
        "rage bait, vague aphorism, recycled thread, context collapse or unqualified certainty",
    ),
    "google_search": _surface(
        "search",
        "complete a query-defined task with trustworthy, accessible information",
        "indexable owned page with intent match, information gain, entity clarity, structured data and source citations",
        "choose the real query task and add original evidence or a decision tool beyond a paraphrase of ranking pages",
        "answer the primary query early, use descriptive headings and preserve expert nuance, definitions and source boundaries",
        "make tables, examples, diagrams and tools directly support the search task and remain accessible",
        "measure qualified organic sessions, task completion, citation/save behavior, conversion and controlled visibility change",
        "keyword stuffing, scaled thin pages, copied SERP consensus, hidden text or claims of assured ranking",
    ),
    "bing_search": _surface(
        "search",
        "complete a query-defined task through a crawlable, source-clear page",
        "crawlable owned page with explicit entities, semantic structure, technical health and current source provenance",
        "serve the user task first while making entity, product and evidence relationships unambiguous",
        "use concise answer blocks, source-visible detail and stable terminology across page, metadata and structured fields",
        "combine inspectable evidence, explanatory visuals and accessible page structure without decorative clutter",
        "measure qualified search visits, task completion, conversion and source-bound visibility change by frozen query set",
        "search-engine-specific folklore, doorway pages, copied answers, unverifiable freshness or claims of assured ranking",
    ),
    "chatgpt_answers": _surface(
        "geo",
        "receive a synthesized answer grounded in discoverable independent evidence",
        "source-clear owned answer asset with stable entities, quotable facts, original evidence and update dates",
        "make the brand genuinely useful to the question and independently corroborable instead of optimizing for mentions",
        "write extractable definitions, scoped claims and compact evidence blocks that retain meaning out of context",
        "design evidence tables and product facts that remain understandable when summarized without the original layout",
        "measure frozen-prompt citation share, entity accuracy, source diversity and qualified follow-on action with repeated panels",
        "prompt spam, fabricated citations, hidden-answer manipulation, claims of assured mentions or secret ranking logic",
    ),
    "claude_answers": _surface(
        "geo",
        "receive careful synthesis with explicit context, limitations and traceable evidence",
        "well-structured expert source with precise terminology, source hierarchy, limitations and durable URLs",
        "earn inclusion through high-information original analysis and transparent evidence boundaries",
        "preserve nuance, assumptions, counterexamples and citations while remaining extractable into a concise answer",
        "use legible structures that support long-context comparison and source-by-source verification",
        "measure frozen-prompt factual inclusion, citation accuracy, nuance preservation and qualified follow-on action",
        "citation laundering, generic AI prose, false consensus, source imitation or claims about hidden model preference",
    ),
    "gemini_answers": _surface(
        "geo",
        "receive a multimodal, entity-grounded answer connected to current discoverable sources",
        "entity-consistent text and media assets with descriptive metadata, provenance and accessible relationships",
        "make the entity, use case, evidence and media relationship easy to verify across owned sources",
        "use consistent naming, concise factual blocks and explicit temporal or geographic scope",
        "align text, image and video evidence so modalities reinforce rather than contradict one another",
        "measure frozen-prompt entity accuracy, citation inclusion, cross-modal consistency and qualified follow-on action",
        "entity ambiguity, mismatched media, unsupported recency, schema spam or claims about hidden ranking behavior",
    ),
    "perplexity_answers": _surface(
        "geo",
        "receive a citation-forward answer and inspect the supporting sources",
        "citation-dense original source with stable passages, explicit dates, named evidence and comparison-ready structure",
        "answer a real research question with primary evidence or novel synthesis worthy of direct citation",
        "make claims locally self-contained, source-adjacent and bounded so excerpts cannot overstate the evidence",
        "use comparison tables and source maps that expose provenance rather than merely decorate the page",
        "measure frozen-prompt citation inclusion, citation correctness, claim preservation and qualified follow-on action",
        "citation bait, derivative listicles, recycled statistics, inaccessible sources or claims of assured citation",
    ),
    "copilot_answers": _surface(
        "geo",
        "receive a useful answer connected to web or authorized enterprise context",
        "entity-clear public source or permission-aware enterprise artifact with explicit ownership and current evidence",
        "separate public discoverability from tenant-authorized knowledge and optimize neither by weakening permissions",
        "write stable terminology, action-oriented summaries and evidence-linked recommendations with explicit boundaries",
        "structure decision tables and workflow artifacts so permissions and provenance survive summarization",
        "measure frozen-prompt answer accuracy, permission correctness, citation inclusion and qualified workflow progression",
        "permission leakage, source ambiguity, unsupported action claims, hidden-ranking folklore or cross-tenant reuse",
    ),
}


HOLDING_SURFACE_PLAYBOOKS: dict[str, dict[str, str]] = {
    "owner_platform_unspecified": _surface(
        "holding_state",
        "preserve strategy and evidence until the owner selects a real distribution surface",
        "surface-neutral internal draft that is explicitly ineligible for final copy or release",
        "continue diagnosis, proof and concept work but require an owner platform decision before production admission",
        "do not claim platform-native tone, format, CTA or timing while the target surface is unknown",
        "keep the organizing idea editable and avoid surface-specific framing that would bias the later decision",
        "collect no platform-effect result and promote no breakout hypothesis until a real surface and frozen baseline exist",
        "silent platform guessing, generic copy labeled native, universal timing claims or release eligibility",
    )
}


def _edge(
    pattern: str,
    hook: str,
    progression: str,
    interaction: str,
    evidence: str,
    metrics: str,
) -> dict[str, str]:
    return {
        "pattern_name": pattern,
        "non_consensus_hook": hook,
        "progression_mechanic": progression,
        "participation_mechanic": interaction,
        "proof_object": evidence,
        "qualified_growth_measurement": metrics,
    }


EDGE_PLAY_ARCHETYPES: dict[str, dict[str, dict[str, str]]] = {
    "linkedin": {
        "b2b": _edge("decision_xray", "Expose one costly operating assumption the category treats as normal.", "diagnose the hidden cost, reveal the decision model, show proof, hand over the model", "invite peers to apply one decision criterion to their own workflow", "editable decision matrix with source-bound example", "qualified dwell, senior-practitioner saves, substantive replies and attributable conversations"),
        "b2c": _edge("professional_identity_reversal", "Challenge a work habit that signals competence but destroys the desired outcome.", "recognition, personal experiment, visible delta, reusable ritual", "invite a seven-day self-experiment with a public or private result template", "before/after workflow receipt and reusable template", "qualified saves, experiment starts, retained product activation and voluntary relays"),
    },
    "tiktok": {
        "b2b": _edge("operator_confession_demo", "Open on the embarrassing workflow failure, not the product claim.", "failure in frame one, live teardown, one decisive intervention, verified payoff", "let viewers choose the next workflow to dismantle without engagement coercion", "screen-recorded process proof with exact boundary", "two-second hold, proof-beat retention, qualified rewatches and attributable demo intent"),
        "b2c": _edge("choose_your_own_proof", "Make a surprising user choice determine which proof path plays next.", "choice, immediate consequence, visible transformation, replayable challenge", "offer meaningful branch choices that change the follow-up artifact", "real product state or owned test fixture", "branch participation, completion, rewatch, retained activation and verified referrals"),
    },
    "reddit": {
        "b2b": _edge("open_failure_teardown", "Publish the failure ledger competitors normally hide.", "context, what failed, mechanism, raw trade-offs, reusable diagnostic", "invite falsification and answer hard objections with disclosed affiliation", "source-linked teardown and downloadable diagnostic", "moderator survival, expert corrections, saves and self-initiated qualified visits"),
        "b2c": _edge("public_self_experiment", "Start with an honest result that contradicts the category's usual promise.", "baseline, protocol, daily evidence, failure, adjusted method", "let the community propose bounded next tests and report outcomes", "dated self-experiment log with limitations", "substantive replies, saves, protocol reuse and retained qualified users"),
    },
    "youtube": {
        "b2b": _edge("reverse_rfp_documentary", "Evaluate the buyer's real problem before revealing any vendor.", "decision criteria, competing approaches, live proof, failure cases, recommendation boundary", "publish the scorecard and let practitioners audit each criterion", "long-form evidence film plus editable scorecard", "qualified click-through, 30-second retention, chapter depth and sales-accepted conversations"),
        "b2c": _edge("constraint_transformation_series", "Promise a visible outcome under a constraint the category thinks is impossible.", "constraint, attempt, setback, adaptation, measured payoff", "give viewers a safe protocol to reproduce and compare", "serial before/after evidence with unchanged measurement rule", "return viewers, completion, protocol adoption, retained activation and voluntary shares"),
    },
    "instagram": {
        "b2b": _edge("visual_operating_system", "Turn an invisible business bottleneck into one unmistakable visual object.", "pain snapshot, system map, intervention, proof panel, relay card", "provide a remixable diagnostic carousel with attribution", "ownable visual framework and evidence panel", "carousel completion, saves, peer relays and qualified profile-to-product progression"),
        "b2c": _edge("identity_utility_relay", "Make the first frame both self-recognition and immediate utility.", "identity tension, visual shortcut, proof, personalized remix", "let people adapt an owned template to their use moment", "editable visual utility with product-truth example", "qualified holds, saves, remixes, retained activation and organic referrals"),
    },
    "x": {
        "b2b": _edge("falsifiable_live_thesis", "Make one category prediction precise enough to be wrong.", "thesis, evidence shards, counterargument, dated prediction, update ledger", "invite evidence-based counterexamples and publish adjudication", "public prediction ledger with sources and update dates", "bookmarks, informed replies, citations and attributable qualified conversations"),
        "b2c": _edge("build_in_public_constraint", "Reveal the constraint and ask the audience to watch the result, not applaud the intention.", "constraint, daily decision, proof artifact, failure, iteration", "offer a useful fork or template instead of an empty like request", "dated build log and reproducible mini-tool", "thread completion, bookmarks, tool reuse, retained activation and referrals"),
    },
    "google_search": {
        "b2b": _edge("buyer_decision_instrument", "Answer the expensive pre-purchase question competitors avoid.", "intent answer, diagnostic, alternatives, proof, decision rule", "let teams use an interactive vendor-neutral calculator or scorecard", "original dataset, calculator or decision model", "qualified organic task completion, tool usage, assisted conversion and controlled visibility delta"),
        "b2c": _edge("instant_personal_utility", "Deliver the useful result before asking for signup.", "direct answer, personalized tool, explanation, next action", "allow a no-login calculation or template preview with consented save", "interactive utility and transparent method", "task completion, repeat usage, retained activation and qualified conversion"),
    },
    "bing_search": {
        "b2b": _edge("entity_comparison_map", "Resolve one high-stakes category ambiguity with source-visible structure.", "entity map, criteria, evidence, exception, action", "offer an auditable comparison worksheet", "current entity graph and source table", "qualified search task completion, worksheet use and sales-accepted progression"),
        "b2c": _edge("decision_shortcut_with_limits", "Compress a confusing choice without hiding its trade-offs.", "choice frame, short diagnostic, result, limitations, next step", "provide a reversible decision path and comparison save", "transparent decision tree with dated inputs", "tool completion, saves, repeat visits and retained activation"),
    },
    "chatgpt_answers": {
        "b2b": _edge("citation_worthy_operating_data", "Publish the narrow operating evidence the category keeps anecdotal.", "method, finding, counterexample, implication, reusable artifact", "let experts inspect or extend the source-clear dataset", "original rights-clear dataset and methodology", "frozen-prompt citation accuracy, source diversity and attributable qualified action"),
        "b2c": _edge("answer_native_public_utility", "Create a tiny public utility that solves the question better than a brand mention.", "question, instant result, transparent method, optional deeper path", "allow citation and reuse with a stable canonical source", "open calculator, checklist or reference with update date", "frozen-prompt inclusion, citation correctness, utility reuse and retained activation"),
    },
    "claude_answers": {
        "b2b": _edge("counterexample_first_brief", "Lead with where the popular strategic answer fails.", "common model, counterexample, boundary conditions, decision framework", "invite expert falsification against a disclosed evidence set", "long-context source pack and limitation ledger", "frozen-prompt nuance preservation, citation accuracy and qualified workflow use"),
        "b2c": _edge("deep_choice_companion", "Turn a generic recommendation request into an inspectable personal decision.", "preference elicitation, trade-offs, bounded recommendation, reflection", "provide a portable decision brief users can refine", "source-clear decision worksheet", "answer accuracy, worksheet reuse, retained utility and qualified action"),
    },
    "gemini_answers": {
        "b2b": _edge("multimodal_proof_graph", "Connect one visual operating signal to the business decision it changes.", "entity, media evidence, relationship, decision, limitation", "let teams inspect the text/media evidence alignment", "provenance-bound multimodal case and entity map", "entity accuracy, cross-modal consistency, citation inclusion and qualified action"),
        "b2c": _edge("camera_to_decision_utility", "Start from the user's real visual context and return a verifiable next step.", "visual input, interpretation, alternatives, safe action, confirmation", "offer consented on-device or owned-fixture comparison", "rights-clear multimodal example and result card", "cross-modal accuracy, utility completion, retained activation and voluntary share"),
    },
    "perplexity_answers": {
        "b2b": _edge("primary_source_gap_report", "Answer a category question with primary evidence competitors merely summarize.", "research question, source map, finding, disagreement, decision implication", "publish an updateable citation ledger", "primary-source report with stable passages", "citation correctness, source inclusion, report reuse and qualified conversations"),
        "b2c": _edge("transparent_comparison_update", "Make the freshness and source disagreement visible before recommending.", "question, dated evidence, comparison, uncertainty, action", "let users inspect and save the source map", "current comparison table with change log", "citation accuracy, saves, return visits and qualified conversion"),
    },
    "copilot_answers": {
        "b2b": _edge("permission_aware_decision_packet", "Turn scattered authorized context into one auditable decision packet.", "permission check, evidence join, decision options, owner action", "route the packet for named human review instead of autonomous execution", "tenant-scoped decision artifact and provenance trace", "permission correctness, decision cycle time and verified workflow progression"),
        "b2c": _edge("cross_device_action_capsule", "Preserve one useful decision across devices without pretending to know more than the user allowed.", "consent, compact context, suggested action, confirmation, portable memory", "let the user edit, revoke or delete the capsule", "permission-bound portable action card", "context preservation, deletion correctness, retained utility and qualified action"),
    },
}


EDGE_PROHIBITED_TACTICS = (
    "fake_identity_or_social_proof",
    "manufactured_comments_shares_or_views",
    "undisclosed_automation_or_affiliation",
    "engagement_bait_without_user_value",
    "clickbait_promise_mismatch",
    "spam_or_nonconsensual_outreach",
    "captcha_paywall_rate_limit_or_access_control_bypass",
    "copying_competitor_expression_trade_dress_or_creator_identity",
)


def unconventional_edge_play(surface_id: str, business_model: str) -> dict[str, Any]:
    surface = normalize_surface_id(surface_id)
    model = str(business_model).strip().casefold()
    if surface in HOLDING_SURFACE_PLAYBOOKS:
        core: dict[str, Any] = {
            "edge_play_card_id": f"edge:{surface}:{model}",
            "surface_id": surface,
            "business_model": model,
            "status": "blocked_until_owner_selects_real_surface",
            "unconventional_not_deceptive": True,
            "external_activation_allowed": False,
            "prohibited_tactics": list(EDGE_PROHIBITED_TACTICS),
        }
    else:
        archetype = EDGE_PLAY_ARCHETYPES.get(surface, {}).get(model)
        if archetype is None:
            raise GTMHumanCapabilityKernelError(
                f"unconventional edge-play coverage missing: {surface}:{model}"
            )
        core = {
            "edge_play_card_id": f"edge:{surface}:{model}",
            "surface_id": surface,
            "business_model": model,
            **archetype,
            "status": "experiment_candidate_only",
            "recent_3_to_6_month_baseline_required": True,
            "one_variable_frozen_test_required": True,
            "falsifier": "stop or revise when the qualified downstream metric fails the preregistered threshold or a guardrail worsens",
            "unconventional_not_deceptive": True,
            "organic_only_by_default": True,
            "external_activation_allowed": False,
            "prohibited_tactics": list(EDGE_PROHIBITED_TACTICS),
        }
    core["edge_play_sha256"] = _digest(core)
    return core


def surface_playbook(surface_id: str) -> Mapping[str, str]:
    playbook = SURFACE_PLAYBOOKS.get(surface_id) or HOLDING_SURFACE_PLAYBOOKS.get(
        surface_id
    )
    if playbook is None:
        raise GTMHumanCapabilityKernelError(f"unsupported public surface: {surface_id}")
    return playbook


SURFACE_SPECIALIST_LENSES: tuple[tuple[str, str], ...] = (
    ("platform_strategy_director", "strategy_standard"),
    ("senior_native_copy_editor", "copy_editor_standard"),
    ("platform_creative_director", "creative_director_standard"),
    ("organic_breakout_analyst", "organic_breakout_standard"),
)


ROLE_SURFACES: dict[str, tuple[str, ...]] = {
    "senior_social_copywriter": ("linkedin", "tiktok", "reddit", "youtube", "instagram", "x"),
    "short_video_director": ("tiktok", "instagram", "youtube"),
    "art_design_director": ("linkedin", "tiktok", "reddit", "youtube", "instagram", "x"),
    "audio_voice_producer": ("tiktok", "instagram", "youtube"),
    "longform_editorial_director": ("linkedin", "reddit", "youtube", "x", "google_search", "bing_search"),
    "organic_growth_community_lead": ("linkedin", "tiktok", "reddit", "youtube", "instagram", "x"),
    "creator_partnerships_lead": ("tiktok", "instagram", "youtube"),
    "seo_geo_editor": ("reddit", "youtube", "google_search", "bing_search", "chatgpt_answers", "claude_answers", "gemini_answers", "perplexity_answers", "copilot_answers"),
}


def _surface_ids(role_id: str) -> list[str]:
    return list(
        ROLE_SURFACES.get(role_id, tuple(SURFACE_PLAYBOOKS))
        + tuple(HOLDING_SURFACE_PLAYBOOKS)
    )


def _surface_specialist_council() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for surface_id, playbook in SURFACE_PLAYBOOKS.items():
        for lens_id, standard_key in SURFACE_SPECIALIST_LENSES:
            core = {
                "specialist_lens_id": f"{surface_id}:{lens_id}",
                "surface_id": surface_id,
                "surface_category": playbook["category"],
                "professional_lens": lens_id,
                "acceptance_standard": playbook[standard_key],
                "required_evidence": (
                    "source-bound native artifact, named failure reasons, frozen baseline and "
                    "qualified downstream observation appropriate to the surface"
                ),
                "fail_closed_when": playbook["fail_closed_anti_pattern"],
                "hidden_algorithm_or_ranking_inference_allowed": False,
                "source_hidden_human_review_required": True,
            }
            core["lens_sha256"] = _digest(core)
            rows.append(core)
    return rows


COMPANY_SQUAD_REFERENCES: dict[str, tuple[str, ...]] = {
    "Microsoft": ("01_portfolio_command", "05_distribution_community", "08_measurement_learning_governance"),
    "Google Cloud": ("02_market_audience_intelligence", "05_distribution_community", "08_measurement_learning_governance"),
    "Salesforce": ("03_positioning_and_proof", "06_growth_and_lifecycle", "07_revenue_operations", "08_measurement_learning_governance"),
    "ServiceNow": ("01_portfolio_command", "07_revenue_operations", "08_measurement_learning_governance"),
    "Palantir": ("01_portfolio_command", "02_market_audience_intelligence", "08_measurement_learning_governance"),
    "Databricks": ("02_market_audience_intelligence", "08_measurement_learning_governance"),
    "Snowflake": ("02_market_audience_intelligence", "08_measurement_learning_governance"),
    "Adobe": ("04_creative_studio", "05_distribution_community", "06_growth_and_lifecycle", "08_measurement_learning_governance"),
    "HubSpot": ("05_distribution_community", "06_growth_and_lifecycle", "07_revenue_operations"),
    "Glean": ("02_market_audience_intelligence", "08_measurement_learning_governance"),
    "OpenAI": ("01_portfolio_command", "02_market_audience_intelligence", "04_creative_studio"),
    "Anthropic": ("01_portfolio_command", "02_market_audience_intelligence", "04_creative_studio"),
    "Google": ("02_market_audience_intelligence", "04_creative_studio", "05_distribution_community"),
    "Meta": ("04_creative_studio", "05_distribution_community", "06_growth_and_lifecycle"),
    "Perplexity": ("02_market_audience_intelligence", "03_positioning_and_proof", "05_distribution_community"),
    "Midjourney": ("04_creative_studio",),
    "Runway": ("04_creative_studio",),
    "Canva": ("04_creative_studio", "05_distribution_community"),
    "Character.AI": ("04_creative_studio", "06_growth_and_lifecycle"),
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _humanize(value: str) -> str:
    return value.replace("_", " ")


def normalize_surface_id(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")
    aliases = {
        "google": "google_search",
        "bing": "bing_search",
        "chatgpt": "chatgpt_answers",
        "claude": "claude_answers",
        "gemini": "gemini_answers",
        "perplexity": "perplexity_answers",
        "copilot": "copilot_answers",
    }
    return aliases.get(key, key)


def _verify_content_digest(payload: Mapping[str, Any], *, label: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMHumanCapabilityKernelError(f"{label} content digest is invalid")


def _business_models(role_id: str) -> list[str]:
    if role_id in B2B_ONLY:
        return ["b2b"]
    if role_id in B2C_ONLY:
        return ["b2c"]
    return ["b2b", "b2c"]


def _platforms(role_id: str, all_platforms: Sequence[str]) -> list[str]:
    return list(ROLE_PLATFORMS.get(role_id, tuple(all_platforms)))


def _lifecycles(role_id: str) -> list[str]:
    return list(
        ROLE_LIFECYCLES.get(role_id, ("pre_pmf", "launch", "growth", "mature"))
    )


def _professional_axes(
    *, role_id: str, skill_id: str, mission: str, quality_gate: str
) -> list[dict[str, str]]:
    skill = _humanize(skill_id)
    role = _humanize(role_id)
    specs = (
        (
            PROFESSIONAL_AXIS_IDS[0],
            f"Use {skill} only after reading the frozen company, lifecycle, budget, audience and channel context.",
            "context digest plus named unknowns and falsifiers",
            "the work starts from a generic category average or an unbound prompt",
        ),
        (
            PROFESSIONAL_AXIS_IDS[1],
            f"Apply {skill} to one primary B2B decision role or B2C use moment; do not average incompatible audiences.",
            "one role/use-moment binding and owner-confirmation state",
            "the output could be swapped unchanged across materially different audiences",
        ),
        (
            PROFESSIONAL_AXIS_IDS[2],
            f"Separate observation, inference and promise while using {skill} to advance the mission: {mission}.",
            "claim-to-source identifiers, freshness and rights state",
            "a promise lacks approved evidence or an inference is presented as observation",
        ),
        (
            PROFESSIONAL_AXIS_IDS[3],
            f"Express {skill} through the selected platform's native format, interaction norm, length and attention pattern.",
            "platform contract, format receipt and cross-platform difference log",
            "copy, pacing or CTA is merely pasted across platforms",
        ),
        (
            PROFESSIONAL_AXIS_IDS[4],
            f"Abstract mechanisms from references, then use {skill} to create a new combination, voice and brand memory device.",
            "mechanism-not-expression memo and originality comparison",
            "source expression, identity, trade dress or distinctive sequence is imitated",
        ),
        (
            PROFESSIONAL_AXIS_IDS[5],
            f"Produce the {role} work product required to demonstrate {skill}, not a role-play explanation of how it might be done.",
            "content-addressed editable artifact plus work-order identifier",
            "only advice, a checklist or an unverifiable completion claim is returned",
        ),
        (
            PROFESSIONAL_AXIS_IDS[6],
            f"Run deterministic schema, proof, identity, rights, accessibility and channel checks before subjective review of {skill}.",
            "machine-readable assertion receipt",
            "any code-checkable defect is delegated to an LLM judge",
        ),
        (
            PROFESSIONAL_AXIS_IDS[7],
            f"Review {skill} with focused binary craft judges and source-hidden humans against the role gate: {quality_gate}.",
            "independent review records with reasons and reviewer separation",
            "a vague helpfulness score, uncalibrated winner claim or producer self-approval is used",
        ),
        (
            PROFESSIONAL_AXIS_IDS[8],
            f"Repair the named {skill} failure only, preserve frozen strategy fields and stop after the bounded loop budget.",
            "before/after digests, exact finding, repair diff and stop reason",
            "the repair silently changes audience, proof, strategy, rights state or release authority",
        ),
        (
            PROFESSIONAL_AXIS_IDS[9],
            f"Hand off {skill} with leading and lagging KPI bindings, uncertainty, next evidence and a next-cycle candidate—not live self-modification.",
            "metric contract, trace, observation window and human promotion decision",
            "vanity metrics, pipeline-as-revenue, unobserved lift or current-run self-training is claimed",
        ),
    )
    return [
        {
            "axis_id": axis_id,
            "execution_requirement": requirement,
            "required_evidence": evidence,
            "fail_closed_when": failure,
        }
        for axis_id, requirement, evidence, failure in specs
    ]


def _evaluation_pyramid(skill_id: str) -> dict[str, list[str]]:
    skill = _humanize(skill_id)
    return {
        "level_1_code_assertions": [
            f"{skill} input and output schemas validate",
            f"{skill} artifact digest matches its work order",
            f"{skill} proof, rights and identity references resolve",
            f"{skill} platform and audience bindings are singular and explicit",
            f"{skill} cannot publish, send, spend or mutate strategy",
        ],
        "level_2_binary_judges": [
            f"Does the artifact visibly demonstrate {skill}?",
            f"Is {skill} platform-native, audience-specific and non-generic?",
            f"Is {skill} original and proof-consistent without source imitation?",
        ],
        "level_3_human_review": [
            f"Would a named senior practitioner accept the {skill} work product without major rework?",
            f"Does source-hidden comparison prefer the {skill} artifact and find zero blocking defect?",
        ],
    }


def _metric_contract(metric_id: str, owner_role_id: str, metric_class: str) -> dict[str, Any]:
    label = _humanize(metric_id)
    if metric_id.endswith("_rate") or "rate" in metric_id:
        unit = "ratio_0_to_1"
        formula = f"verified {label} events divided by eligible opportunities"
    elif "time" in metric_id or "latency" in metric_id:
        unit = "elapsed_time"
        formula = f"p50 and p95 elapsed time for {label} on completed eligible work"
    elif "error" in metric_id:
        unit = "absolute_or_relative_error"
        formula = f"predeclared error function for {label} on a held-out observation window"
    elif "count" in metric_id or "coverage" in metric_id:
        unit = "count_and_coverage_ratio"
        formula = f"valid {label} items divided by required eligible items"
    else:
        unit = "contract_specific_measure"
        formula = f"owner-approved numerator, denominator and observation window for {label}"
    return {
        "metric_id": metric_id,
        "owner_role_id": owner_role_id,
        "metric_class": metric_class,
        "unit": unit,
        "formula_contract": formula,
        "source_binding_required": True,
        "baseline_required_before_numeric_target": True,
        "causal_claim_allowed_without_registered_design": False,
        "pipeline_may_be_labeled_revenue": False,
        "vanity_impressions_may_stand_alone": False,
    }


def _role_okr(role_id: str, role: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "okr_id": f"okr:{role_id}",
        "objective": str(role["mission"]),
        "key_results": [
            {
                "kr_id": f"kr:{role_id}:work_product",
                "definition": "all required work products are content-bound, editable and reviewable",
                "target": "100_percent_structural_gate",
            },
            {
                "kr_id": f"kr:{role_id}:quality_gate",
                "definition": str(role["quality_gate"]),
                "target": "100_percent_structural_gate_before_human_review",
            },
            {
                "kr_id": f"kr:{role_id}:human_craft",
                "definition": "subjective craft is independently reviewed and blocking defects are zero",
                "target": None,
                "target_status": "requires_source_hidden_named_human_review",
            },
            {
                "kr_id": f"kr:{role_id}:observed_effect",
                "definition": "improve the role's lagging outcome against a frozen eligible control",
                "target": None,
                "target_status": "requires_baseline_power_check_observation_and_owner_approval",
            },
        ],
        "leading_kpi_ids": list(role["leading_kpi_ids"]),
        "lagging_kpi_ids": list(role["lagging_kpi_ids"]),
    }


def _company_reference_rows(reference_cohorts: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cohort_id, companies in reference_cohorts.items():
        if not isinstance(companies, list) or len(companies) != 10:
            raise GTMHumanCapabilityKernelError("each public capability cohort requires ten companies")
        for company in companies:
            name = str(company.get("company", ""))
            squads = COMPANY_SQUAD_REFERENCES.get(name)
            if not squads:
                raise GTMHumanCapabilityKernelError(f"company capability mapping missing: {name}")
            rows.append(
                {
                    "cohort_id": cohort_id,
                    "company": name,
                    "official_url": company.get("official_url"),
                    "public_capability_surface": company.get("capability_surface"),
                    "synthesized_squad_reference_ids": list(squads),
                    "is_authoritative_global_rank": False,
                    "internal_org_chart_inferred": False,
                    "performance_parity_claimed": False,
                }
            )
    return rows


def compile_gtm_human_capability_kernel(
    *,
    team_matrix: Mapping[str, Any],
    craft_matrix: Mapping[str, Any],
    adaptive_graph: Mapping[str, Any],
    open_source_radar: Mapping[str, Any],
    source_file_sha256: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _verify_content_digest(team_matrix, label="team capability matrix")
    _verify_content_digest(craft_matrix, label="craft handoff matrix")
    _verify_content_digest(adaptive_graph, label="adaptive capability graph")

    registry = team_matrix.get("role_skill_registry")
    if not isinstance(registry, Mapping):
        raise GTMHumanCapabilityKernelError("team role registry is missing")
    roles = registry.get("roles")
    if not isinstance(roles, Mapping) or len(roles) != EXPECTED_ROLE_COUNT:
        raise GTMHumanCapabilityKernelError("team role coverage drifted")
    if registry.get("skills_per_role") != EXPECTED_SKILLS_PER_ROLE:
        raise GTMHumanCapabilityKernelError("skills-per-role coverage drifted")
    if set(roles) != set(ROLE_STAGE) or set(roles) != set(ROLE_SQUAD):
        raise GTMHumanCapabilityKernelError("role execution binding coverage drifted")

    platforms = tuple(team_matrix["staffing_contexts"][index]["distribution_platform"] for index in range(len(team_matrix["staffing_contexts"])))
    all_platforms = tuple(dict.fromkeys(platforms))
    if set(all_platforms) != {"linkedin", "tiktok", "reddit", "youtube", "instagram", "x"}:
        raise GTMHumanCapabilityKernelError("platform coverage drifted")

    graph_nodes = adaptive_graph.get("graph_loop_harness", {}).get("nodes", [])
    loop_by_stage = {
        str(node.get("id")): str(node.get("loop"))
        for node in graph_nodes
        if isinstance(node, Mapping)
    }
    if not set(ROLE_STAGE.values()).issubset(loop_by_stage):
        raise GTMHumanCapabilityKernelError("one or more professional stages lack a graph node")

    projects = open_source_radar.get("projects")
    if not isinstance(projects, Mapping):
        raise GTMHumanCapabilityKernelError("open-source project registry is missing")
    referenced_projects = {project for values in ROLE_OSS_PROJECTS.values() for project in values}
    if not referenced_projects.issubset(projects):
        raise GTMHumanCapabilityKernelError("one or more OSS role adapters are not pinned in the radar")

    metric_registry: dict[str, dict[str, Any]] = {}
    role_okrs: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for role_id, role_value in roles.items():
        if not isinstance(role_value, Mapping):
            raise GTMHumanCapabilityKernelError(f"invalid role record: {role_id}")
        skills = role_value.get("atomic_skill_ids")
        if not isinstance(skills, list) or len(skills) != EXPECTED_SKILLS_PER_ROLE:
            raise GTMHumanCapabilityKernelError(f"role skill coverage drifted: {role_id}")
        role_okrs.append(_role_okr(role_id, role_value))
        for metric_class, metric_ids in (
            ("leading", role_value["leading_kpi_ids"]),
            ("lagging", role_value["lagging_kpi_ids"]),
        ):
            for metric_id in metric_ids:
                existing = metric_registry.get(metric_id)
                contract = _metric_contract(metric_id, role_id, metric_class)
                if existing is not None and existing != contract:
                    raise GTMHumanCapabilityKernelError(f"metric ownership collision: {metric_id}")
                metric_registry[metric_id] = contract

        for skill_id in skills:
            axes = _professional_axes(
                role_id=role_id,
                skill_id=str(skill_id),
                mission=str(role_value["mission"]),
                quality_gate=str(role_value["quality_gate"]),
            )
            evaluation = _evaluation_pyramid(str(skill_id))
            core: dict[str, Any] = {
                "schema": SKILL_CARD_SCHEMA,
                "skill_card_id": f"{role_id}:{skill_id}",
                "role_id": role_id,
                "squad_id": ROLE_SQUAD[role_id],
                "skill_id": skill_id,
                "job_to_be_done": f"Use {_humanize(str(skill_id))} to {role_value['mission']}.",
                "business_model_binding": _business_models(role_id),
                "lifecycle_binding": _lifecycles(role_id),
                "platform_binding": _platforms(role_id, all_platforms),
                "surface_specialization_binding": _surface_ids(role_id),
                "required_work_products": list(role_value["required_work_products"]),
                "graph_binding": {
                    "node_id": ROLE_STAGE[role_id],
                    "loop_id": loop_by_stage[ROLE_STAGE[role_id]],
                    "autonomy_level": "L2_deterministic_workflow_with_bounded_evaluator_optimizer",
                    "maximum_loop_iterations": adaptive_graph["coverage"]["maximum_node_loop_iteration_cap"],
                    "termination_conditions": [
                        "all mechanical assertions pass and subjective review admits the artifact",
                        "repair budget is exhausted",
                        "blocking rights evidence identity or permission defect is found",
                        "named human escalation is required",
                    ],
                },
                "professional_contract_axes": axes,
                "evaluation_pyramid": evaluation,
                "okr_id": f"okr:{role_id}",
                "leading_kpi_ids": list(role_value["leading_kpi_ids"]),
                "lagging_kpi_ids": list(role_value["lagging_kpi_ids"]),
                "oss_composition": [
                    {
                        "project_id": project_id,
                        "revision": projects[project_id].get("revision"),
                        "decision": projects[project_id].get("decision"),
                        "automatic_admission": False,
                    }
                    for project_id in ROLE_OSS_PROJECTS[role_id]
                ],
                "training_and_learning_boundary": {
                    "failure_coordinate": [
                        "business_model",
                        "industry",
                        "lifecycle",
                        "platform",
                        role_id,
                        str(skill_id),
                    ],
                    "gold_repair_prefix_allowed_in_offline_shadow": True,
                    "failed_output_auto_admitted": False,
                    "live_weight_update_allowed": False,
                    "next_run_human_promotion_required": True,
                },
                "permissions": {
                    "may_draft_or_analyze": True,
                    "may_publish_send_spend_or_contact": False,
                    "may_change_frozen_strategy_or_proof": False,
                    "may_promote_model_prompt_skill_or_policy": False,
                },
            }
            core["skill_card_sha256"] = _digest(core)
            cards.append(core)

    if len(cards) != EXPECTED_SKILL_CARD_COUNT:
        raise GTMHumanCapabilityKernelError("professional skill card coverage drifted")

    company_rows = _company_reference_rows(team_matrix["reference_cohorts"]["cohorts"])
    surface_council = _surface_specialist_council()
    edge_play_cards = [
        unconventional_edge_play(surface_id, business_model)
        for surface_id in SURFACE_PLAYBOOKS
        for business_model in ("b2b", "b2c")
    ]
    staffing_manifests: list[dict[str, Any]] = []
    activated_skill_cards: set[str] = set()
    for context in team_matrix["staffing_contexts"]:
        role_ids = list(context["active_role_ids"])
        card_ids = [card["skill_card_id"] for card in cards if card["role_id"] in role_ids]
        activated_skill_cards.update(card_ids)
        manifest = {
            "case_id": context["case_id"],
            "business_model": context["business_model"],
            "lifecycle": context["lifecycle"],
            "budget": context["budget"],
            "distribution_platform": context["distribution_platform"],
            "unconventional_edge_play_card_id": (
                f"edge:{context['distribution_platform']}:{context['business_model']}"
            ),
            "accountable_role_id": "gtm_general_manager",
            "active_role_ids": role_ids,
            "active_squad_ids": sorted({ROLE_SQUAD[role_id] for role_id in role_ids}),
            "active_skill_card_ids": card_ids,
            "active_professional_axis_count": len(card_ids) * len(PROFESSIONAL_AXIS_IDS),
            "external_action_authority": "named_human_only",
        }
        manifest["manifest_sha256"] = _digest(manifest)
        staffing_manifests.append(manifest)

    total_axes = sum(len(card["professional_contract_axes"]) for card in cards)
    total_eval_checks = sum(
        sum(len(checks) for checks in card["evaluation_pyramid"].values())
        for card in cards
    )
    kpi_binding_count = sum(
        len(card["leading_kpi_ids"]) + len(card["lagging_kpi_ids"])
        for card in cards
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "as_of": "2026-08-03",
        "design_contract": {
            "autonomy_level": "L2_plus_bounded_L3_research_fanout_only_after_eval_gate",
            "composition_patterns": [
                "routing",
                "prompt_chaining",
                "bounded_parallel_research",
                "evaluator_optimizer",
            ],
            "single_vs_multi_agent": "single_writer_depth_first_campaign_state_with_isolated_breadth_first_research_workers",
            "minimum_pass_rate_before_autonomy_escalation": 0.90,
            "models_providers_and_hardware_are_replaceable": True,
        },
        "public_reference_cohorts": {
            "company_count": len(company_rows),
            "b2b_company_count": sum("b2b" in row["cohort_id"] for row in company_rows),
            "b2c_company_count": sum("b2c" in row["cohort_id"] for row in company_rows),
            "authoritative_global_rank_claimed": False,
            "internal_org_chart_inferred": False,
            "performance_parity_claimed": False,
            "companies": company_rows,
        },
        "functional_squads": [
            {
                "squad_id": squad_id,
                "mission": mission,
                "role_ids": sorted(role_id for role_id, value in ROLE_SQUAD.items() if value == squad_id),
            }
            for squad_id, mission in SQUAD_MISSIONS.items()
        ],
        "surface_operating_system": {
            "surface_count": len(SURFACE_PLAYBOOKS),
            "social_surface_count": sum(row["category"] == "social" for row in SURFACE_PLAYBOOKS.values()),
            "search_surface_count": sum(row["category"] == "search" for row in SURFACE_PLAYBOOKS.values()),
            "geo_answer_surface_count": sum(row["category"] == "geo" for row in SURFACE_PLAYBOOKS.values()),
            "specialist_lenses_per_surface": len(SURFACE_SPECIALIST_LENSES),
            "specialist_lens_count": len(surface_council),
            "hidden_algorithm_or_ranking_inference_allowed": False,
            "playbooks": [
                {"surface_id": surface_id, **playbook}
                for surface_id, playbook in SURFACE_PLAYBOOKS.items()
            ],
            "specialist_council": surface_council,
            "unconventional_edge_play_contract": {
                "card_count": len(edge_play_cards),
                "business_models_per_surface": 2,
                "unconventional_not_deceptive": True,
                "prohibited_tactics": list(EDGE_PROHIBITED_TACTICS),
                "cards": edge_play_cards,
            },
        },
        "role_okrs": role_okrs,
        "metric_registry": sorted(metric_registry.values(), key=lambda item: item["metric_id"]),
        "professional_skill_cards": cards,
        "staffing_manifests": staffing_manifests,
        "graph_loop_harness": {
            "graph_nodes": graph_nodes,
            "skill_card_graph_binding_count": len(cards),
            "loop_iteration_cap": adaptive_graph["coverage"]["maximum_node_loop_iteration_cap"],
            "harness": adaptive_graph["graph_loop_harness"]["global_harness"],
            "external_action_count": 0,
        },
        "open_source_composition": {
            "pinned_radar_project_count": len(projects),
            "referenced_project_count": len(referenced_projects),
            "referenced_project_ids": sorted(referenced_projects),
            "automatic_install_or_promotion": False,
            "shadow_replay_and_named_human_admission_required": True,
        },
        "source_bindings": {
            "team_capability_matrix_content_sha256": team_matrix["content_sha256"],
            "craft_handoff_matrix_content_sha256": craft_matrix["content_sha256"],
            "adaptive_capability_graph_content_sha256": adaptive_graph["content_sha256"],
            "craft_handoff_work_order_count": craft_matrix["coverage"]["total_work_order_count"],
            "craft_handoff_skill_assignment_count": craft_matrix["coverage"]["selected_atomic_skill_assignment_count"],
            "named_product_pk_jobs_preserved": adaptive_graph["coverage"]["named_product_pk_jobs_preserved"],
            "named_product_pk_wins": adaptive_graph["coverage"]["named_product_pk_wins"],
            "source_file_sha256": dict(source_file_sha256 or {}),
        },
        "coverage": {
            "role_count": len(roles),
            "skills_per_role": EXPECTED_SKILLS_PER_ROLE,
            "professional_skill_card_count": len(cards),
            "professional_axes_per_skill": len(PROFESSIONAL_AXIS_IDS),
            "professional_axis_count": total_axes,
            "detail_expansion_factor_over_skill_name_inventory": total_axes // len(cards),
            "eval_checks_per_skill": total_eval_checks // len(cards),
            "eval_check_count": total_eval_checks,
            "kpi_binding_count": kpi_binding_count,
            "metric_contract_count": len(metric_registry),
            "role_okr_count": len(role_okrs),
            "functional_squad_count": len(SQUAD_MISSIONS),
            "surface_count": len(SURFACE_PLAYBOOKS),
            "surface_specialist_lens_count": len(surface_council),
            "unconventional_edge_play_card_count": len(edge_play_cards),
            "skill_to_surface_binding_count": sum(len(card["surface_specialization_binding"]) for card in cards),
            "staffing_context_count": len(staffing_manifests),
            "activated_skill_card_count": len(activated_skill_cards),
            "automatic_external_action_count": 0,
        },
        "promotion_gate": {
            "structural_coverage_is_effect_evidence": False,
            "llm_judge_is_final_authority": False,
            "source_hidden_human_review_required": True,
            "recent_3_to_6_month_organic_breakout_baseline_required": True,
            "qualified_action_and_conversion_observation_required": True,
            "comparative_superiority_claim_allowed_now": False,
        },
        "truth_boundary": (
            "This artifact proves a deterministic 22-role, 220-skill professional capability ontology, "
            "2,200 execution axes, 2,200 evaluation checks, 13 public-surface playbooks, 52 specialist "
            "lenses, context staffing and OSS/harness bindings. "
            "The twenty companies are user-requested public capability reference cohorts, not a verified "
            "global ranking or their internal org charts. Structural detail does not prove 4A craft, organic "
            "breakout, conversion, revenue causality or superiority; those remain blocked on source-hidden "
            "human review and observed outcomes against authorized recent baselines."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_gtm_human_capability_kernel(payload, open_source_radar=open_source_radar)
    return payload


def verify_gtm_human_capability_kernel(
    payload: Mapping[str, Any], *, open_source_radar: Mapping[str, Any] | None = None
) -> None:
    if payload.get("schema") != SCHEMA:
        raise GTMHumanCapabilityKernelError("human capability kernel schema is invalid")
    _verify_content_digest(payload, label="human capability kernel")
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping):
        raise GTMHumanCapabilityKernelError("human capability coverage is missing")
    expected = {
        "role_count": EXPECTED_ROLE_COUNT,
        "skills_per_role": EXPECTED_SKILLS_PER_ROLE,
        "professional_skill_card_count": EXPECTED_SKILL_CARD_COUNT,
        "professional_axes_per_skill": len(PROFESSIONAL_AXIS_IDS),
        "professional_axis_count": EXPECTED_PROFESSIONAL_AXIS_COUNT,
        "detail_expansion_factor_over_skill_name_inventory": 10,
        "eval_checks_per_skill": 10,
        "eval_check_count": EXPECTED_EVAL_CHECK_COUNT,
        "role_okr_count": EXPECTED_ROLE_COUNT,
        "functional_squad_count": len(SQUAD_MISSIONS),
        "surface_count": 13,
        "surface_specialist_lens_count": 52,
        "unconventional_edge_play_card_count": 26,
        "staffing_context_count": 144,
        "activated_skill_card_count": EXPECTED_SKILL_CARD_COUNT,
        "automatic_external_action_count": 0,
    }
    for key, value in expected.items():
        if coverage.get(key) != value:
            raise GTMHumanCapabilityKernelError(f"human capability coverage drifted: {key}")

    cards = payload.get("professional_skill_cards")
    if not isinstance(cards, list) or len(cards) != EXPECTED_SKILL_CARD_COUNT:
        raise GTMHumanCapabilityKernelError("professional skill cards are incomplete")
    if len({card.get("skill_card_id") for card in cards}) != len(cards):
        raise GTMHumanCapabilityKernelError("professional skill card identities collide")
    for card in cards:
        unsigned = dict(card)
        supplied = unsigned.pop("skill_card_sha256", None)
        if supplied != _digest(unsigned):
            raise GTMHumanCapabilityKernelError("professional skill card digest is invalid")
        axes = card.get("professional_contract_axes")
        if [axis.get("axis_id") for axis in axes or []] != list(PROFESSIONAL_AXIS_IDS):
            raise GTMHumanCapabilityKernelError("professional skill axes are incomplete")
        checks = card.get("evaluation_pyramid")
        if not isinstance(checks, Mapping) or sum(len(value) for value in checks.values()) != 10:
            raise GTMHumanCapabilityKernelError("professional skill eval pyramid is incomplete")
        permissions = card.get("permissions", {})
        if any(
            permissions.get(key) is not False
            for key in (
                "may_publish_send_spend_or_contact",
                "may_change_frozen_strategy_or_proof",
                "may_promote_model_prompt_skill_or_policy",
            )
        ):
            raise GTMHumanCapabilityKernelError("professional skill authority escalated")

    cohorts = payload.get("public_reference_cohorts", {})
    if (
        cohorts.get("company_count") != 20
        or cohorts.get("b2b_company_count") != 10
        or cohorts.get("b2c_company_count") != 10
        or cohorts.get("authoritative_global_rank_claimed") is not False
        or cohorts.get("internal_org_chart_inferred") is not False
        or cohorts.get("performance_parity_claimed") is not False
    ):
        raise GTMHumanCapabilityKernelError("public reference cohort boundary drifted")

    surfaces = payload.get("surface_operating_system", {})
    if (
        surfaces.get("surface_count") != 13
        or surfaces.get("social_surface_count") != 6
        or surfaces.get("search_surface_count") != 2
        or surfaces.get("geo_answer_surface_count") != 5
        or surfaces.get("specialist_lenses_per_surface") != 4
        or surfaces.get("specialist_lens_count") != 52
        or surfaces.get("hidden_algorithm_or_ranking_inference_allowed") is not False
    ):
        raise GTMHumanCapabilityKernelError("surface operating-system coverage drifted")
    council = surfaces.get("specialist_council")
    if not isinstance(council, list) or len(council) != 52:
        raise GTMHumanCapabilityKernelError("surface specialist council is incomplete")
    for row in council:
        unsigned = dict(row)
        supplied = unsigned.pop("lens_sha256", None)
        if supplied != _digest(unsigned):
            raise GTMHumanCapabilityKernelError("surface specialist lens digest is invalid")
        if row.get("hidden_algorithm_or_ranking_inference_allowed") is not False:
            raise GTMHumanCapabilityKernelError("a surface lens inferred hidden ranking logic")
    edge = surfaces.get("unconventional_edge_play_contract", {})
    edge_cards = edge.get("cards")
    if (
        edge.get("card_count") != 26
        or edge.get("business_models_per_surface") != 2
        or edge.get("unconventional_not_deceptive") is not True
        or not isinstance(edge_cards, list)
        or len(edge_cards) != 26
    ):
        raise GTMHumanCapabilityKernelError("unconventional edge-play coverage drifted")
    expected_edge_ids = {
        f"edge:{surface_id}:{business_model}"
        for surface_id in SURFACE_PLAYBOOKS
        for business_model in ("b2b", "b2c")
    }
    if {row.get("edge_play_card_id") for row in edge_cards} != expected_edge_ids:
        raise GTMHumanCapabilityKernelError("unconventional edge-play identities drifted")
    for row in edge_cards:
        unsigned = dict(row)
        supplied = unsigned.pop("edge_play_sha256", None)
        if supplied != _digest(unsigned):
            raise GTMHumanCapabilityKernelError("unconventional edge-play digest is invalid")
        if (
            row.get("unconventional_not_deceptive") is not True
            or row.get("external_activation_allowed") is not False
            or set(row.get("prohibited_tactics", [])) != set(EDGE_PROHIBITED_TACTICS)
        ):
            raise GTMHumanCapabilityKernelError("unconventional edge-play safety drifted")

    harness = payload.get("graph_loop_harness", {})
    if harness.get("external_action_count") != 0:
        raise GTMHumanCapabilityKernelError("capability kernel executed an external action")
    global_harness = harness.get("harness", {})
    if (
        global_harness.get("deny_by_default_tools") is not True
        or global_harness.get("human_approval_before_external_action") is not True
        or global_harness.get("automatic_publish_send_spend_or_strategy_mutation") is not False
    ):
        raise GTMHumanCapabilityKernelError("global harness boundary drifted")

    promotion = payload.get("promotion_gate", {})
    if (
        promotion.get("structural_coverage_is_effect_evidence") is not False
        or promotion.get("source_hidden_human_review_required") is not True
        or promotion.get("comparative_superiority_claim_allowed_now") is not False
    ):
        raise GTMHumanCapabilityKernelError("effect promotion boundary drifted")

    if open_source_radar is not None:
        projects = open_source_radar.get("projects", {})
        referenced = set(payload.get("open_source_composition", {}).get("referenced_project_ids", []))
        if not referenced.issubset(projects):
            raise GTMHumanCapabilityKernelError("unbound OSS project entered the kernel")
