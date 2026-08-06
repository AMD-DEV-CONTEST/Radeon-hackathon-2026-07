from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Mapping

from .gtm_strategy import BudgetTier, CampaignStrategyInput, GTMStrategy, LifecycleStage


SCHEMA = "ProofLaunchGTMCreativeStrategyKernelV1"


class CreativeStrategyKernelError(ValueError):
    """The strategy kernel drifted from its evidence or quality contract."""


def _digest(value: object) -> str:
    def jsonable(item: object) -> object:
        if is_dataclass(item):
            return jsonable(asdict(item))
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, Mapping):
            return {str(key): jsonable(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [jsonable(child) for child in item]
        return item

    return hashlib.sha256(
        json.dumps(
            jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _category_entry(request: CampaignStrategyInput) -> dict[str, object]:
    if request.lifecycle == LifecycleStage.PRE_PMF:
        choice = "enter_existing_problem_demand"
        reason = "Pre-PMF work must prove a painful buying situation before attempting to manufacture a category."
    elif request.lifecycle == LifecycleStage.MATURE and request.brand_reach.value == "strong":
        choice = "test_category_creation_hypothesis"
        reason = "A mature high-reach brand can test a category movement, but only as a falsifiable hypothesis."
    else:
        choice = "reframe_existing_category"
        reason = "The current stage benefits from a sharper evidence-led frame without requiring buyers to learn a new category."
    return {
        "choice": choice,
        "declared_category": request.product_category,
        "reason": reason,
        "human_confirmation_required": True,
        "category_leadership_claim_allowed": False,
    }


def _territories(request: CampaignStrategyInput, strategy: GTMStrategy) -> list[dict[str, object]]:
    tension = strategy.growth_tensions[0]
    proof_id = strategy.proof_claim_id
    return [
        {
            "territory_id": "territory-decision-xray",
            "name": "Decision X-Ray",
            "mechanism": "make the buying decision inspectable before asking for belief",
            "hook_family": "demonstration",
            "opening": f"Inspect the proof behind the {request.product_category} decision before accepting the promise.",
            "proof_role": f"evidence card {proof_id} is the visible center of the idea",
            "visual_grammar": {
                "composition": "one decision question, one evidence card, one unresolved objection",
                "motion": "progressive reveal from claim to source to objection",
                "forbidden": ["invented dashboard", "synthetic testimonial", "unverified outcome counter"],
            },
            "falsifier": "The audience inspects the evidence but does not take the pre-registered qualified next action.",
        },
        {
            "territory_id": "territory-uncertainty-tax",
            "name": "The Uncertainty Tax",
            "mechanism": "show the operational cost of leaving the decision unresolved without inventing monetary impact",
            "hook_family": "loss_and_risk",
            "opening": f"The hidden cost is not choosing wrong; it is leaving {tension.problem.rstrip('?. ')} unresolved.",
            "proof_role": f"evidence card {proof_id} bounds what can be asserted and what remains unknown",
            "visual_grammar": {
                "composition": "split unresolved workflow from evidence-backed next step",
                "motion": "accumulating friction stops when the source is inspected",
                "forbidden": ["fabricated ROI", "fear escalation", "unsupported savings certainty"],
            },
            "falsifier": "The risk frame raises attention but reduces qualified action or trust relative to the control.",
        },
        {
            "territory_id": "territory-proof-challenge",
            "name": "Challenge the Proof",
            "mechanism": "invite the audience to attack the strongest evidence before taking the next step",
            "hook_family": "contrarian_participation",
            "opening": f"Do not trust the {request.brand.brand_name} promise yet—find the strongest flaw in its evidence.",
            "proof_role": f"evidence card {proof_id} becomes a participatory review object",
            "visual_grammar": {
                "composition": "claim, source marker and objection field share equal visual weight",
                "motion": "audience objection appears before the manual CTA",
                "forbidden": ["rage bait", "fake comments", "competitor denigration"],
            },
            "falsifier": "Participation produces low-information argument rather than qualified objections or next actions.",
        },
    ]


def compile_creative_strategy_kernel(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
) -> dict[str, Any]:
    if len(strategy.growth_tensions) != 1:
        raise CreativeStrategyKernelError("creative strategy requires exactly one growth tension")
    claim = next((item for item in request.claims if item.claim_id == strategy.proof_claim_id), None)
    if claim is None:
        raise CreativeStrategyKernelError("creative strategy proof claim is absent")
    if claim.text != strategy.proof or claim.evidence_sha256 != strategy.proof_evidence_sha256:
        raise CreativeStrategyKernelError("creative strategy proof binding drifted")

    territories = _territories(request, strategy)
    if len({row["hook_family"] for row in territories}) != 3:
        raise CreativeStrategyKernelError("creative territories are not materially distinct")
    message_layers = {
        "brand_belief": request.brand.purpose,
        "campaign_hypothesis": strategy.hero_hypothesis,
        "channel_expression_rule": (
            "Translate the campaign hypothesis into the selected platform's native attention and interaction contract."
        ),
        "asset_promise": strategy.call_to_action,
    }
    normalized_layers = [str(value).casefold().strip() for value in message_layers.values()]
    if len(set(normalized_layers)) != len(normalized_layers):
        raise CreativeStrategyKernelError("message layers collapsed into duplicate language")

    zero_budget_mix = [
        {"lever": "product_utility", "asset": "a source-bound decision aid using the product's owned capability"},
        {"lever": "founder_expertise", "asset": f"a specific point of view on {request.audience.core_problem}"},
        {"lever": "customer_evidence", "asset": f"an approval-gated evidence card for {claim.claim_id}"},
        {"lever": "community", "asset": "a standalone diagnostic contribution before any product link"},
        {"lever": "partner", "asset": "a jointly useful decision artifact selected by audience overlap and trust transfer"},
        {"lever": "tool_content", "asset": "a reusable checklist, calculator or evaluator that solves part of the buying job"},
    ]
    paid_gate = {
        "paid_amplification_allowed": request.budget != BudgetTier.ZERO,
        "activation_conditions": [
            "named human released the unchanged asset",
            "observed organic signal exceeded its pre-registered baseline",
            "claim rights and validity remain current",
            "spend cap and stop-loss were approved",
        ],
        "conditions_currently_observed": False,
        "automatic_spend_allowed": False,
    }
    if request.budget == BudgetTier.ZERO:
        paid_gate["paid_amplification_allowed"] = False

    core: dict[str, Any] = {
        "schema": SCHEMA,
        "strategy_id": strategy.strategy_id,
        "campaign_id": request.campaign_id,
        "source_strategy_sha256": _digest(strategy),
        "growth_tension_id": strategy.growth_tensions[0].tension_id,
        "category_entry": _category_entry(request),
        "brand_tension": {
            "belief": request.brand.purpose,
            "opposition": f"decisions about {request.product_category} made from unsupported certainty",
            "desired_change": f"help {request.audience.name} evaluate the next step using inspectable evidence",
            "reason_to_act_now": request.audience.buying_context,
            "source_type": "owner_declared_and_evidence_bound",
        },
        "positioning_contract": {
            "target_customer": request.audience.name,
            "buying_situation": request.audience.buying_context,
            "current_alternative": "the owner-declared current workflow or substitute; confirm before release",
            "key_difference_hypothesis": strategy.hero_hypothesis,
            "credible_reason": strategy.proof,
            "proof_claim_id": strategy.proof_claim_id,
            "proof_evidence_sha256": strategy.proof_evidence_sha256,
            "human_alternative_confirmation_required": True,
        },
        "creative_territories": territories,
        "creative_territory_count": len(territories),
        "message_hierarchy": message_layers,
        "zero_budget_growth_mix": zero_budget_mix,
        "paid_amplification_gate": paid_gate,
        "selected_territory_id": None,
        "named_human_selection_required": True,
        "external_activation_executed": False,
        "truth_boundary": (
            "The three territories are distinct test hypotheses derived from owner-declared context and one cited claim. "
            "They are not award-winning, publishable or effective until named-human review and observed tests say so."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_creative_strategy_kernel(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise CreativeStrategyKernelError("creative strategy kernel seal is invalid")
    territories = payload.get("creative_territories")
    if not isinstance(territories, list) or len(territories) < 3:
        raise CreativeStrategyKernelError("creative strategy requires at least three territories")
    if len({row.get("hook_family") for row in territories if isinstance(row, Mapping)}) != len(territories):
        raise CreativeStrategyKernelError("creative territory hook families are not distinct")
    paid = payload.get("paid_amplification_gate")
    if not isinstance(paid, Mapping) or paid.get("automatic_spend_allowed") is not False:
        raise CreativeStrategyKernelError("creative strategy cannot enable automatic spend")
    if payload.get("external_activation_executed") is not False:
        raise CreativeStrategyKernelError("creative strategy cannot claim external activation")
