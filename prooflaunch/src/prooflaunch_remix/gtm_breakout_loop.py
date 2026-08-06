from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .gtm_strategy import (
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    Channel,
    GTMStrategy,
    IndustryRisk,
    LifecycleStage,
)


class BreakoutLoopError(ValueError):
    """Raised when a proposed earned-growth loop is unsafe or incoherent."""


class BreakoutArchetype(str, Enum):
    FOUNDER_LEARNING_RELAY = "founder_learning_relay"
    PEER_PROOF_TRANSFER = "peer_proof_transfer"
    SEARCH_EVIDENCE_COMPOUND = "search_evidence_compound"
    CUSTOMER_DECISION_RELAY = "customer_decision_relay"
    COMMUNITY_LANGUAGE_LOOP = "community_language_loop"
    UTILITY_DEMO_REMIX = "utility_demo_remix"
    SEARCH_VIDEO_COMPOUND = "search_video_compound"
    CUSTOMER_RITUAL_LOOP = "customer_ritual_loop"


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STEP_IDS = ("sense", "make", "seed", "convert", "learn")
_UNSUPPORTED = (
    "guaranteed",
    "guarantee",
    "will go viral",
    "will drive revenue",
    "viral coefficient above",
    "guaranteed roi",
    "保证爆款",
    "必然爆款",
    "保证营收",
    "必然营收",
)


_ARCHETYPES: dict[
    tuple[BusinessModel, LifecycleStage],
    tuple[BreakoutArchetype, str, str, tuple[str, str, str]],
] = {
    (BusinessModel.B2B, LifecycleStage.PRE_PMF): (
        BreakoutArchetype.FOUNDER_LEARNING_RELAY,
        "turn one founder conversation into a source-bound problem pattern that another qualified operator can challenge",
        "a concise decision memo that gives the recipient a safer way to frame the problem before any product ask",
        (
            "operators who explicitly recognize the problem",
            "specialists who can falsify the proposed framing",
            "peer operators facing the same decision window",
        ),
    ),
    (BusinessModel.B2B, LifecycleStage.LAUNCH): (
        BreakoutArchetype.PEER_PROOF_TRANSFER,
        "make approved proof useful enough for a practitioner to carry into a buying-group discussion",
        "an evidence card plus an objection prompt that helps a committee inspect the decision",
        (
            "owner-approved design partners",
            "relevant practitioner communities",
            "partners already trusted by the buying group",
        ),
    ),
    (BusinessModel.B2B, LifecycleStage.GROWTH): (
        BreakoutArchetype.SEARCH_EVIDENCE_COMPOUND,
        "answer a repeated high-intent question, then let verified customer evidence deepen the answer over time",
        "a citable explainer that a stakeholder can reuse in internal evaluation",
        (
            "high-intent search visitors",
            "existing customers with approved evidence",
            "partners serving the same decision journey",
        ),
    ),
    (BusinessModel.B2B, LifecycleStage.MATURE): (
        BreakoutArchetype.CUSTOMER_DECISION_RELAY,
        "help customers transfer a defensible decision pattern to peers without turning them into unsolicited endorsers",
        "a reusable decision packet with evidence, limitations and a clear not-for-everyone boundary",
        (
            "customers who opted into evidence review",
            "peer operators in adjacent teams",
            "customer-success and education owners",
        ),
    ),
    (BusinessModel.B2C, LifecycleStage.PRE_PMF): (
        BreakoutArchetype.COMMUNITY_LANGUAGE_LOOP,
        "reflect the audience's problem language back as a useful diagnostic and invite correction before promotion",
        "a low-friction self-check that creates value even when the audience never converts",
        (
            "owned community participants",
            "people actively describing the problem",
            "subject-matter reviewers who can flag harmful framing",
        ),
    ),
    (BusinessModel.B2C, LifecycleStage.LAUNCH): (
        BreakoutArchetype.UTILITY_DEMO_REMIX,
        "show one immediately useful transformation that people can recreate, adapt and discuss in their own context",
        "a short proof-led demonstration with a remixable prompt rather than a polished promise reel",
        (
            "owned waitlist members",
            "small creators with direct audience relevance",
            "communities where the demonstrated task already occurs",
        ),
    ),
    (BusinessModel.B2C, LifecycleStage.GROWTH): (
        BreakoutArchetype.SEARCH_VIDEO_COMPOUND,
        "pair durable search answers with short demonstrations so each format supplies context the other lacks",
        "an answer-plus-demonstration pair that remains useful outside the campaign window",
        (
            "high-intent search visitors",
            "returning owned-audience members",
            "creators who can add a genuinely different use context",
        ),
    ),
    (BusinessModel.B2C, LifecycleStage.MATURE): (
        BreakoutArchetype.CUSTOMER_RITUAL_LOOP,
        "turn repeated customer use into a voluntary evidence ritual that teaches the next cohort",
        "a customer-controlled before/during/after reflection format with explicit consent and no fabricated outcome",
        (
            "customers who explicitly opt into sharing",
            "owned audience cohorts with the same use moment",
            "community moderators responsible for safety and context",
        ),
    ),
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _bounded(value: object, field: str, maximum: int = 1_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise BreakoutLoopError(f"{field} must be a nonblank bounded string")
    if "\x00" in value:
        raise BreakoutLoopError(f"{field} contains a NUL byte")
    lowered = value.casefold()
    if any(term in lowered for term in _UNSUPPORTED):
        raise BreakoutLoopError(f"{field} contains an unsupported outcome claim")
    return value.strip()


@dataclass(frozen=True)
class BreakoutLoopStep:
    step_id: str
    owner: str
    channel: Channel
    precondition: str
    operator_action: str
    audience_value: str
    output_object: str
    success_signal: str
    stop_condition: str
    human_release_required: bool = True
    external_action_performed: bool = False

    def __post_init__(self) -> None:
        if self.step_id not in _STEP_IDS:
            raise BreakoutLoopError("breakout step_id is unsupported")
        if not isinstance(self.channel, Channel):
            raise BreakoutLoopError("breakout step channel is invalid")
        for field in (
            "owner",
            "precondition",
            "operator_action",
            "audience_value",
            "output_object",
            "success_signal",
            "stop_condition",
        ):
            _bounded(getattr(self, field), field)
        if not self.human_release_required or self.external_action_performed:
            raise BreakoutLoopError("breakout steps must remain human-released plans")


def _step_payload(step: BreakoutLoopStep) -> dict[str, Any]:
    payload = asdict(step)
    payload["channel"] = step.channel.value
    return payload


def _core_channel(strategy: GTMStrategy) -> Channel:
    if not strategy.primary_channel.paid:
        return strategy.primary_channel
    if strategy.secondary_channel.paid:
        raise BreakoutLoopError("breakout loop requires at least one organic channel")
    return strategy.secondary_channel


def _steps(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    value_object: str,
    seed_cohorts: tuple[str, str, str],
) -> tuple[BreakoutLoopStep, ...]:
    channel = _core_channel(strategy)
    proof_ref = f"approved claim {strategy.proof_claim_id}"
    owner = request.owner
    return (
        BreakoutLoopStep(
            step_id="sense",
            owner=owner,
            channel=channel,
            precondition="rights-cleared audience and channel observations are available",
            operator_action=(
                f"collect recurring language around '{request.audience.core_problem}' and "
                "record contradictions without copying source creative"
            ),
            audience_value="the audience's real decision friction becomes visible before a campaign answer is imposed",
            output_object="source-linked tension brief",
            success_signal="distinct qualified problem statements and falsifying objections captured",
            stop_condition="stop if collection requires bypassing access controls, consent or platform policy",
        ),
        BreakoutLoopStep(
            step_id="make",
            owner=owner,
            channel=channel,
            precondition=f"{proof_ref} is valid and the tension brief passed human review",
            operator_action=(
                f"turn {proof_ref} into {value_object}; preserve evidence, limitations, "
                "brand voice and a clear not-for-everyone boundary"
            ),
            audience_value="the artifact helps the recipient make a better decision before asking for conversion",
            output_object="proof-bound share object",
            success_signal="blind reviewers can identify the decision value, proof and limitation without seeing the brand name",
            stop_condition="stop after two failed repair cycles or any claim, rights, accessibility or policy defect",
        ),
        BreakoutLoopStep(
            step_id="seed",
            owner=owner,
            channel=channel,
            precondition="the unchanged share object is approved and its experiment arm is preregistered",
            operator_action=(
                "manually offer the artifact to the three consented seed roles in order: "
                + "; ".join(seed_cohorts)
            ),
            audience_value="each recipient may use, challenge or ignore the artifact without being enrolled into outreach",
            output_object="consented seed log with aggregate exposure counts",
            success_signal="qualified recipients voluntarily inspect, respond to or pass along the useful object",
            stop_condition="stop on complaint, negative safety signal, unauthorized outreach or audience mismatch",
        ),
        BreakoutLoopStep(
            step_id="convert",
            owner=owner,
            channel=channel,
            precondition="a recipient has consumed the useful object and reaches the explicit next-step boundary",
            operator_action=(
                f"offer one reversible next step: {request.objective}; disclose what happens next and retain a no-action path"
            ),
            audience_value="the recipient can choose a next step with the proof and trade-offs still visible",
            output_object="deduplicated qualified-action observation",
            success_signal="qualified_action_rate measured against the frozen comparison without causal inflation",
            stop_condition="stop if the CTA, landing experience or follow-up differs from the approved promise",
        ),
        BreakoutLoopStep(
            step_id="learn",
            owner=owner,
            channel=channel,
            precondition=f"experiment {strategy.attribution.experiment_id} reaches its preregistered window or a guardrail fires",
            operator_action="compare candidate and baseline aggregates, record uncertainty and request a separate human promote, repair or stop decision",
            audience_value="future iterations preserve what was learned without silently changing the current approved campaign",
            output_object="content-bound effect observation and proposed next-cycle directive",
            success_signal="a reproducible decision names the winning evidence, audience, format and uncertainty boundary",
            stop_condition="never promote learning from insufficient samples, raw attribution, judge-only preference or unreviewed PII",
        ),
    )


def compile_breakout_growth_loop(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    source_strategy_sha256: str,
) -> dict[str, Any]:
    if not _SHA256.fullmatch(source_strategy_sha256):
        raise BreakoutLoopError("source_strategy_sha256 must be a lowercase digest")
    archetype, mechanism, value_object, seed_cohorts = _ARCHETYPES[
        (request.audience.business_model, request.lifecycle)
    ]
    core_channel = _core_channel(strategy)
    if request.budget is BudgetTier.ZERO and (
        strategy.primary_channel.paid or strategy.secondary_channel.paid
    ):
        raise BreakoutLoopError("zero-budget breakout loop cannot contain paid channels")
    paid_amplifier = (
        strategy.primary_channel.value if strategy.primary_channel.paid else None
    )
    steps = _steps(
        request,
        strategy,
        value_object=value_object,
        seed_cohorts=seed_cohorts,
    )
    payload: dict[str, Any] = {
        "schema": "ProofLaunchBreakoutGrowthLoopV1",
        "strategy_id": strategy.strategy_id,
        "campaign_id": request.campaign_id,
        "source_strategy_sha256": source_strategy_sha256,
        "business_model": request.audience.business_model.value,
        "lifecycle": request.lifecycle.value,
        "budget": request.budget.value,
        "industry_risk": request.industry_risk.value,
        "archetype": archetype.value,
        "operating_thesis": f"Earn distribution by {mechanism}.",
        "core_organic_channel": core_channel.value,
        "paid_amplifier_channel": paid_amplifier,
        "core_loop_functions_without_paid_media": True,
        "audience_problem": request.audience.core_problem,
        "audience_desired_outcome": request.audience.desired_outcome,
        "value_before_ask": value_object,
        "share_trigger_hypothesis": (
            "A recipient may share the object when it improves a real decision, helps "
            "another person avoid uncertainty and keeps the evidence limitations visible."
        ),
        "seed_cohorts": list(seed_cohorts),
        "steps": [_step_payload(step) for step in steps],
        "primary_experiment": {
            "experiment_id": strategy.attribution.experiment_id,
            "single_changed_variable": "proof_first_versus_promise_first_message_order",
            "candidate": "useful decision object presents approved proof and limits before the CTA",
            "baseline": "same offer, channel, audience and CTA with the promise before proof",
            "primary_metric": "qualified_action_rate",
            "guardrails": [
                "unsubscribe_or_complaint_rate",
                "rights_privacy_or_policy_breach_count",
                "claim_or_brand_drift_count",
            ],
            "causal_claim_allowed": False,
            "activation_status": "awaiting_human_release",
        },
        "growth_accounting": {
            "projection_supplied": False,
            "required_observations": [
                "unique_seed_exposures",
                "qualified_engagements",
                "voluntary_pass_alongs",
                "deduplicated_qualified_actions",
                "complaints_or_safety_stops",
            ],
            "derived_metrics_after_observation": [
                "qualified_engagement_rate",
                "voluntary_pass_along_rate",
                "qualified_action_rate",
                "observed_loop_amplification_ratio",
            ],
            "interpretation": (
                "Descriptive loop accounting only; amplification, attribution and "
                "revenue are not causal effects without an eligible experiment."
            ),
        },
        "operator_capacity": {
            "numeric_capacity_invented": False,
            "required_before_release": [
                "named owner",
                "manual review capacity",
                "response and escalation SLA",
                "maximum consented seed count",
            ],
        },
        "specialist_gate_required": request.industry_risk is IndustryRisk.HIGH_REGULATION,
        "automatic_publish_enabled": False,
        "automatic_outreach_enabled": False,
        "automatic_budget_activation_enabled": False,
        "automatic_learning_promotion_enabled": False,
        "external_action_performed": False,
        "status": "planned_human_release_required",
        "truth_boundary": (
            "This artifact specifies an earned-growth hypothesis and measurable operating "
            "loop. It does not prove virality, distribution, conversion, revenue or causal lift."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_breakout_growth_loop(payload)
    return payload


def verify_breakout_growth_loop(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != "ProofLaunchBreakoutGrowthLoopV1":
        raise BreakoutLoopError("breakout loop schema is invalid")
    supplied = payload.get("content_sha256")
    if not isinstance(supplied, str) or not _SHA256.fullmatch(supplied):
        raise BreakoutLoopError("breakout loop digest is invalid")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise BreakoutLoopError("breakout loop digest does not match content")
    steps = payload.get("steps")
    if not isinstance(steps, list) or [step.get("step_id") for step in steps] != list(_STEP_IDS):
        raise BreakoutLoopError("breakout loop must contain the five ordered functions")
    if any(
        step.get("human_release_required") is not True
        or step.get("external_action_performed") is not False
        for step in steps
    ):
        raise BreakoutLoopError("breakout loop step escaped the human release boundary")
    if payload.get("budget") == BudgetTier.ZERO.value and (
        Channel(payload["core_organic_channel"]).paid
        or payload.get("paid_amplifier_channel") is not None
    ):
        raise BreakoutLoopError("zero-budget breakout loop contains paid activation")
    if payload.get("core_loop_functions_without_paid_media") is not True:
        raise BreakoutLoopError("breakout loop depends on paid media")
    for field in (
        "automatic_publish_enabled",
        "automatic_outreach_enabled",
        "automatic_budget_activation_enabled",
        "automatic_learning_promotion_enabled",
        "external_action_performed",
    ):
        if payload.get(field) is not False:
            raise BreakoutLoopError(f"{field} must remain false")
    experiment = payload.get("primary_experiment")
    if not isinstance(experiment, dict):
        raise BreakoutLoopError("breakout loop experiment is missing")
    if experiment.get("causal_claim_allowed") is not False:
        raise BreakoutLoopError("breakout loop pre-claimed a causal effect")
    if experiment.get("single_changed_variable") != "proof_first_versus_promise_first_message_order":
        raise BreakoutLoopError("breakout loop experiment is not single-variable")
    if payload.get("specialist_gate_required") != (
        payload.get("industry_risk") == IndustryRisk.HIGH_REGULATION.value
    ):
        raise BreakoutLoopError("breakout loop specialist gate is inconsistent")
    _bounded(str(payload.get("operating_thesis", "")), "operating_thesis")
    _bounded(str(payload.get("truth_boundary", "")), "truth_boundary")
