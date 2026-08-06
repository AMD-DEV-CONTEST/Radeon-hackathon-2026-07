from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .gtm_market_neighborhood import compile_market_neighborhood


SCHEMA = "ProofLaunchGTMBriefIntelligenceV1"
PRODUCT_EVIDENCE_SCHEMA = "ProofLaunchProductEvidenceRegisterV1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_TYPES = frozenset(
    {"feature", "performance", "customer_result", "operational_capability"}
)
_RIGHTS_STATUSES = frozenset(
    {
        "owner_attested",
        "owner_approved",
        "licensed",
        "public_measurement",
        "restricted",
    }
)
_PUBLIC_RELEASE_RIGHTS = frozenset(
    {"owner_approved", "licensed", "public_measurement"}
)
_PLACEHOLDERS = frozenset(
    {
        "unspecified",
        "owner_category_unspecified",
        "owner_role_unspecified",
        "owner context not supplied",
        "intended audience",
    }
)


class BriefIntelligenceError(ValueError):
    """A brief cannot be made operational without inventing evidence."""


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


def _parse_time(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise BriefIntelligenceError(f"{field} must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise BriefIntelligenceError(f"{field} must include a timezone")
    return parsed


def _required(value: object, *, field: str, maximum: int = 4_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise BriefIntelligenceError(f"{field} must be a non-empty bounded string")
    return value.strip()


@dataclass(frozen=True)
class ProductEvidenceInput:
    claim_id: str
    claim_type: str
    claim_text: str
    source_uri: str
    source_sha256: str
    rights_status: str
    rights_reference: str
    release_scope: str
    valid_from: str
    valid_until: str | None = None
    approved_by: str | None = None
    specialist_approved_by: str | None = None

    def __post_init__(self) -> None:
        for field, value, maximum in (
            ("claim_id", self.claim_id, 128),
            ("claim_text", self.claim_text, 4_000),
            ("source_uri", self.source_uri, 2_000),
            ("rights_reference", self.rights_reference, 2_000),
            ("release_scope", self.release_scope, 500),
        ):
            _required(value, field=field, maximum=maximum)
        if self.claim_type not in _CLAIM_TYPES:
            raise BriefIntelligenceError("claim_type is unsupported")
        if self.rights_status not in _RIGHTS_STATUSES:
            raise BriefIntelligenceError("rights_status is unsupported")
        if not _SHA256.fullmatch(self.source_sha256):
            raise BriefIntelligenceError("source_sha256 must be lowercase SHA-256")
        parsed = urlparse(self.source_uri)
        if not parsed.scheme:
            raise BriefIntelligenceError("source_uri must be absolute")
        starts = _parse_time(self.valid_from, field="valid_from")
        if self.valid_until is not None:
            ends = _parse_time(self.valid_until, field="valid_until")
            if ends <= starts:
                raise BriefIntelligenceError("valid_until must follow valid_from")
        for field, value in (
            ("approved_by", self.approved_by),
            ("specialist_approved_by", self.specialist_approved_by),
        ):
            if value is not None:
                _required(value, field=field, maximum=200)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ProductEvidenceInput":
        if not isinstance(value, Mapping):
            raise BriefIntelligenceError("each product claim must be an object")
        try:
            return cls(
                claim_id=_required(value["claim_id"], field="claim_id", maximum=128),
                claim_type=_required(value["claim_type"], field="claim_type", maximum=64),
                claim_text=_required(value["claim_text"], field="claim_text"),
                source_uri=_required(value["source_uri"], field="source_uri", maximum=2_000),
                source_sha256=_required(value["source_sha256"], field="source_sha256", maximum=64),
                rights_status=_required(value["rights_status"], field="rights_status", maximum=64),
                rights_reference=_required(value["rights_reference"], field="rights_reference", maximum=2_000),
                release_scope=_required(value["release_scope"], field="release_scope", maximum=500),
                valid_from=_required(value["valid_from"], field="valid_from", maximum=64),
                valid_until=(
                    str(value["valid_until"])
                    if value.get("valid_until") is not None
                    else None
                ),
                approved_by=(
                    str(value["approved_by"])
                    if value.get("approved_by") is not None
                    else None
                ),
                specialist_approved_by=(
                    str(value["specialist_approved_by"])
                    if value.get("specialist_approved_by") is not None
                    else None
                ),
            )
        except KeyError as error:
            raise BriefIntelligenceError(
                f"product claim is missing {error.args[0]}"
            ) from error


def compile_product_evidence_register(
    claims: Sequence[ProductEvidenceInput],
    *,
    evaluated_at: str,
    high_regulation: bool,
) -> dict[str, Any]:
    """Compile per-claim draft and release decisions without upgrading attestations."""

    now = _parse_time(evaluated_at, field="evaluated_at")
    if not claims:
        raise BriefIntelligenceError("at least one product claim is required")
    ids = [claim.claim_id for claim in claims]
    if len(ids) != len(set(ids)):
        raise BriefIntelligenceError("product claim IDs must be unique")

    rows: list[dict[str, Any]] = []
    for claim in claims:
        starts = _parse_time(claim.valid_from, field="valid_from")
        ends = (
            _parse_time(claim.valid_until, field="valid_until")
            if claim.valid_until is not None
            else None
        )
        blockers: list[str] = []
        if now < starts:
            blockers.append("evidence_not_yet_valid")
        if ends is not None and now >= ends:
            blockers.append("evidence_expired")
        if claim.rights_status == "restricted":
            blockers.append("rights_restricted")
        if claim.rights_status not in _PUBLIC_RELEASE_RIGHTS:
            blockers.append("release_rights_not_established")
        if not claim.approved_by:
            blockers.append("named_claim_approver_missing")
        if claim.release_scope.casefold() in {"draft_only", "internal_draft"}:
            blockers.append("release_scope_is_draft_only")
        if high_regulation and not claim.specialist_approved_by:
            blockers.append("named_specialist_approver_missing")
        draft_blockers = [
            item
            for item in blockers
            if item
            in {"evidence_not_yet_valid", "evidence_expired", "rights_restricted"}
        ]
        rows.append(
            {
                **asdict(claim),
                "draft_generation_eligible": not draft_blockers,
                "public_release_eligible": not blockers,
                "release_blockers": blockers,
                "source_storage_required": False,
                "source_content_copied_into_training": False,
            }
        )

    core: dict[str, Any] = {
        "schema": PRODUCT_EVIDENCE_SCHEMA,
        "evaluated_at": evaluated_at,
        "claim_count": len(rows),
        "claim_type_counts": {
            kind: sum(row["claim_type"] == kind for row in rows)
            for kind in sorted(_CLAIM_TYPES)
        },
        "draft_generation_eligible_count": sum(
            row["draft_generation_eligible"] for row in rows
        ),
        "public_release_eligible_count": sum(
            row["public_release_eligible"] for row in rows
        ),
        "all_claims_draft_generation_eligible": all(
            row["draft_generation_eligible"] for row in rows
        ),
        "all_claims_public_release_eligible": all(
            row["public_release_eligible"] for row in rows
        ),
        "claims": rows,
        "external_release_executed": False,
        "training_admitted": False,
        "truth_boundary": (
            "Owner attestation can support a reviewable draft but cannot become public-release "
            "approval. Every outward claim retains its own source, validity, rights, scope and "
            "named-approver decision."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


_MATURITY_PRIORITY = {
    "pre_pmf": "resolve whether one painful problem and one reachable audience justify continued discovery",
    "launch": "turn one evidence-backed promise into qualified first-action demand",
    "growth": "scale the strongest retained acquisition-to-activation loop without message dilution",
    "mature": "defend preference and expand durable value without eroding trust or margin",
}

_BRAND_DIAGNOSIS = {
    "none": ("no_recognition", "borrow trust from product proof, practitioners and communities"),
    "emerging": ("niche_recognition", "convert specific proof into repeatable category association"),
    "established": ("category_recognition", "differentiate a defensible point of view and customer evidence"),
    "strong": ("leader_recognition", "use reach to create category movement while protecting identity"),
}

_BUDGET_DIAGNOSIS = {
    "zero": ("owned_earned_only", "product utility, founder expertise, customer proof, community and partners"),
    "small": ("validated_signal_amplification", "fund only the best manually approved organic signal"),
    "scaled": ("incremental_portfolio", "scale only pre-registered creative/channel cells with guardrails"),
}


def _critical_questions(context: Mapping[str, object], register: Mapping[str, Any]) -> list[dict[str, str]]:
    candidates: list[tuple[bool, str, str]] = [
        (
            str(context.get("industry", "")).casefold() in _PLACEHOLDERS,
            "industry",
            "Which precise industry and buying situation would change the channel or proof strategy?",
        ),
        (
            str(context.get("product_category", "")).casefold() in _PLACEHOLDERS,
            "product_category",
            "What exact product category and substitute does the buyer compare against?",
        ),
        (
            str(context.get("audience_role", "")).casefold() in _PLACEHOLDERS,
            "audience_role",
            "Who owns the decision, who uses the product, and who can veto it?",
        ),
        (
            not bool(register.get("all_claims_public_release_eligible")),
            "claim_release",
            "Which named person can approve each claim and its exact public release scope?",
        ),
        (
            str(context.get("buying_context", "")).casefold() in _PLACEHOLDERS,
            "buying_context",
            "What event makes the audience act now rather than defer or use the current alternative?",
        ),
    ]
    return [
        {"question_id": f"critical-{index:02d}", "field": field, "question": question}
        for index, (_, field, question) in enumerate(
            (item for item in candidates if item[0]), start=1
        )
    ][:5]


def compile_brief_intelligence(
    context: Mapping[str, object],
    *,
    product_evidence_register: Mapping[str, Any],
    growth_tension: Mapping[str, object],
) -> dict[str, Any]:
    lifecycle = str(context.get("lifecycle"))
    budget = str(context.get("budget"))
    brand_reach = str(context.get("brand_reach"))
    business_model = str(context.get("business_model"))
    if lifecycle not in _MATURITY_PRIORITY:
        raise BriefIntelligenceError("lifecycle is unsupported")
    if budget not in _BUDGET_DIAGNOSIS:
        raise BriefIntelligenceError("budget is unsupported")
    if brand_reach not in _BRAND_DIAGNOSIS:
        raise BriefIntelligenceError("brand_reach is unsupported")
    if business_model not in {"b2b", "b2c"}:
        raise BriefIntelligenceError("business_model is unsupported")

    tension = dict(growth_tension)
    required_tension = {
        "tension_id",
        "audience",
        "problem",
        "business_constraint",
        "evidence_ids",
        "falsifier",
        "primary_outcome_metric",
    }
    if not required_tension.issubset(tension):
        raise BriefIntelligenceError("growth tension is incomplete")

    brand_state, brand_move = _BRAND_DIAGNOSIS[brand_reach]
    budget_mode, budget_move = _BUDGET_DIAGNOSIS[budget]
    decision_unit: dict[str, Any]
    if business_model == "b2b":
        decision_unit = {
            "model": "b2b_decision_unit",
            "roles": [
                "end_user",
                "influencer",
                "technical_evaluator",
                "procurement",
                "finance",
                "economic_buyer",
            ],
            "required_message_translation": (
                "Translate one evidence spine into role-specific value, risk and proof; "
                "do not create contradictory promises."
            ),
        }
    else:
        decision_unit = {
            "model": "b2c_audience_state",
            "states": [
                "trigger_context",
                "felt_anxiety",
                "desired_progress",
                "identity_expression",
                "current_alternative",
                "purchase_friction",
            ],
            "required_message_translation": (
                "Compress the same evidence into fast perception, felt relevance, product role "
                "and friction removal without inventing urgency."
            ),
        }

    goal = str(context.get("goal", "")).strip()
    lowered_goal = goal.casefold()
    challenged = any(
        term in lowered_goal
        for term in ("guarantee", "guaranteed", "viral", "top 1", "全球第一", "保证爆款")
    )
    questions = _critical_questions(context, product_evidence_register)
    market_neighborhood = compile_market_neighborhood(context)
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "brief_id": f"brief-{_digest(context)[:16]}",
        "maturity_diagnosis": {
            "declared_stage": lifecycle,
            "single_stage_priority": _MATURITY_PRIORITY[lifecycle],
        },
        "brand_momentum_diagnosis": {
            "declared_reach": brand_reach,
            "state": brand_state,
            "strategic_move": brand_move,
        },
        "budget_diagnosis": {
            "declared_budget": budget,
            "operating_mode": budget_mode,
            "strategic_move": budget_move,
            "paid_media_required": False if budget == "zero" else None,
        },
        "audience_decision_model": decision_unit,
        "market_neighborhood": market_neighborhood,
        "product_evidence_register_sha256": product_evidence_register.get(
            "content_sha256"
        ),
        "product_release_eligible": product_evidence_register.get(
            "all_claims_public_release_eligible"
        )
        is True,
        "critical_questions": questions,
        "critical_question_count": len(questions),
        "goal_feasibility": {
            "original_goal": goal,
            "challenged": challenged,
            "replacement_goal": (
                "Run one bounded, evidence-backed experiment against the pre-registered primary metric."
                if challenged
                else goal
            ),
            "reason": (
                "The stated goal contains an outcome that cannot be promised before observation."
                if challenged
                else "No unsupported outcome promise was detected; production evidence is still required."
            ),
        },
        "growth_tensions": [tension],
        "primary_growth_tension_id": tension["tension_id"],
        "secondary_objectives_may_not_override_primary": True,
        "human_release_required": True,
        "automatic_strategy_mutation_executed": False,
        "truth_boundary": (
            "This diagnosis converts declared inputs into one bounded operating choice. It does "
            "not independently verify the market, product claims, publishability or effect."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_brief_intelligence(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise BriefIntelligenceError("brief intelligence seal is invalid")
    tensions = payload.get("growth_tensions")
    if not isinstance(tensions, list) or len(tensions) != 1:
        raise BriefIntelligenceError("brief intelligence must contain one growth tension")
    if payload.get("critical_question_count") != len(payload.get("critical_questions", [])):
        raise BriefIntelligenceError("critical question count drifted")
    if int(payload.get("critical_question_count", 99)) > 5:
        raise BriefIntelligenceError("critical questions exceed five")
