from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .gtm_creative_alpha import (
    CreativeAlphaError,
    compile_creative_alpha_plan,
    verify_creative_alpha_plan,
)
from .gtm_craft_handoff import (
    GTMCraftHandoffError,
    compile_gtm_craft_handoff_plan,
    verify_gtm_craft_handoff_plan,
)
from .gtm_generative_execution_kernel import (
    GTMGenerativeExecutionKernelError,
    compile_generative_execution_kernel,
    verify_generative_execution_kernel,
)
from .gtm_multimodal_breakout_factory import (
    GTMMultimodalBreakoutFactoryError,
    compile_multimodal_breakout_factory,
    verify_multimodal_breakout_factory,
)
from .gtm_strategy import CampaignStrategyInput, Channel, GTMStrategy


class TextChallengerError(ValueError):
    """A text challenger plan or model response violated the creative contract."""


LEGACY_PLAN_SCHEMA = "ProofLaunchTextCreativeChallengerPlanV1"
CREATIVE_ALPHA_PLAN_SCHEMA = "ProofLaunchTextCreativeChallengerPlanV2"
PLAN_SCHEMA = "ProofLaunchTextCreativeChallengerPlanV3"
CANDIDATE_SCHEMA = "ProofLaunchTextCreativeCandidateV1"
QUALITY_GATE_SCHEMA = "ProofLaunchTextCreativeQualityGateV1"
_CANDIDATE_FIELDS = frozenset(
    {
        "schema",
        "territory_id",
        "strategy_id",
        "proof_claim_id",
        "cultural_tension",
        "organizing_idea",
        "participation_mechanism",
        "share_trigger",
        "proof_role",
        "falsifier",
        "factual_claims",
        "channels",
    }
)
_CHANNEL_FIELDS = frozenset(
    {"channel", "native_format", "hook", "body", "cta", "disclosure"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE = (
    re.compile(r"\bguarantee(?:d|s)?\b", re.IGNORECASE),
    re.compile(r"\bwill\s+(?:go\s+viral|drive\s+revenue)\b", re.IGNORECASE),
    re.compile(r"\b(?:4a|top\s*1|best[- ]in[- ]class|world[- ]class)\b", re.IGNORECASE),
    re.compile(r"保证(?:爆款|营收|转化|效果)"),
    re.compile(r"必然(?:爆款|营收|转化|增长)"),
)
_PLACEHOLDER = (
    re.compile(r"\bnon[- ]?blank string\b", re.IGNORECASE),
    re.compile(r"\b(?:placeholder|lorem ipsum|todo|tbd|fixme)\b", re.IGNORECASE),
    re.compile(r"\b(?:insert|write|replace|add)\s+(?:copy|text|content|sentence|phrase)\b", re.IGNORECASE),
    re.compile(r"\b(?:example|sample)\s+(?:copy|text|content)\b", re.IGNORECASE),
    re.compile(r"\b2\s+to\s+5\s+concise\s+blocks\b", re.IGNORECASE),
    re.compile(r"\bdo not copy this instruction\b", re.IGNORECASE),
    re.compile(r"\byour\s+.+\s+here\b", re.IGNORECASE),
    re.compile(r"待补充|占位|示例文案|此处填写"),
)
_STRATEGY_MINIMUM_CHARACTERS = {
    "cultural_tension": 42,
    "organizing_idea": 36,
    "participation_mechanism": 36,
    "share_trigger": 40,
    "proof_role": 36,
    "falsifier": 48,
}
_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?|[\u3400-\u9fff]")
_CTA_REPEATED_PUNCTUATION = re.compile(r"[.!?。！？]{2,}")
_CHANNEL_CORE_JACCARD_MAXIMUM = 0.80
_TERRITORY_JACCARD_MAXIMUM = 0.86
_PORTFOLIO_CHANNEL_JACCARD_MAXIMUM = 0.82
_SCENARIO_DIMENSIONS = ("business_model", "lifecycle", "budget", "industry_risk")
_SCENARIO_LENSES: dict[str, dict[str, dict[str, Any]]] = {
    "business_model": {
        "b2b": {
            "job": "make the multi-person buying decision inspectable",
            "markers": ("committee", "buying group", "decision"),
        },
        "b2c": {
            "job": "turn an individual use moment into identity-relevant participation",
            "markers": ("use moment", "identity", "customer", "participant"),
        },
    },
    "lifecycle": {
        "pre_pmf": {
            "job": "falsify the problem and recruit co-creation signals before scaling",
            "markers": ("falsify", "co-create", "problem", "signal"),
        },
        "launch": {
            "job": "earn category entry by sequencing first proof before the launch ask",
            "markers": ("launch", "first proof", "introduce", "entry", "pilot", "offer"),
        },
        "growth": {
            "job": "convert proven value into a repeatable activation and referral loop",
            "markers": ("repeatable", "activation", "referral", "loop"),
        },
        "mature": {
            "job": "reframe the category default and create a credible reactivation reason",
            "markers": ("reframe", "default", "reactivation", "renew"),
        },
    },
    "budget": {
        "zero": {
            "job": "use founder-led, community and earned participation without paid reach",
            "markers": ("peer", "community", "founder", "earned", "unpaid", "card"),
        },
        "small": {
            "job": "concentrate owned content, micro-creator collaboration and one measurable community loop",
            "markers": ("owned", "micro-creator", "community", "concentrate"),
        },
        "scaled": {
            "job": "sequence distinctive brand codes and channel orchestration while preserving one proof spine",
            "markers": ("sequence", "orchestration", "brand code", "proof spine"),
        },
    },
    "industry_risk": {
        "standard": {
            "job": "keep every assertion inside the approved claim boundary",
            "markers": ("proof", "evidence", "claim", "boundary"),
        },
        "high_regulation": {
            "job": "make compliance-safe education and the approved claim boundary part of the idea",
            "markers": ("compliance", "educational", "claim boundary", "approved proof"),
        },
    },
}
_CHANNEL_NATIVE_MARKERS: dict[str, tuple[str, ...]] = {
    "community_listening": ("moderated", "community question", "listening thread"),
    "creator_community": ("creator brief", "creator collaboration", "recreate"),
    "customer_evidence": ("evidence card", "customer evidence", "case note"),
    "customer_email": ("email", "subject line", "reply"),
    "founder_conversations": ("one-to-one interview", "founder interview", "interview"),
    "linkedin_organic": ("linkedin", "text post", "professional thread"),
    "owned_social": ("carousel", "owned social", "caption"),
    "partner_communities": ("partner discussion", "partner community", "working session"),
    "search_education": ("query-led explainer", "search explainer", "search question"),
    "short_video_organic": ("vertical short-video", "opening frame", "on-screen proof"),
    "paid_search": ("search-ad draft", "headline and description", "manual activation"),
    "paid_social": ("paid-social draft", "frame sequence", "manual activation"),
}
_TERRITORIES = (
    {
        "territory_id": "decision_xray",
        "creative_job": "turn the hidden decision friction into something the audience can inspect and name",
        "opening_device": "an unresolved question or contradiction, not a product boast",
        "participation_device": "invite the audience to identify the missing proof or limiting condition",
        "difference_from_baseline": "lead with the decision tension before revealing the approved proof",
    },
    {
        "territory_id": "proof_before_promise",
        "creative_job": "make the approved evidence and its limitations the dramatic center of the execution",
        "opening_device": "show the proof object, number or observable behavior before explaining the offer",
        "participation_device": "ask the audience to test whether the evidence resolves their real objection",
        "difference_from_baseline": "replace generic evidence language with a concrete proof-reveal sequence",
    },
    {
        "territory_id": "voluntary_relay",
        "creative_job": "make a useful decision object that a recipient may voluntarily pass to a relevant peer",
        "opening_device": "offer a reusable diagnostic, checklist, question or micro-demonstration",
        "participation_device": "let the recipient adapt or challenge the object without endorsing the brand",
        "difference_from_baseline": "optimize for recipient utility and peer transfer rather than immediate conversion",
    },
)


def _scenario_lens_from_values(values: Mapping[str, str]) -> dict[str, Any]:
    dimensions: dict[str, Any] = {}
    for dimension in _SCENARIO_DIMENSIONS:
        value = values[dimension]
        profile = _SCENARIO_LENSES[dimension][value]
        dimensions[dimension] = {
            "value": value,
            "job": profile["job"],
            "markers": list(profile["markers"]),
        }
    return {
        "schema": "ProofLaunchCreativeScenarioLensV1",
        "signature": ":".join(values[name] for name in _SCENARIO_DIMENSIONS),
        "dimensions": dimensions,
    }


def _scenario_lens(request: CampaignStrategyInput) -> dict[str, Any]:
    return _scenario_lens_from_values(
        {
            "business_model": request.audience.business_model.value,
            "lifecycle": request.lifecycle.value,
            "budget": request.budget.value,
            "industry_risk": request.industry_risk.value,
        }
    )


def _legacy_scenario_lens(context: Mapping[str, Any]) -> dict[str, Any]:
    audience = context.get("audience")
    if not isinstance(audience, Mapping):
        raise TextChallengerError("legacy challenger context lacks audience")
    return _scenario_lens_from_values(
        {
            "business_model": str(audience.get("business_model", "b2b")),
            "lifecycle": str(context.get("lifecycle", "launch")),
            "budget": str(context.get("budget", "zero")),
            "industry_risk": str(context.get("industry_risk", "standard")),
        }
    )


def _scenario_territories(lens: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    dimensions = lens["dimensions"]
    return tuple(
        {
            **territory,
            "variant_id": f"{territory['territory_id']}:{lens['signature']}",
            "scenario_signature": lens["signature"],
            "business_model_job": dimensions["business_model"]["job"],
            "lifecycle_job": dimensions["lifecycle"]["job"],
            "budget_execution": dimensions["budget"]["job"],
            "risk_constraint": dimensions["industry_risk"]["job"],
        }
        for territory in _TERRITORIES
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _bounded(value: object, field: str, maximum: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise TextChallengerError(f"{field} must be a nonblank bounded string")
    if "\x00" in value or any(pattern.search(value) for pattern in _UNSAFE):
        raise TextChallengerError(f"{field} contains unsafe or unsupported language")
    return value.strip()


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?", value))


def _normalized_text(value: str) -> str:
    return " ".join(_WORD.findall(value.casefold()))


def _tokens(value: str) -> set[str]:
    return {token for token in _WORD.findall(value.casefold()) if len(token) > 1}


def _jaccard(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    union = left_tokens | right_tokens
    if not union:
        return 1.0
    return len(left_tokens & right_tokens) / len(union)


def _creative_text(value: object, field: str, *, minimum: int, maximum: int) -> str:
    text = _bounded(value, field, maximum)
    if len(text) < minimum:
        raise TextChallengerError(
            f"{field} is too shallow for the creative quality gate"
        )
    if any(pattern.search(text) for pattern in _PLACEHOLDER):
        raise TextChallengerError(f"{field} contains placeholder or schema-copy language")
    return text


def _context_anchor_fields(context: Mapping[str, Any], content: str) -> tuple[str, ...]:
    audience = context["audience"]
    brand = context["brand"]
    anchors = {
        "brand_name": brand["name"],
        "audience_name": audience["name"],
        "core_problem": audience["core_problem"],
        "desired_outcome": audience["desired_outcome"],
        "buying_context": audience["buying_context"],
        "offer": context["offer"],
    }
    normalized_content = _normalized_text(content)
    return tuple(
        name
        for name, value in anchors.items()
        if _normalized_text(str(value)) in normalized_content
    )


def _prompt_messages(
    context: dict[str, Any],
    territory: Mapping[str, str],
    craft_handoff: Mapping[str, Any],
) -> list[dict[str, str]]:
    system = (
        "Execute the supplied typed GTM craft handoff in stage order. The work is not generic "
        "role-play: apply only the selected specialist skills, inputs, outputs and acceptance "
        "criteria assigned to this territory. Produce one sharply distinct, platform-native "
        "text territory. Return exactly one JSON object and no markdown. "
        "Use only the supplied approved factual claim; do not add statistics, customers, "
        "outcomes, rankings, unsupported assurances or invented product capabilities. Preserve the exact "
        "CTA and exact approved proof in both channel drafts. Make the work useful before the "
        "ask, culturally specific to the supplied decision context, concise, and executable. "
        "Never copy a field instruction, schema hint, placeholder, or generic channel prefix "
        "into the answer. Every strategic field must state a concrete tension, mechanism, "
        "proof function, or failure condition grounded in the named audience and buying context."
    )
    output_contract = {
        "schema": CANDIDATE_SCHEMA,
        "territory_id": territory["territory_id"],
        "strategy_id": context["strategy_id"],
        "proof_claim_id": context["proof_claim_id"],
        "cultural_tension": "Explain the audience-specific conflict between the desired outcome and the current problem; do not copy this instruction.",
        "organizing_idea": "Name one ownable creative system that resolves that conflict; do not copy this instruction.",
        "participation_mechanism": "Describe the concrete action the audience takes with the proof object; do not copy this instruction.",
        "share_trigger": "Explain why a recipient would relay the useful object without endorsing the brand; do not copy this instruction.",
        "proof_role": "State how the approved proof changes the sequence or decision, rather than decorating the copy; do not copy this instruction.",
        "falsifier": "State the observable condition under which this territory must be rejected; do not copy this instruction.",
        "factual_claims": [context["approved_proof"]],
        "channels": [
            {
                "channel": channel["channel"],
                "native_format": channel["native_format"],
                "hook": "Write a channel-native opening with a specific unresolved decision; do not copy this instruction.",
                "body": [
                    context["approved_proof"],
                    "Write one or more distinct channel-native blocks that turn the proof into a useful action; do not copy this instruction.",
                ],
                "cta": context["exact_cta"],
                "disclosure": "draft_pending_human_review",
            }
            for channel in context["channels"]
        ],
    }
    user = {
        "task": "Create the challenger candidate under the exact output contract.",
        "territory": dict(territory),
        "context": context,
        "craft_handoff": craft_handoff,
        "output_contract": output_contract,
        "acceptance": [
            "both channels are genuinely native, not verbatim duplicates",
            "the approved proof appears exactly and no new factual claim is introduced",
            "the CTA is exact and the value-before-ask mechanism is visible",
            "the candidate is materially different from the deterministic baseline",
            "all work remains draft pending a content-bound human release",
            "at least two exact context anchors appear across the strategy and drafts",
            "each channel uses a different opening, evidence sequence and participation device",
            "the proof appears exactly once per channel and the CTA never appears inside the body",
            "no placeholder, schema instruction or superficial channel-prefix variation is accepted",
            "the creative system visibly reflects every supplied scenario-lens dimension: business model, lifecycle, budget and industry risk",
            "the opening and body follow the supplied channel grammar rather than merely reformatting one generic draft",
            "the assigned style system is visible in structure and voice without imitating any source creator or campaign",
            "growth-case and trend signals remain hypotheses; never copy source expression or present a research-priority score as causality",
        ],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _canonical(user)},
    ]


def _creative_alpha_prompt_projection(
    creative_alpha_plan: Mapping[str, Any], territory: Mapping[str, Any]
) -> dict[str, Any]:
    """Project only current-craft constraints instead of injecting the full team registry."""

    market_language = creative_alpha_plan.get("market_language_contract", {})
    team = creative_alpha_plan.get("gtm_team_capability_contract", {})
    return {
        "schema": "ProofLaunchCreativeAlphaPromptProjectionV1",
        "creative_alpha_plan_sha256": creative_alpha_plan.get("content_sha256"),
        "context": creative_alpha_plan.get("context"),
        "growth_case_radar_status": creative_alpha_plan.get("growth_case_radar_status"),
        "growth_case_research_candidates": creative_alpha_plan.get(
            "growth_case_research_candidates", []
        )[:3],
        "abstract_signal_patterns": creative_alpha_plan.get("abstract_signal_patterns", [])[:5],
        "audience_decision_unit_contract": creative_alpha_plan.get(
            "audience_decision_unit_contract"
        ),
        "market_language": {
            "contract_sha256": market_language.get("content_sha256"),
            "context": market_language.get("context"),
            "primary_role_contract": market_language.get("primary_role_contract"),
            "language_operating_contract": market_language.get(
                "language_operating_contract"
            ),
        },
        "team": {
            "contract_sha256": team.get("content_sha256"),
            "active_role_ids": [
                row.get("role_id")
                for row in team.get("active_virtual_team", {}).get("roles", [])
                if isinstance(row, Mapping)
            ],
        },
        "platform_grammars": creative_alpha_plan.get("platform_grammars"),
        "distribution_platform_overlay": creative_alpha_plan.get(
            "distribution_platform_overlay"
        ),
        "assigned_style": territory.get("assigned_style"),
        "creative_candidate_contract": creative_alpha_plan.get(
            "creative_candidate_contract"
        ),
        "generative_execution_kernel_contract": creative_alpha_plan.get(
            "generative_execution_kernel_contract"
        ),
        "assigned_genome_blueprint": territory.get("assigned_genome_blueprint"),
    }


def _execution_surface(request: CampaignStrategyInput, strategy: GTMStrategy) -> str:
    declared = request.distribution_platform.strip().casefold().replace(" ", "_")
    for surface in (
        "linkedin", "tiktok", "reddit", "youtube", "instagram", "x", "google_search", "bing_search",
        "chatgpt_answers", "claude_answers", "gemini_answers", "perplexity_answers", "copilot_answers",
    ):
        if surface in declared or surface.split("_")[0] in declared:
            return surface
    return {
        "linkedin_organic": "linkedin",
        "short_video_organic": "tiktok",
        "community_listening": "reddit",
        "creator_community": "tiktok",
        "owned_social": "instagram",
        "search_education": "google_search",
        "paid_search": "google_search",
        "paid_social": "instagram",
        "partner_communities": "reddit",
        "founder_conversations": "linkedin",
        "customer_evidence": "linkedin",
        "customer_email": "linkedin",
    }[strategy.primary_channel.value]


def build_text_challenger_plan(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    source_strategy_sha256: str,
    baseline_copy_sha256: str,
    primary_native_format: str,
    secondary_native_format: str,
    breakout_growth_loop: Mapping[str, Any],
    signal_intelligence: Mapping[str, Any] | None = None,
    genome_learning_memory: Mapping[str, Any] | None = None,
    named_capability_distillation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    for name, value in (
        ("source_strategy_sha256", source_strategy_sha256),
        ("baseline_copy_sha256", baseline_copy_sha256),
    ):
        if not _SHA256.fullmatch(value):
            raise TextChallengerError(f"{name} must be a lowercase SHA-256 digest")
    if breakout_growth_loop.get("strategy_id") != strategy.strategy_id:
        raise TextChallengerError("breakout loop and strategy identities differ")
    try:
        creative_alpha_plan = compile_creative_alpha_plan(
            request,
            strategy,
            signal_intelligence=signal_intelligence,
        )
    except CreativeAlphaError as error:
        raise TextChallengerError(
            f"creative-alpha planning failed: {error}"
        ) from error
    scenario_lens = _scenario_lens(request)
    territory_templates = _scenario_territories(scenario_lens)
    styles = creative_alpha_plan.get("style_portfolio")
    if not isinstance(styles, list) or len(styles) < len(territory_templates):
        raise TextChallengerError(
            "creative-alpha exploration portfolio cannot cover all challenger territories"
        )
    try:
        execution_kernel = compile_generative_execution_kernel(
            {
                "brief_id": request.campaign_id,
                "business_model": request.audience.business_model.value,
                "lifecycle": request.lifecycle.value,
                "industry": request.industry,
                "category": request.product_category,
                "product_surface": request.product_surface.value,
                "platform": _execution_surface(request, strategy),
                "audience": request.audience.name,
                "decision_job": request.audience.desired_outcome,
                "tension": f"{request.audience.core_problem}; {strategy.objection}",
                "approved_proof": strategy.proof,
                "brand_voice": ", ".join(request.brand.voice_principles),
                "budget": request.budget.value,
            },
            candidate_count=24,
            learning_memory=genome_learning_memory,
        )
    except GTMGenerativeExecutionKernelError as error:
        raise TextChallengerError(f"generative execution planning failed: {error}") from error
    multimodal_factory = None
    if named_capability_distillation is not None:
        try:
            multimodal_factory = compile_multimodal_breakout_factory(
                execution_kernel["brief"],
                named_capability_distillation=named_capability_distillation,
                learning_memory=genome_learning_memory,
            )
        except GTMMultimodalBreakoutFactoryError as error:
            raise TextChallengerError(f"multimodal breakout planning failed: {error}") from error
    territories = [
        {
            **territory,
            "assigned_style": dict(styles[index]),
            "assigned_genome_blueprint": dict(execution_kernel["candidate_blueprints"][index]),
        }
        for index, territory in enumerate(territory_templates)
    ]
    channels = [
        {
            "channel": strategy.primary_channel.value,
            "native_format": primary_native_format,
            "required_native_markers": list(
                _CHANNEL_NATIVE_MARKERS[strategy.primary_channel.value]
            ),
        },
        {
            "channel": strategy.secondary_channel.value,
            "native_format": secondary_native_format,
            "required_native_markers": list(
                _CHANNEL_NATIVE_MARKERS[strategy.secondary_channel.value]
            ),
        },
    ]
    base_context = {
        "strategy_id": strategy.strategy_id,
        "campaign_id": request.campaign_id,
        "brand": {
            "name": request.brand.brand_name,
            "purpose": request.brand.purpose,
            "customer_promise": request.brand.customer_promise,
            "voice_principles": list(request.brand.voice_principles),
            "prohibited_tactics": list(request.brand.prohibited_tactics),
        },
        "audience": {
            "name": request.audience.name,
            "business_model": request.audience.business_model.value,
            "core_problem": request.audience.core_problem,
            "desired_outcome": request.audience.desired_outcome,
            "buying_context": request.audience.buying_context,
        },
        "industry": request.industry,
        "lifecycle": request.lifecycle.value,
        "budget": request.budget.value,
        "objective": request.objective,
        "offer": request.offer,
        "approved_proof": strategy.proof,
        "proof_claim_id": strategy.proof_claim_id,
        "proof_evidence_sha256": strategy.proof_evidence_sha256,
        "open_objection": strategy.objection,
        "exact_cta": strategy.call_to_action,
        "channels": channels,
        "breakout_archetype": breakout_growth_loop.get("archetype"),
        "value_before_ask": breakout_growth_loop.get("value_before_ask"),
        "share_trigger_hypothesis": breakout_growth_loop.get("share_trigger_hypothesis"),
        "scenario_lens": scenario_lens,
        "creative_alpha_plan_sha256": creative_alpha_plan["content_sha256"],
    }
    craft_handoff_plans = []
    requests = []
    for territory in territories:
        try:
            craft_handoff = compile_gtm_craft_handoff_plan(
                request,
                strategy,
                territory=territory,
                channels=channels,
                creative_alpha_plan=creative_alpha_plan,
            )
        except GTMCraftHandoffError as error:
            raise TextChallengerError(
                f"craft handoff planning failed: {error}"
            ) from error
        craft_handoff_plans.append(craft_handoff)
        prompt_context = {
            **base_context,
            "creative_alpha": _creative_alpha_prompt_projection(
                creative_alpha_plan, territory
            ),
        }
        messages = _prompt_messages(prompt_context, territory, craft_handoff)
        requests.append({
            "request_id": f"text-challenger-{territory['territory_id']}",
            "territory_id": territory["territory_id"],
            "purpose": "evidence_bound_gtm_text_creative_challenger",
            "scope": "development_core",
            "maximum_output_tokens": 1400,
            "temperature": 0.65,
            "messages": messages,
            "request_sha256": _digest(messages),
        })
    payload: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "strategy_id": strategy.strategy_id,
        "campaign_id": request.campaign_id,
        "source_strategy_sha256": source_strategy_sha256,
        "baseline_copy_sha256": baseline_copy_sha256,
        "proof_claim_id": strategy.proof_claim_id,
        "proof_evidence_sha256": strategy.proof_evidence_sha256,
        "territory_count": len(territories),
        "territories": [dict(item) for item in territories],
        "scenario_lens": scenario_lens,
        "territory_variant_ids": [item["variant_id"] for item in territories],
        "creative_alpha_plan": creative_alpha_plan,
        "generative_execution_kernel": execution_kernel,
        "craft_handoff_plans": craft_handoff_plans,
        "requests": requests,
        "official_first_required": True,
        "third_party_competition_core_eligible": False,
        "maximum_model_calls": 3,
        "maximum_craft_quality_calls": 21,
        "execution_policy": {
            "mode": "sequential_fail_fast",
            "maximum_concurrency": 1,
            "default_official_models": ["Qwen3.6-35B-A3B"],
            "default_retry_rounds": 0,
            "maximum_output_tokens_per_call": 1400,
            "require_all_three_before_blind_review": True,
        },
        "winner_selected": False,
        "blind_review_completed": False,
        "external_publish_executed": False,
        "execution_status": "ready_when_credential_and_gateway_are_available",
        "truth_boundary": (
            "This plan contains a 24-blueprint generative kernel, three model requests and validation rules, not generated creative. "
            "A successful API response remains an unreviewed challenger until mechanical and blind human gates pass."
        ),
    }
    if multimodal_factory is not None:
        payload["multimodal_breakout_factory"] = multimodal_factory
    payload["content_sha256"] = _digest(payload)
    verify_text_challenger_plan(payload)
    return payload


def verify_text_challenger_plan(payload: Mapping[str, Any]) -> None:
    schema = payload.get("schema")
    if schema not in {LEGACY_PLAN_SCHEMA, CREATIVE_ALPHA_PLAN_SCHEMA, PLAN_SCHEMA}:
        raise TextChallengerError("text challenger plan schema is invalid")
    supplied = payload.get("content_sha256")
    if not isinstance(supplied, str) or not _SHA256.fullmatch(supplied):
        raise TextChallengerError("text challenger plan digest is invalid")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise TextChallengerError("text challenger plan digest does not match content")
    territories = payload.get("territories")
    requests = payload.get("requests")
    expected_ids = [item["territory_id"] for item in _TERRITORIES]
    if not isinstance(territories, list) or [row.get("territory_id") for row in territories] != expected_ids:
        raise TextChallengerError("text challenger territories are incomplete or reordered")
    if not isinstance(requests, list) or [row.get("territory_id") for row in requests] != expected_ids:
        raise TextChallengerError("text challenger requests are incomplete or reordered")
    scenario_lens = payload.get("scenario_lens")
    if scenario_lens is not None:
        if not isinstance(scenario_lens, Mapping) or scenario_lens.get("schema") != "ProofLaunchCreativeScenarioLensV1":
            raise TextChallengerError("text challenger scenario lens is invalid")
        dimensions = scenario_lens.get("dimensions")
        if not isinstance(dimensions, Mapping) or set(dimensions) != set(_SCENARIO_DIMENSIONS):
            raise TextChallengerError("text challenger scenario dimensions are incomplete")
        signature = scenario_lens.get("signature")
        if not isinstance(signature, str) or not signature:
            raise TextChallengerError("text challenger scenario signature is invalid")
        expected_variants = [f"{territory_id}:{signature}" for territory_id in expected_ids]
        if payload.get("territory_variant_ids") != expected_variants:
            raise TextChallengerError("text challenger territory variants are inconsistent")
        for territory, expected_variant in zip(territories, expected_variants, strict=True):
            if territory.get("variant_id") != expected_variant or territory.get("scenario_signature") != signature:
                raise TextChallengerError("text challenger territory scenario binding is invalid")
    creative_alpha_plan = payload.get("creative_alpha_plan")
    if schema in {CREATIVE_ALPHA_PLAN_SCHEMA, PLAN_SCHEMA}:
        if not isinstance(creative_alpha_plan, Mapping):
            raise TextChallengerError("text challenger lacks a creative-alpha plan")
        try:
            verify_creative_alpha_plan(creative_alpha_plan)
        except CreativeAlphaError as error:
            raise TextChallengerError(
                f"text challenger creative-alpha plan is invalid: {error}"
            ) from error
        if creative_alpha_plan.get("strategy_id") != payload.get("strategy_id"):
            raise TextChallengerError(
                "creative-alpha and text challenger strategy identities differ"
            )
        kernel = payload.get("generative_execution_kernel")
        if not isinstance(kernel, Mapping):
            raise TextChallengerError("text challenger lacks the generative execution kernel")
        try:
            verify_generative_execution_kernel(kernel)
        except GTMGenerativeExecutionKernelError as error:
            raise TextChallengerError(f"text challenger generative kernel is invalid: {error}") from error
        assigned_genomes = [row.get("assigned_genome_blueprint", {}).get("genome_id") for row in territories]
        expected_genomes = [row.get("genome_id") for row in kernel.get("candidate_blueprints", [])[: len(territories)]]
        if assigned_genomes != expected_genomes or len(set(assigned_genomes)) != len(territories):
            raise TextChallengerError("text challenger territories lost distinct genome bindings")
        multimodal_factory = payload.get("multimodal_breakout_factory")
        if multimodal_factory is not None:
            try:
                verify_multimodal_breakout_factory(multimodal_factory)
            except GTMMultimodalBreakoutFactoryError as error:
                raise TextChallengerError(f"text challenger multimodal factory is invalid: {error}") from error
            factory_genomes = [row.get("genome_id") for row in multimodal_factory.get("candidate_campaigns", [])]
            if factory_genomes != assigned_genomes:
                raise TextChallengerError("multimodal factory lost challenger genome coherence")
        style_portfolio = creative_alpha_plan.get("style_portfolio")
        assigned_styles = [row.get("assigned_style") for row in territories]
        if (
            not isinstance(style_portfolio, list)
            or assigned_styles != style_portfolio[: len(territories)]
            or len(
                {
                    row.get("style_id")
                    for row in assigned_styles
                    if isinstance(row, Mapping)
                }
            )
            != len(territories)
        ):
            raise TextChallengerError(
                "text challenger territories lack distinct creative-alpha style bindings"
            )
    if payload.get("maximum_model_calls") != len(requests):
        raise TextChallengerError("text challenger call budget is inconsistent")
    if schema == PLAN_SCHEMA:
        handoff_plans = payload.get("craft_handoff_plans")
        if (
            not isinstance(handoff_plans, list)
            or len(handoff_plans) != len(territories)
            or [row.get("territory_id") for row in handoff_plans] != expected_ids
            or payload.get("maximum_craft_quality_calls") != len(territories) * 7
        ):
            raise TextChallengerError(
                "text challenger craft-handoff portfolio is incomplete"
            )
        team_contract = creative_alpha_plan.get(
            "gtm_team_capability_contract", {}
        )
        for handoff_plan in handoff_plans:
            try:
                verify_gtm_craft_handoff_plan(
                    handoff_plan, team_contract=team_contract
                )
            except GTMCraftHandoffError as error:
                raise TextChallengerError(
                    f"text challenger craft-handoff plan is invalid: {error}"
                ) from error
    if payload.get("execution_policy") != {
        "mode": "sequential_fail_fast",
        "maximum_concurrency": 1,
        "default_official_models": ["Qwen3.6-35B-A3B"],
        "default_retry_rounds": 0,
        "maximum_output_tokens_per_call": 1400,
        "require_all_three_before_blind_review": True,
    }:
        raise TextChallengerError("text challenger execution policy is invalid")
    for row in requests:
        messages = row.get("messages")
        if not isinstance(messages, list) or len(messages) != 2:
            raise TextChallengerError("text challenger request messages are invalid")
        if row.get("request_sha256") != _digest(messages):
            raise TextChallengerError("text challenger request digest is invalid")
        if schema in {CREATIVE_ALPHA_PLAN_SCHEMA, PLAN_SCHEMA}:
            request_payload = json.loads(messages[1]["content"])
            request_context = request_payload.get("context", {})
            if schema == CREATIVE_ALPHA_PLAN_SCHEMA:
                request_alpha = request_context.get("creative_alpha_plan")
                if not isinstance(request_alpha, Mapping) or request_alpha.get(
                    "content_sha256"
                ) != creative_alpha_plan.get("content_sha256"):
                    raise TextChallengerError(
                        "text challenger request lost creative-alpha binding"
                    )
            else:
                request_alpha = request_context.get("creative_alpha")
                if not isinstance(request_alpha, Mapping) or request_alpha.get(
                    "creative_alpha_plan_sha256"
                ) != creative_alpha_plan.get("content_sha256"):
                    raise TextChallengerError(
                        "text challenger request lost creative-alpha projection binding"
                    )
                handoff = request_payload.get("craft_handoff")
                matching = next(
                    (
                        handoff_row
                        for handoff_row in payload.get("craft_handoff_plans", [])
                        if handoff_row.get("territory_id")
                        == row.get("territory_id")
                    ),
                    None,
                )
                if not isinstance(handoff, Mapping) or not isinstance(matching, Mapping) or handoff.get("content_sha256") != matching.get("content_sha256"):
                    raise TextChallengerError(
                        "text challenger request lost craft-handoff binding"
                    )
        if row.get("scope") != "development_core":
            raise TextChallengerError("text challenger escaped the development scope")
    for field in (
        "winner_selected",
        "blind_review_completed",
        "third_party_competition_core_eligible",
        "external_publish_executed",
    ):
        if payload.get(field) is not False:
            raise TextChallengerError(f"{field} must remain false")
    if payload.get("official_first_required") is not True:
        raise TextChallengerError("official-first routing was disabled")


def validate_text_candidate(
    raw_content: str,
    plan: Mapping[str, Any],
    *,
    territory_id: str,
) -> dict[str, Any]:
    verify_text_challenger_plan(plan)
    try:
        candidate = json.loads(raw_content)
    except (TypeError, json.JSONDecodeError) as error:
        raise TextChallengerError("candidate must be one strict JSON object") from error
    if not isinstance(candidate, dict) or candidate.get("schema") != CANDIDATE_SCHEMA:
        raise TextChallengerError("candidate schema is invalid")
    if set(candidate) != _CANDIDATE_FIELDS:
        raise TextChallengerError("candidate fields do not match the closed contract")
    if candidate.get("territory_id") != territory_id:
        raise TextChallengerError("candidate territory identity does not match")
    if candidate.get("strategy_id") != plan.get("strategy_id"):
        raise TextChallengerError("candidate strategy identity does not match")
    if candidate.get("proof_claim_id") != plan.get("proof_claim_id"):
        raise TextChallengerError("candidate proof identity does not match")
    request = next(
        (row for row in plan["requests"] if row["territory_id"] == territory_id),
        None,
    )
    if request is None:
        raise TextChallengerError("candidate territory is absent from the plan")
    user_context = json.loads(request["messages"][1]["content"])["context"]
    approved_proof = user_context["approved_proof"]
    if candidate.get("factual_claims") != [approved_proof]:
        raise TextChallengerError("candidate introduced or removed a factual claim")
    strategic_values: dict[str, str] = {}
    for field, minimum in _STRATEGY_MINIMUM_CHARACTERS.items():
        strategic_values[field] = _creative_text(
            candidate.get(field),
            field,
            minimum=minimum,
            maximum=800,
        )
    normalized_strategic_values = {
        _normalized_text(value) for value in strategic_values.values()
    }
    if len(normalized_strategic_values) != len(strategic_values):
        raise TextChallengerError("strategic fields must express distinct functions")
    channels = candidate.get("channels")
    expected_channels = user_context["channels"]
    if not isinstance(channels, list) or len(channels) != 2:
        raise TextChallengerError("candidate must contain exactly two channel drafts")
    rendered: list[str] = []
    channel_cores: list[str] = []
    channel_nonproof_blocks: list[set[str]] = []
    proof_occurrences: list[int] = []
    channel_native_markers: list[str | None] = []
    channel_native_required: list[bool] = []
    allowed_numbers = _numbers(approved_proof) | _numbers(user_context["exact_cta"])
    exact_cta = str(user_context["exact_cta"])
    if (
        _CTA_REPEATED_PUNCTUATION.search(exact_cta)
        or exact_cta[-1:] not in ".!?。！？"
        or re.search(r"\bto\s+[A-Z][a-z]", exact_cta)
    ):
        raise TextChallengerError("candidate CTA is grammatically malformed")
    for index, draft in enumerate(channels):
        if not isinstance(draft, dict):
            raise TextChallengerError("candidate channel draft is invalid")
        if set(draft) != _CHANNEL_FIELDS:
            raise TextChallengerError("candidate channel fields do not match the closed contract")
        expected = expected_channels[index]
        if draft.get("channel") != expected["channel"] or draft.get("native_format") != expected["native_format"]:
            raise TextChallengerError("candidate channel binding is invalid")
        hook = _creative_text(
            draft.get("hook"), "hook", minimum=32, maximum=300
        )
        body = draft.get("body")
        if not isinstance(body, list) or not 2 <= len(body) <= 5:
            raise TextChallengerError("candidate body must contain two to five blocks")
        body_text = [
            (
                _bounded(item, "body", 700)
                if item == approved_proof
                else _creative_text(item, "body", minimum=24, maximum=700)
            )
            for item in body
        ]
        if len({_normalized_text(item) for item in body_text}) != len(body_text):
            raise TextChallengerError("candidate repeated a body block")
        if draft.get("cta") != user_context["exact_cta"]:
            raise TextChallengerError("candidate CTA drifted from the strategy")
        if draft.get("disclosure") != "draft_pending_human_review":
            raise TextChallengerError("candidate lost the human-review disclosure")
        combined = "\n".join((hook, *body_text, draft["cta"]))
        required_native_markers = expected.get("required_native_markers")
        channel_native_required.append(isinstance(required_native_markers, list))
        matched_native_marker = None
        if isinstance(required_native_markers, list):
            normalized_channel_content = _normalized_text(
                "\n".join((hook, *body_text))
            )
            matched_native_marker = next(
                (
                    str(marker)
                    for marker in required_native_markers
                    if _normalized_text(str(marker)) in normalized_channel_content
                ),
                None,
            )
        occurrence_count = combined.count(approved_proof)
        if occurrence_count != 1:
            raise TextChallengerError(
                "candidate channel must use the exact approved proof exactly once"
            )
        if any(exact_cta in item for item in body_text):
            raise TextChallengerError("candidate duplicated the CTA inside the body")
        if _numbers(combined) - allowed_numbers:
            raise TextChallengerError("candidate introduced an unapproved numeric claim")
        rendered.append(combined)
        channel_native_markers.append(matched_native_marker)
        proof_occurrences.append(occurrence_count)
        channel_cores.append(
            "\n".join(
                part
                for part in (hook, *body_text)
                if part != approved_proof and part != exact_cta
            )
        )
        channel_nonproof_blocks.append(
            {
                _normalized_text(part)
                for part in body_text
                if part != approved_proof and part != exact_cta
            }
        )
    if rendered[0] == rendered[1]:
        raise TextChallengerError("candidate duplicated copy across channels")
    if _normalized_text(channels[0]["hook"]) == _normalized_text(channels[1]["hook"]):
        raise TextChallengerError("candidate duplicated its opening across channels")
    if channel_nonproof_blocks[0] & channel_nonproof_blocks[1]:
        raise TextChallengerError("candidate reused a body block across channels")
    channel_jaccard = _jaccard(channel_cores[0], channel_cores[1])
    if channel_jaccard > _CHANNEL_CORE_JACCARD_MAXIMUM:
        raise TextChallengerError(
            "candidate channels differ only superficially rather than natively"
        )
    all_creative_content = "\n".join(
        (
            *strategic_values.values(),
            *channel_cores,
        )
    )
    matched_anchor_fields = _context_anchor_fields(user_context, all_creative_content)
    if len(matched_anchor_fields) < 2:
        raise TextChallengerError(
            "candidate is not grounded in at least two supplied context anchors"
        )
    scenario_lens = user_context.get("scenario_lens")
    if not isinstance(scenario_lens, Mapping):
        scenario_lens = _legacy_scenario_lens(user_context)
    dimensions = scenario_lens.get("dimensions")
    if not isinstance(dimensions, Mapping):
        raise TextChallengerError("candidate scenario dimensions are invalid")
    normalized_creative_content = _normalized_text(all_creative_content)
    scenario_fit: dict[str, str] = {}
    for dimension in _SCENARIO_DIMENSIONS:
        profile = dimensions.get(dimension)
        markers = profile.get("markers") if isinstance(profile, Mapping) else None
        if not isinstance(markers, list) or not markers:
            raise TextChallengerError("candidate scenario markers are invalid")
        matched_marker = next(
            (
                str(marker)
                for marker in markers
                if _normalized_text(str(marker)) in normalized_creative_content
            ),
            None,
        )
        if matched_marker is None:
            raise TextChallengerError(
                f"candidate does not visibly fit the {dimension} scenario lens"
            )
        scenario_fit[dimension] = matched_marker
    for draft, native_marker, native_required in zip(
        channels, channel_native_markers, channel_native_required, strict=True
    ):
        if native_required and native_marker is None:
            raise TextChallengerError(
                f"candidate channel {draft['channel']} lacks its native execution marker"
            )
    sealed = dict(candidate)
    sealed["winner_selected"] = False
    sealed["blind_review_completed"] = False
    sealed["external_publish_executed"] = False
    sealed["creative_quality_gate"] = {
        "schema": QUALITY_GATE_SCHEMA,
        "passed": True,
        "placeholder_free": True,
        "strategic_function_count": len(normalized_strategic_values),
        "context_anchor_fields": list(matched_anchor_fields),
        "context_anchor_count": len(matched_anchor_fields),
        "proof_occurrences_per_channel": proof_occurrences,
        "channel_core_jaccard": round(channel_jaccard, 6),
        "channel_core_jaccard_maximum": _CHANNEL_CORE_JACCARD_MAXIMUM,
        "cta_well_formed": True,
        "scenario_signature": scenario_lens["signature"],
        "scenario_fit_markers": scenario_fit,
        "scenario_dimension_count": len(scenario_fit),
        "channel_native_markers": channel_native_markers,
        "channel_native_marker_count": sum(
            marker is not None for marker in channel_native_markers
        ),
    }
    sealed["candidate_content_sha256"] = _digest(sealed)
    return sealed


def build_text_challenger_receipt(
    plan: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    verify_text_challenger_plan(plan)
    expected = [row["territory_id"] for row in plan["requests"]]
    observed = [str(row.get("territory_id")) for row in results]
    if observed != expected:
        raise TextChallengerError("challenger results do not match the planned territory order")
    for result in results:
        supplied = str(result.get("candidate_content_sha256", ""))
        if not _SHA256.fullmatch(supplied):
            raise TextChallengerError("challenger result lacks a validated content digest")
        unsigned = dict(result)
        unsigned.pop("candidate_content_sha256", None)
        if supplied != _digest(unsigned):
            raise TextChallengerError("challenger result content digest does not match")
        if not all(
            result.get(field) is False
            for field in (
                "winner_selected",
                "blind_review_completed",
                "external_publish_executed",
            )
        ):
            raise TextChallengerError("challenger result escaped the review boundary")
        quality_gate = result.get("creative_quality_gate")
        if (
            not isinstance(quality_gate, Mapping)
            or quality_gate.get("schema") != QUALITY_GATE_SCHEMA
            or quality_gate.get("passed") is not True
        ):
            raise TextChallengerError("challenger result lacks the creative quality gate")
    territory_signatures = [
        "\n".join(
            str(result[field])
            for field in (
                "cultural_tension",
                "organizing_idea",
                "participation_mechanism",
                "share_trigger",
                "proof_role",
                "falsifier",
            )
        )
        for result in results
    ]
    if len({_normalized_text(value) for value in territory_signatures}) != len(results):
        raise TextChallengerError("challenger territories duplicated one strategic system")
    territory_pair_jaccards = [
        _jaccard(territory_signatures[left], territory_signatures[right])
        for left in range(len(territory_signatures))
        for right in range(left + 1, len(territory_signatures))
    ]
    if territory_pair_jaccards and max(territory_pair_jaccards) > _TERRITORY_JACCARD_MAXIMUM:
        raise TextChallengerError("challenger territories are not strategically distinct")
    approved_proof = str(results[0]["factual_claims"][0])
    portfolio_channel_signatures = [
        "\n".join(
            (
                str(channel["hook"]),
                *(
                    str(block)
                    for block in channel["body"]
                    if block != approved_proof
                ),
            )
        )
        for result in results
        for channel in result["channels"]
    ]
    if len({_normalized_text(value) for value in portfolio_channel_signatures}) != len(
        portfolio_channel_signatures
    ):
        raise TextChallengerError(
            "challenger territories duplicated one channel creative system"
        )
    portfolio_channel_pair_jaccards = [
        _jaccard(portfolio_channel_signatures[left], portfolio_channel_signatures[right])
        for left in range(len(portfolio_channel_signatures))
        for right in range(left + 1, len(portfolio_channel_signatures))
    ]
    if (
        portfolio_channel_pair_jaccards
        and max(portfolio_channel_pair_jaccards) > _PORTFOLIO_CHANNEL_JACCARD_MAXIMUM
    ):
        raise TextChallengerError(
            "challenger territories reused a channel system too closely"
        )
    receipt: dict[str, Any] = {
        "schema": "ProofLaunchTextCreativeChallengerReceiptV1",
        "plan_sha256": plan["content_sha256"],
        "strategy_id": plan["strategy_id"],
        "candidate_count": len(results),
        "candidate_sha256s": [row["candidate_content_sha256"] for row in results],
        "creative_quality_gate": {
            "schema": "ProofLaunchTextCreativePortfolioQualityGateV1",
            "passed": True,
            "candidate_gate_count": len(results),
            "maximum_territory_jaccard": (
                round(max(territory_pair_jaccards), 6)
                if territory_pair_jaccards
                else 0.0
            ),
            "territory_jaccard_maximum": _TERRITORY_JACCARD_MAXIMUM,
            "maximum_portfolio_channel_jaccard": (
                round(max(portfolio_channel_pair_jaccards), 6)
                if portfolio_channel_pair_jaccards
                else 0.0
            ),
            "portfolio_channel_jaccard_maximum": _PORTFOLIO_CHANNEL_JACCARD_MAXIMUM,
        },
        "winner_selected": False,
        "blind_review_completed": False,
        "external_publish_executed": False,
        "status": "generated_validated_unreviewed",
        "truth_boundary": (
            "All candidate payloads passed mechanical grounding, semantic specificity, "
            "cross-channel distinction and cross-territory creative validation. "
            "No creative winner, 4A preference, publication, lift or revenue effect is established."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    return receipt
