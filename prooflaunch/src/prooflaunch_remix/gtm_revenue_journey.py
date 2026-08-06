from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping

from .gtm_strategy import CampaignStrategyInput, GTMStrategy


SCHEMA = "ProofLaunchGTMRevenueJourneyOperationsV1"


class RevenueJourneyError(ValueError):
    """Search, lifecycle, sales, or measurement operations are not evidence-safe."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def compile_revenue_journey_operations(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    compiled_at: str,
) -> dict[str, Any]:
    try:
        parsed = datetime.fromisoformat(compiled_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise RevenueJourneyError("compiled_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise RevenueJourneyError("compiled_at must include a timezone")
    claim = next((item for item in request.claims if item.claim_id == strategy.proof_claim_id), None)
    if claim is None or claim.text != strategy.proof:
        raise RevenueJourneyError("revenue journey lost its evidence-bound claim")

    intent_graph = [
        {"intent": "learn", "question": f"What is {request.product_category}, and what problem does it address?", "conversion_distance": "far"},
        {"intent": "compare", "question": f"How should {request.audience.name} compare {request.product_category} with the current alternative?", "conversion_distance": "medium"},
        {"intent": "decide", "question": f"What evidence should be inspected before choosing {request.product_category}?", "conversion_distance": "near"},
        {"intent": "migrate", "question": f"What must be validated before moving from the current workflow to {request.brand.brand_name}?", "conversion_distance": "near"},
        {"intent": "troubleshoot", "question": f"Why might {request.audience.core_problem} remain unresolved, and what can be checked next?", "conversion_distance": "medium"},
        {"intent": "validate_brand", "question": f"What source supports the {request.brand.brand_name} claim, and what are its limits?", "conversion_distance": "near"},
    ]
    information_gain = {
        "required_types": ["original_evidence", "tool", "data", "framework", "decision_value"],
        "present_types": ["original_evidence", "framework", "decision_value"],
        "proof_claim_id": claim.claim_id,
        "evidence_sha256": claim.evidence_sha256,
        "mechanical_gate_passed": True,
        "human_information_gain_review": None,
        "search_publication_allowed": False,
    }
    geo_nodes = [
        {"answer_type": "entity_definition", "required_elements": ["entity", "category", "audience", "bounded purpose"]},
        {"answer_type": "comparison", "required_elements": ["alternative", "decision axes", "evidence", "trade-off"]},
        {"answer_type": "fit", "required_elements": ["buying situation", "applicable audience", "prerequisite", "next step"]},
        {"answer_type": "limitation", "required_elements": ["unsupported outcome", "evidence boundary", "disqualifier", "review date"]},
        {"answer_type": "evidence", "required_elements": ["claim ID", "source URI", "digest", "validity", "rights"]},
        {"answer_type": "citation_ready", "required_elements": ["direct answer", "source marker", "updated time", "scope"]},
    ]
    citability_components = {
        "explicit_entity": bool(request.brand.brand_name),
        "direct_conclusion": bool(strategy.proof),
        "located_evidence": bool(claim.evidence_uri and claim.evidence_sha256),
        "updated_time": bool(compiled_at),
    }
    citability = {
        "components": citability_components,
        "mechanical_score": sum(citability_components.values()) / len(citability_components),
        "claim_release_eligibility_must_be_checked_separately": True,
        "human_citation_editor_pass": None,
        "answer_published": False,
    }

    email_states = [
        ("trigger", "the audience enters the declared buying situation", "state the relevant decision tension without fabricated urgency"),
        ("educate", "the audience requests context", "teach one decision framework"),
        ("prove", "the audience engages with the framework", f"show claim {claim.claim_id} with its source boundary"),
        ("object", "the audience raises or exhibits a material objection", "answer the objection or acknowledge what remains unknown"),
        ("convert", "the audience meets the qualified-action criteria", "offer one proportionate next step"),
        ("activate", "the qualified action is completed", "help the person achieve first value"),
        ("retain", "continued value or risk signal is observed", "reinforce useful behavior and surface friction"),
        ("win_back", "the declared inactivity threshold is reached", "offer new value or a respectful exit"),
    ]
    lifecycle = [
        {
            "state": state,
            "entry_condition": condition,
            "message_job": job,
            "exit_event_required": True,
            "human_send_approval_required": True,
            "automatic_send_enabled": False,
        }
        for state, condition, job in email_states
    ]
    sales_enablement = {
        "discovery_questions": [
            f"What changed that made {request.audience.core_problem} important now?",
            "How is the current alternative evaluated, and who can veto a change?",
            "What evidence would make a next step rational, and what would disqualify it?",
        ],
        "objection_response": {
            "open_objection": strategy.objection,
            "response_rule": "answer only with the cited claim, state its limitation, and record any unanswered question",
        },
        "case_narrative": {
            "status": "evidence_example_not_customer_case",
            "structure": "buying context → decision tension → source-bound claim → limitation → next-step question",
            "customer_outcome_claim_allowed": False,
        },
        "follow_up_email": {
            "subject": "Evidence and the unresolved decision question",
            "blocks": [strategy.proof, strategy.objection, strategy.call_to_action],
            "automatic_send_enabled": False,
        },
    }
    event_dimensions = [
        "content_id",
        "creative_version",
        "platform",
        "audience_id",
        "cta_id",
        "landing_page_id",
        "experiment_id",
        "claim_id",
        "occurred_at",
        "consent_and_data_class",
    ]
    events = [
        {"event": "qualified_content_action", "required_dimensions": event_dimensions, "outcome_level": "engagement"},
        {"event": "qualified_lead", "required_dimensions": event_dimensions + ["lead_definition_version"], "outcome_level": "demand"},
        {"event": "registration", "required_dimensions": event_dimensions + ["account_or_user_pseudonymous_id"], "outcome_level": "conversion"},
        {"event": "activation", "required_dimensions": event_dimensions + ["activation_definition_version"], "outcome_level": "product_value"},
        {"event": "revenue", "required_dimensions": event_dimensions + ["currency", "gross_amount", "refund_state"], "outcome_level": "business"},
        {"event": "retention", "required_dimensions": event_dimensions + ["retention_window"], "outcome_level": "durability"},
    ]
    incrementality = {
        "descriptive_only": ["raw count", "rate", "cohort movement", "correlation"],
        "causal_language_allowed_only_for": [
            "randomized controlled experiment with pre-registered assignment and analysis",
            "qualified quasi-experiment with explicit assumptions, diagnostics and sensitivity analysis",
        ],
        "prohibited_shortcuts": ["before-after alone", "last-touch attribution", "model score alone", "testimonial", "post hoc segment selection"],
        "current_causal_claim_allowed": False,
        "named_human_or_qualified_analyst_review_required": True,
    }
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "strategy_id": strategy.strategy_id,
        "campaign_id": request.campaign_id,
        "compiled_at": compiled_at,
        "search_intent_graph": intent_graph,
        "information_gain_gate": information_gain,
        "geo_answer_graph": geo_nodes,
        "citability_score": citability,
        "lifecycle_email_state_machine": lifecycle,
        "sales_enablement_pack": sales_enablement,
        "event_tracking_contract": {
            "content_to_revenue_trace_required": True,
            "events": events,
            "identity_mode": "pseudonymous_or_aggregated_under_declared_consent",
            "schema_versioning_required": True,
        },
        "incrementality_rules": incrementality,
        "external_send_executed": False,
        "external_publish_executed": False,
        "production_effect_observed": False,
        "truth_boundary": (
            "This document supplies search, lifecycle, sales and measurement contracts. It does not prove indexing, "
            "AI citation, email delivery, sales use, attribution, incrementality, revenue or retention."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_revenue_journey_operations(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise RevenueJourneyError("revenue journey seal is invalid")
    intents = payload.get("search_intent_graph")
    if not isinstance(intents, list) or {row.get("intent") for row in intents if isinstance(row, Mapping)} != {"learn", "compare", "decide", "migrate", "troubleshoot", "validate_brand"}:
        raise RevenueJourneyError("search intent graph is incomplete")
    lifecycle = payload.get("lifecycle_email_state_machine")
    if not isinstance(lifecycle, list) or len(lifecycle) != 8 or any(row.get("automatic_send_enabled") is not False for row in lifecycle if isinstance(row, Mapping)):
        raise RevenueJourneyError("lifecycle state machine is unsafe")
    tracking = payload.get("event_tracking_contract")
    if not isinstance(tracking, Mapping) or tracking.get("content_to_revenue_trace_required") is not True:
        raise RevenueJourneyError("content-to-revenue tracking contract is incomplete")
    incrementality = payload.get("incrementality_rules")
    if not isinstance(incrementality, Mapping) or incrementality.get("current_causal_claim_allowed") is not False:
        raise RevenueJourneyError("incrementality rule overclaims causality")
    if payload.get("production_effect_observed") is not False:
        raise RevenueJourneyError("contract compilation cannot prove production effect")
