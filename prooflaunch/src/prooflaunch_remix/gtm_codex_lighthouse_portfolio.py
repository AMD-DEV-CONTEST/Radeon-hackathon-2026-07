from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from .gtm_codex_candidate_quality import (
    compile_codex_candidate_eval_plan,
    compile_codex_candidate_quality_audit,
    verify_codex_candidate_quality_audit,
)
from .gtm_codex_campaign_work_order import (
    SURFACE_IDS,
    compile_codex_campaign_generation_protocol,
    compile_codex_campaign_work_order,
    verify_codex_campaign_work_order,
)
from .gtm_industry_profile import (
    bind_industry_profile_strategy,
    compile_industry_gtm_profile,
)
from .gtm_strategy import (
    AudienceICP,
    BrandConstitution,
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    ClaimEvidence,
    EvidenceRights,
    IndustryRisk,
    LifecycleStage,
    ProductSurface,
    StrategyCompiler,
)


class CodexLighthousePortfolioError(ValueError):
    """A lighthouse candidate escaped its frozen synthetic brief or authority."""


CANDIDATE_SCHEMA = "ProofLaunchCodexLighthouseCandidateV1"
PORTFOLIO_SCHEMA = "ProofLaunchCodexLighthousePortfolioV1"
AUTHORING_SCHEMA = "ProofLaunchCodexWorkspaceAuthorshipReceiptV1"
QUALITY_PORTFOLIO_SCHEMA = "ProofLaunchCodexLighthouseQualityPortfolioV1"

_SHA = re.compile(r"^[0-9a-f]{64}$")
_SLUG = re.compile(r"^/[a-z0-9]+(?:[a-z0-9/-]*[a-z0-9])?$|^/$")

_ARCHETYPE_ROUTE: dict[str, dict[str, Any]] = {
    "b2b_saas": {
        "industry": "enterprise software",
        "risk": IndustryRisk.STANDARD,
        "surface": ProductSurface.WEB_APP,
    },
    "developer_tools": {
        "industry": "developer tools",
        "risk": IndustryRisk.STANDARD,
        "surface": ProductSurface.API,
    },
    "healthcare": {
        "industry": "healthcare",
        "risk": IndustryRisk.HIGH_REGULATION,
        "surface": ProductSurface.WEB_APP,
    },
    "manufacturing_industrial": {
        "industry": "manufacturing",
        "risk": IndustryRisk.STANDARD,
        "surface": ProductSurface.PHYSICAL_PRODUCT,
    },
    "marketplace": {
        "industry": "marketplace",
        "risk": IndustryRisk.STANDARD,
        "surface": ProductSurface.WEB_APP,
    },
    "financial_services": {
        "industry": "fintech",
        "risk": IndustryRisk.HIGH_REGULATION,
        "surface": ProductSurface.MOBILE_APP,
    },
    "ecommerce_dtc": {
        "industry": "ecommerce",
        "risk": IndustryRisk.STANDARD,
        "surface": ProductSurface.PHYSICAL_PRODUCT,
    },
    "consumer_app": {
        "industry": "consumer app",
        "risk": IndustryRisk.STANDARD,
        "surface": ProductSurface.MOBILE_APP,
    },
}


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, *, field: str, minimum: int = 12) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise CodexLighthousePortfolioError(f"{field} is missing or too thin")
    return value.strip()


def _text_list(
    value: Any, *, field: str, minimum_count: int, minimum_text: int = 4
) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) < minimum_count
        or any(not isinstance(item, str) or len(item.strip()) < minimum_text for item in value)
    ):
        raise CodexLighthousePortfolioError(f"{field} is incomplete")
    return [item.strip() for item in value]


def _request_from_draft(draft: Mapping[str, Any]) -> CampaignStrategyInput:
    selector = draft.get("selector")
    fixture = draft.get("fixture")
    if not isinstance(selector, Mapping) or not isinstance(fixture, Mapping):
        raise CodexLighthousePortfolioError("candidate selector or fixture is missing")
    archetype = str(selector.get("industry_archetype", ""))
    route = _ARCHETYPE_ROUTE.get(archetype)
    if route is None:
        raise CodexLighthousePortfolioError("candidate uses an unapproved lighthouse archetype")
    business_model = BusinessModel(str(selector.get("business_model")))
    lifecycle = LifecycleStage(str(selector.get("lifecycle")))
    budget = BudgetTier(str(selector.get("budget")))
    risk = route["risk"]
    claim = _text(fixture.get("approved_claim"), field="fixture.approved_claim", minimum=20)
    slug = f"{archetype}-{business_model.value}-{lifecycle.value}-{budget.value}"
    voice = tuple(_text_list(fixture.get("voice"), field="fixture.voice", minimum_count=3))
    prohibited = tuple(
        _text_list(
            fixture.get("prohibited_claims"),
            field="fixture.prohibited_claims",
            minimum_count=3,
        )
    )
    return CampaignStrategyInput(
        org_id="org-codex-lighthouse-clean-room",
        project_id="project-codex-lighthouse-clean-room",
        campaign_id=f"campaign-{slug}",
        owner="named-human-owner-required-before-real-use",
        industry=str(route["industry"]),
        lifecycle=lifecycle,
        budget=budget,
        industry_risk=risk,
        brand=BrandConstitution(
            brand_name=_text(fixture.get("brand_name"), field="fixture.brand_name", minimum=3),
            purpose=_text(fixture.get("jtbd"), field="fixture.jtbd", minimum=20),
            customer_promise=claim,
            voice_principles=voice,
            prohibited_tactics=prohibited,
        ),
        audience=AudienceICP(
            audience_id=f"audience-{slug}",
            name=_text(fixture.get("audience"), field="fixture.audience", minimum=15),
            business_model=business_model,
            core_problem=_text(fixture.get("jtbd"), field="fixture.jtbd", minimum=20),
            desired_outcome=_text(fixture.get("offer"), field="fixture.offer", minimum=15),
            buying_context=f"Synthetic clean-room capability test for {archetype.replace('_', ' ')}.",
        ),
        objective="Test whether one industry-native campaign system can produce a qualified next-step decision without implying an unobserved market outcome.",
        offer=_text(fixture.get("offer"), field="fixture.offer", minimum=15),
        landing_url=f"https://example.test/codex-lighthouse/{slug}",
        claims=(
            ClaimEvidence(
                claim_id=f"claim-{_digest({'selector': _normalize(selector), 'claim': claim})[:18]}",
                text=claim,
                evidence_uri=f"fixture://codex-lighthouse/{slug}",
                evidence_sha256=_digest({"selector": _normalize(selector), "approved_claim": claim}),
                rights=EvidenceRights.OWNED,
                rights_reference="synthetic-clean-room-owner-fixture",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                approved_by="named-synthetic-fixture-owner",
                specialist_approved_by=(
                    "named-synthetic-licensed-specialist"
                    if risk is IndustryRisk.HIGH_REGULATION
                    else None
                ),
            ),
        ),
        product_category=_text(
            fixture.get("product_name"), field="fixture.product_name", minimum=3
        ),
        product_surface=route["surface"],
        distribution_platform=str(
            draft.get("channel_decision", {}).get("primary_surface", "owner_review")
        ),
        audience_role="primary_decision_unit",
        schedule_timezone="America/New_York",
    )


def _verify_draft_shape(draft: Mapping[str, Any]) -> None:
    fixture = draft.get("fixture")
    campaign = draft.get("campaign_system")
    channel = draft.get("channel_decision")
    if not isinstance(fixture, Mapping) or not isinstance(campaign, Mapping) or not isinstance(channel, Mapping):
        raise CodexLighthousePortfolioError("candidate core is incomplete")
    for key in (
        "name",
        "human_tension",
        "category_enemy",
        "organizing_idea",
        "proof_spine",
        "promise_hypothesis",
        "falsifier",
        "growth_loop",
    ):
        _text(campaign.get(key), field=f"campaign_system.{key}", minimum=18)
    primary = str(channel.get("primary_surface", ""))
    secondary = str(channel.get("secondary_surface", ""))
    if primary not in SURFACE_IDS or secondary not in SURFACE_IDS or primary == secondary:
        raise CodexLighthousePortfolioError("candidate focus surfaces are invalid")
    _text_list(channel.get("excluded_surfaces"), field="excluded_surfaces", minimum_count=1)
    _text(channel.get("reason"), field="channel_decision.reason", minimum=25)

    assets = draft.get("platform_assets")
    if not isinstance(assets, list) or len(assets) != 2:
        raise CodexLighthousePortfolioError("candidate requires exactly two deep platform assets")
    if {row.get("surface_id") for row in assets if isinstance(row, Mapping)} != {primary, secondary}:
        raise CodexLighthousePortfolioError("platform assets escaped the two focus surfaces")
    for index, asset in enumerate(assets):
        if not isinstance(asset, Mapping):
            raise CodexLighthousePortfolioError("platform asset is invalid")
        for key in (
            "native_format",
            "audience_state",
            "hook",
            "full_copy",
            "cta",
            "participation",
            "proof_and_limitation",
            "event_name",
        ):
            _text(asset.get(key), field=f"platform_assets.{index}.{key}", minimum=8)
        if asset.get("release_state") != "draft_pending_human_review":
            raise CodexLighthousePortfolioError("platform asset bypasses human review")

    email = draft.get("email")
    seo = draft.get("seo_page")
    geo = draft.get("geo_answer")
    video = draft.get("video_script")
    experiment = draft.get("experiment")
    for label, value in (
        ("email", email),
        ("seo_page", seo),
        ("geo_answer", geo),
        ("video_script", video),
        ("experiment", experiment),
    ):
        if not isinstance(value, Mapping):
            raise CodexLighthousePortfolioError(f"{label} is missing")
    for key in ("trigger", "delay", "segment", "subject", "preview", "body", "cta", "suppression", "exit"):
        _text(email.get(key), field=f"email.{key}", minimum=6)
    for key in ("query", "title", "meta", "hero", "cta", "rejection_condition"):
        _text(seo.get(key), field=f"seo_page.{key}", minimum=8)
    if not isinstance(seo.get("slug"), str) or _SLUG.fullmatch(str(seo["slug"])) is None:
        raise CodexLighthousePortfolioError("seo_page.slug is invalid")
    _text_list(seo.get("outline"), field="seo_page.outline", minimum_count=4)
    _text_list(seo.get("schema_types"), field="seo_page.schema_types", minimum_count=2)
    _text_list(seo.get("internal_links"), field="seo_page.internal_links", minimum_count=2)
    for key in ("question", "direct_answer", "entity_statement", "evidence_boundary", "nonfit", "cta"):
        _text(geo.get(key), field=f"geo_answer.{key}", minimum=8)
    _text_list(geo.get("required_sources"), field="geo_answer.required_sources", minimum_count=2)

    if video.get("duration_seconds") != 15 or not isinstance(video.get("shots"), list) or len(video["shots"]) != 3:
        raise CodexLighthousePortfolioError("video script requires three shots over 15 seconds")
    cursor = 0
    for index, shot in enumerate(video["shots"]):
        if (
            not isinstance(shot, Mapping)
            or shot.get("start") != cursor
            or not isinstance(shot.get("end"), int)
            or shot["end"] <= cursor
        ):
            raise CodexLighthousePortfolioError("video shot timing is invalid")
        cursor = shot["end"]
        for key in ("visual", "audio", "caption", "acceptance_test"):
            _text(shot.get(key), field=f"video_script.shots.{index}.{key}", minimum=5)
    if cursor != 15:
        raise CodexLighthousePortfolioError("video shots do not cover exactly 15 seconds")
    for key in (
        "hypothesis",
        "primary_metric",
        "numerator",
        "denominator",
        "baseline",
        "minimum_sample_rule",
        "success_rule",
        "kill_rule",
    ):
        _text(experiment.get(key), field=f"experiment.{key}", minimum=8)
    if experiment.get("causal_claim_allowed") is not False:
        raise CodexLighthousePortfolioError("candidate experiment cannot pre-claim causality")
    _text(draft.get("truth_boundary"), field="truth_boundary", minimum=30)


def compile_lighthouse_candidate(
    draft: Mapping[str, Any], *, generated_at: str = "2026-08-03T15:00:00Z"
) -> dict[str, Any]:
    _verify_draft_shape(draft)
    request = _request_from_draft(draft)
    strategy = StrategyCompiler().compile(request, at=generated_at)
    profile = compile_industry_gtm_profile(
        request,
        source_strategy_sha256=_digest(strategy),
    )
    profile = bind_industry_profile_strategy(profile, strategy_id=strategy.strategy_id)
    selector = draft["selector"]
    if (
        profile["industry_archetype"] != selector["industry_archetype"]
        or request.audience.business_model.value != selector["business_model"]
        or request.lifecycle.value != selector["lifecycle"]
        or request.budget.value != selector["budget"]
    ):
        raise CodexLighthousePortfolioError("candidate selector escaped compiled context")
    protocol = compile_codex_campaign_generation_protocol()
    work_order = compile_codex_campaign_work_order(
        request,
        strategy,
        profile,
        protocol=protocol,
    )
    verify_codex_campaign_work_order(work_order, protocol=protocol)
    focus = set(work_order["strategy_contract"]["primary_platform_surfaces"]) | set(
        work_order["strategy_contract"]["secondary_platform_surfaces"]
    )
    selected_surfaces = {
        draft["channel_decision"]["primary_surface"],
        draft["channel_decision"]["secondary_surface"],
    }
    if not selected_surfaces <= focus:
        raise CodexLighthousePortfolioError(
            "candidate focus escaped the deterministic channel strategy"
        )
    approved_claim = draft["fixture"]["approved_claim"]
    proof_text = " ".join(
        [draft["campaign_system"]["proof_spine"]]
        + [row["proof_and_limitation"] for row in draft["platform_assets"]]
    )
    if approved_claim not in proof_text:
        raise CodexLighthousePortfolioError(
            "candidate output does not preserve the exact approved claim"
        )

    candidate: dict[str, Any] = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": "codex-lighthouse-" + _digest(draft)[:20],
        "selector": dict(selector),
        "work_order_id": work_order["work_order_id"],
        "work_order_sha256": work_order["content_sha256"],
        "protocol_sha256": protocol["content_sha256"],
        "request_sha256": work_order["request_sha256"],
        "strategy_sha256": work_order["strategy_sha256"],
        "authorship": {
            "schema": AUTHORING_SCHEMA,
            "mode": "codex_workspace_clean_room_reference_authoring",
            "workspace_model_authorship_asserted": True,
            "flagship_api_inference_observed": False,
            "provider_response_id": None,
            "api_call_count": "not_measured_by_worktree",
            "training_observed": False,
            "source_imitation_requested": False,
            "synthetic_reference_only": True,
        },
        "fixture": dict(draft["fixture"]),
        "campaign_system": dict(draft["campaign_system"]),
        "channel_decision": dict(draft["channel_decision"]),
        "platform_assets": list(draft["platform_assets"]),
        "email": dict(draft["email"]),
        "seo_page": dict(draft["seo_page"]),
        "geo_answer": dict(draft["geo_answer"]),
        "video_script": dict(draft["video_script"]),
        "experiment": dict(draft["experiment"]),
        "execution_state": {
            "workspace_authored_candidate_present": True,
            "level_1_mechanical_audit_present": False,
            "calibrated_model_critic_passed": False,
            "qualified_human_review_count": 0,
            "release_eligible": False,
            "external_publish_executed": False,
            "production_effect_observed": False,
            "causal_revenue_effect_proven": False,
            "automatic_strategy_mutation_executed": False,
        },
        "truth_boundary": draft["truth_boundary"],
    }
    candidate["content_sha256"] = _digest(candidate)
    verify_lighthouse_candidate(candidate)
    return candidate


def verify_lighthouse_candidate(candidate: Mapping[str, Any]) -> None:
    unsigned = dict(candidate)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise CodexLighthousePortfolioError("lighthouse candidate digest is invalid")
    authorship = candidate.get("authorship", {})
    state = candidate.get("execution_state", {})
    if (
        candidate.get("schema") != CANDIDATE_SCHEMA
        or _SHA.fullmatch(str(candidate.get("work_order_sha256", ""))) is None
        or _SHA.fullmatch(str(candidate.get("protocol_sha256", ""))) is None
        or authorship.get("workspace_model_authorship_asserted") is not True
        or authorship.get("flagship_api_inference_observed") is not False
        or authorship.get("api_call_count") != "not_measured_by_worktree"
        or authorship.get("synthetic_reference_only") is not True
        or state.get("workspace_authored_candidate_present") is not True
        or state.get("level_1_mechanical_audit_present") is not False
        or state.get("calibrated_model_critic_passed") is not False
        or state.get("qualified_human_review_count") != 0
        or state.get("release_eligible") is not False
        or state.get("external_publish_executed") is not False
        or state.get("production_effect_observed") is not False
        or state.get("causal_revenue_effect_proven") is not False
        or state.get("automatic_strategy_mutation_executed") is not False
    ):
        raise CodexLighthousePortfolioError("lighthouse candidate authority drifted")
    _verify_draft_shape(candidate)


def compile_lighthouse_portfolio(
    drafts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(drafts) != 8:
        raise CodexLighthousePortfolioError("lighthouse portfolio requires eight cases")
    candidates = [compile_lighthouse_candidate(draft) for draft in drafts]
    selectors = [candidate["selector"] for candidate in candidates]
    selector_keys = {
        (
            row["industry_archetype"],
            row["business_model"],
            row["lifecycle"],
            row["budget"],
        )
        for row in selectors
    }
    if len(selector_keys) != 8:
        raise CodexLighthousePortfolioError("lighthouse selectors are duplicated")
    for model in ("b2b", "b2c"):
        model_rows = [row for row in selectors if row["business_model"] == model]
        if len(model_rows) != 4 or {row["lifecycle"] for row in model_rows} != {
            "pre_pmf",
            "launch",
            "growth",
            "mature",
        }:
            raise CodexLighthousePortfolioError(
                "each business model must cover all four lifecycle stages"
            )
    if {row["budget"] for row in selectors} != {"zero", "small", "scaled"}:
        raise CodexLighthousePortfolioError("lighthouse budget coverage is incomplete")
    if len({row["industry_archetype"] for row in selectors}) != 8:
        raise CodexLighthousePortfolioError("lighthouse industry coverage is incomplete")
    regulated = sum(
        _ARCHETYPE_ROUTE[row["industry_archetype"]]["risk"]
        is IndustryRisk.HIGH_REGULATION
        for row in selectors
    )
    if regulated != 2:
        raise CodexLighthousePortfolioError("exactly two regulated lighthouse cases are required")
    portfolio: dict[str, Any] = {
        "schema": PORTFOLIO_SCHEMA,
        "source_draft_set_sha256": _digest(list(drafts)),
        "candidate_count": 8,
        "business_model_count": 2,
        "industry_archetype_count": 8,
        "lifecycle_coverage_per_business_model": 4,
        "budget_tier_count": 3,
        "regulated_candidate_count": regulated,
        "workspace_authored_candidate_count": 8,
        "platform_asset_count": 16,
        "email_count": 8,
        "seo_page_count": 8,
        "geo_answer_count": 8,
        "video_script_count": 8,
        "experiment_count": 8,
        "level_1_mechanical_audit_pass_count": 0,
        "calibrated_model_critic_pass_count": 0,
        "qualified_human_review_count": 0,
        "release_eligible_count": 0,
        "external_publish_executed_count": 0,
        "production_effect_observed_count": 0,
        "causal_revenue_effect_proven_count": 0,
        "named_product_pk_completed_count": 0,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "candidates": candidates,
        "truth_boundary": (
            "These eight clean-room Codex workspace candidates demonstrate deeper generated execution across B2B/B2C, all lifecycle stages, three budget tiers and eight industries. "
            "They are synthetic, pre-audit and pre-human capability references; they prove neither publication readiness, preference, market effect, revenue, 4A quality nor named-product superiority."
        ),
    }
    portfolio["content_sha256"] = _digest(portfolio)
    verify_lighthouse_portfolio(portfolio)
    return portfolio


def verify_lighthouse_portfolio(portfolio: Mapping[str, Any]) -> None:
    unsigned = dict(portfolio)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise CodexLighthousePortfolioError("lighthouse portfolio digest is invalid")
    candidates = portfolio.get("candidates")
    if (
        portfolio.get("schema") != PORTFOLIO_SCHEMA
        or _SHA.fullmatch(str(portfolio.get("source_draft_set_sha256", ""))) is None
        or portfolio.get("candidate_count") != 8
        or not isinstance(candidates, list)
        or len(candidates) != 8
        or portfolio.get("workspace_authored_candidate_count") != 8
        or portfolio.get("level_1_mechanical_audit_pass_count") != 0
        or portfolio.get("calibrated_model_critic_pass_count") != 0
        or portfolio.get("qualified_human_review_count") != 0
        or portfolio.get("release_eligible_count") != 0
        or portfolio.get("external_publish_executed_count") != 0
        or portfolio.get("production_effect_observed_count") != 0
        or portfolio.get("causal_revenue_effect_proven_count") != 0
        or portfolio.get("named_product_pk_completed_count") != 0
        or portfolio.get("four_a_claim_eligible") is not False
        or portfolio.get("top1_claim_eligible") is not False
    ):
        raise CodexLighthousePortfolioError("lighthouse portfolio boundary drifted")
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise CodexLighthousePortfolioError("lighthouse candidate is invalid")
        verify_lighthouse_candidate(candidate)


def compile_lighthouse_quality_portfolio(
    portfolio: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal deterministic Level-1 receipts without upgrading human or effect authority."""

    verify_lighthouse_portfolio(portfolio)
    candidates = portfolio["candidates"]
    audits: list[dict[str, Any]] = []
    for candidate in candidates:
        receipt = compile_codex_candidate_quality_audit(candidate)
        verify_codex_candidate_quality_audit(receipt, candidate=candidate)
        audits.append(receipt)
    pass_count = sum(receipt["passed"] is True for receipt in audits)
    failure_count = sum(int(receipt["failure_count"]) for receipt in audits)
    payload: dict[str, Any] = {
        "schema": QUALITY_PORTFOLIO_SCHEMA,
        "source_portfolio_sha256": portfolio["content_sha256"],
        "candidate_count": len(candidates),
        "level_1_audit_count": len(audits),
        "level_1_pass_count": pass_count,
        "level_1_reject_count": len(audits) - pass_count,
        "located_critical_failure_count": failure_count,
        "eval_plan": compile_codex_candidate_eval_plan(),
        "calibrated_model_critic_pass_count": 0,
        "human_development_eval_completed_count": 0,
        "qualified_human_review_count": 0,
        "named_product_baseline_count": 0,
        "named_product_pk_completed_count": 0,
        "release_eligible_count": 0,
        "external_publish_executed_count": 0,
        "external_action_count": 0,
        "production_effect_observed_count": 0,
        "causal_revenue_effect_proven_count": 0,
        "model_critic_counts_in_preference_denominator": False,
        "model_critic_may_promote_or_release": False,
        "four_a_quality_proven": False,
        "top1_claim_eligible": False,
        "audits": audits,
        "truth_boundary": (
            "These content-addressed receipts prove only deterministic Level-1 mechanics for eight synthetic Codex workspace candidates. "
            "They do not prove human preference, publication readiness, 4A quality, Top-1 standing, virality, production effect, conversion, revenue, causal lift or named-product superiority."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_lighthouse_quality_portfolio(payload, portfolio=portfolio)
    return payload


def verify_lighthouse_quality_portfolio(
    quality: Mapping[str, Any],
    *,
    portfolio: Mapping[str, Any],
) -> None:
    verify_lighthouse_portfolio(portfolio)
    unsigned = dict(quality)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise CodexLighthousePortfolioError("lighthouse quality portfolio digest is invalid")
    audits = quality.get("audits")
    if (
        quality.get("schema") != QUALITY_PORTFOLIO_SCHEMA
        or quality.get("source_portfolio_sha256") != portfolio.get("content_sha256")
        or quality.get("candidate_count") != 8
        or quality.get("level_1_audit_count") != 8
        or not isinstance(audits, list)
        or len(audits) != 8
        or quality.get("eval_plan") != compile_codex_candidate_eval_plan()
        or quality.get("calibrated_model_critic_pass_count") != 0
        or quality.get("human_development_eval_completed_count") != 0
        or quality.get("qualified_human_review_count") != 0
        or quality.get("named_product_baseline_count") != 0
        or quality.get("named_product_pk_completed_count") != 0
        or quality.get("release_eligible_count") != 0
        or quality.get("external_publish_executed_count") != 0
        or quality.get("external_action_count") != 0
        or quality.get("production_effect_observed_count") != 0
        or quality.get("causal_revenue_effect_proven_count") != 0
        or quality.get("model_critic_counts_in_preference_denominator") is not False
        or quality.get("model_critic_may_promote_or_release") is not False
        or quality.get("four_a_quality_proven") is not False
        or quality.get("top1_claim_eligible") is not False
    ):
        raise CodexLighthousePortfolioError("lighthouse quality authority drifted")
    pass_count = 0
    failure_count = 0
    for candidate, receipt in zip(portfolio["candidates"], audits, strict=True):
        verify_codex_candidate_quality_audit(receipt, candidate=candidate)
        pass_count += receipt["passed"] is True
        failure_count += int(receipt["failure_count"])
    if (
        quality.get("level_1_pass_count") != pass_count
        or quality.get("level_1_reject_count") != 8 - pass_count
        or quality.get("located_critical_failure_count") != failure_count
    ):
        raise CodexLighthousePortfolioError("lighthouse quality totals drifted")


__all__ = [
    "AUTHORING_SCHEMA",
    "CANDIDATE_SCHEMA",
    "PORTFOLIO_SCHEMA",
    "QUALITY_PORTFOLIO_SCHEMA",
    "CodexLighthousePortfolioError",
    "compile_lighthouse_candidate",
    "compile_lighthouse_portfolio",
    "compile_lighthouse_quality_portfolio",
    "verify_lighthouse_candidate",
    "verify_lighthouse_portfolio",
    "verify_lighthouse_quality_portfolio",
]
