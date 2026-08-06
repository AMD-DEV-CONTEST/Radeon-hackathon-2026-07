from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


class CodexIntegratedCampaignError(ValueError):
    """Raised when a Codex campaign system loses its brief or truth binding."""


PORTFOLIO_SCHEMA = "ProofLaunchCodexIntegratedCampaignPortfolioV1"
BLUEPRINT_SCHEMA = "ProofLaunchCodexIntegratedCampaignBlueprintsV1"
PACK_SCHEMA = "ProofLaunchCodexIntegratedCampaignPackV1"

SURFACE_IDS = (
    "linkedin",
    "tiktok",
    "reddit",
    "youtube",
    "instagram",
    "x",
    "google_search",
    "bing_search",
    "chatgpt_answers",
    "claude_answers",
    "gemini_answers",
    "perplexity_answers",
    "copilot_answers",
)

SEARCH_GEO_SURFACES = {
    "google_search",
    "bing_search",
    "chatgpt_answers",
    "claude_answers",
    "gemini_answers",
    "perplexity_answers",
    "copilot_answers",
}

MEDIA_KINDS = {"image_system", "video_system", "audio_system"}
EXPERIMENT_IDS = {
    "hook_hold",
    "qualified_participation",
    "proof_depth",
    "conversion_intent",
}

UNSUPPORTED_CLAIM_PATTERNS = (
    re.compile(r"\bguarantee(?:d|s)?\b", re.I),
    re.compile(r"\bwill (?:go viral|drive revenue|convert)\b", re.I),
    re.compile(r"\b(?:4a|top[- ]?1|world[- ]class|best[- ]in[- ]class)\b", re.I),
    re.compile(r"保证(?:爆款|营收|转化|效果)"),
    re.compile(r"必然(?:爆款|营收|转化|增长)"),
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _require_text(value: Any, *, field: str, minimum: int = 8) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise CodexIntegratedCampaignError(f"{field} is missing or too thin")
    if any(pattern.search(value) for pattern in UNSUPPORTED_CLAIM_PATTERNS):
        raise CodexIntegratedCampaignError(f"{field} contains an unsupported claim")
    return value.strip()


def _require_digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise CodexIntegratedCampaignError(f"{field} must be a SHA-256 digest")
    return value


def _verify_showcase(showcase: Mapping[str, Any]) -> None:
    unsigned = dict(showcase)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise CodexIntegratedCampaignError("source showcase digest is invalid")
    if (
        showcase.get("schema") != "ProofLaunchPlatformCapabilityShowcasePublicV1"
        or showcase.get("business_model_count") != 2
        or showcase.get("candidate_count") != 26
        or showcase.get("pre_human_quality_pass_count") != 26
        or showcase.get("release_eligible_count") != 0
        or showcase.get("human_review_completed_count") != 0
        or showcase.get("production_effect_observed") is not False
        or showcase.get("four_a_claim_eligible") is not False
        or showcase.get("top1_claim_eligible") is not False
        or showcase.get("automatic_publish_enabled") is not False
    ):
        raise CodexIntegratedCampaignError("source showcase truth boundary is invalid")


def _verify_blueprint_record(record: Mapping[str, Any]) -> None:
    business_model = record.get("business_model")
    if business_model not in {"b2b", "b2c"}:
        raise CodexIntegratedCampaignError("blueprint business model is invalid")
    _require_text(record.get("brief_id"), field="brief_id")
    core = record.get("strategic_core")
    required_core = (
        "campaign_system_name",
        "narrow_audience",
        "job_to_be_done",
        "category_enemy",
        "human_tension",
        "organizing_idea",
        "proof_spine",
        "promise_hypothesis",
        "rejection_rule",
        "zero_budget_growth_loop",
    )
    if not isinstance(core, Mapping):
        raise CodexIntegratedCampaignError("strategic core is missing")
    for key in required_core:
        _require_text(core.get(key), field=f"strategic_core.{key}", minimum=16)

    channel_strategy = record.get("channel_strategy")
    if not isinstance(channel_strategy, Mapping):
        raise CodexIntegratedCampaignError("channel strategy is missing")
    primary = channel_strategy.get("primary_surfaces")
    secondary = channel_strategy.get("secondary_surfaces")
    if (
        not isinstance(primary, list)
        or len(primary) != 2
        or len(set(primary)) != 2
        or not isinstance(secondary, list)
        or not 1 <= len(secondary) <= 4
        or set(primary) & set(secondary)
        or not (set(primary) | set(secondary)) <= set(SURFACE_IDS)
        or channel_strategy.get("paid_media_required") is not False
    ):
        raise CodexIntegratedCampaignError("channel focus violates the zero-budget portfolio")
    _require_text(channel_strategy.get("focus_rationale"), field="focus_rationale", minimum=30)

    phases = record.get("lifecycle_phases")
    if not isinstance(phases, list) or len(phases) != 4:
        raise CodexIntegratedCampaignError("exactly four lifecycle phases are required")
    assigned: list[str] = []
    for expected, phase in zip(("diagnose", "prove", "participate", "convert_and_learn"), phases):
        if not isinstance(phase, Mapping) or phase.get("phase_id") != expected:
            raise CodexIntegratedCampaignError("lifecycle phase sequence drifted")
        surfaces = phase.get("surface_ids")
        if not isinstance(surfaces, list) or not surfaces:
            raise CodexIntegratedCampaignError("lifecycle phase has no surface job")
        assigned.extend(str(item) for item in surfaces)
        for key in ("audience_state", "decision_job", "entry_evidence", "exit_signal", "stop_rule"):
            _require_text(phase.get(key), field=f"{expected}.{key}", minimum=12)
    if len(assigned) != len(set(assigned)) or set(assigned) != set(SURFACE_IDS):
        raise CodexIntegratedCampaignError("lifecycle phases must assign all 13 surfaces exactly once")

    email = record.get("email_sequence")
    if not isinstance(email, list) or len(email) != 4:
        raise CodexIntegratedCampaignError("campaign requires a four-email lifecycle sequence")
    for expected, message in enumerate(email, start=1):
        if not isinstance(message, Mapping) or message.get("sequence") != expected:
            raise CodexIntegratedCampaignError("email sequence order is invalid")
        for key in ("audience_state", "subject", "preview", "body", "cta", "falsifier"):
            _require_text(message.get(key), field=f"email.{expected}.{key}", minimum=12)

    media = record.get("production_directions")
    if not isinstance(media, list) or {row.get("kind") for row in media if isinstance(row, Mapping)} != MEDIA_KINDS:
        raise CodexIntegratedCampaignError("image, video and audio production directions are required")
    for direction in media:
        if not isinstance(direction, Mapping):
            raise CodexIntegratedCampaignError("media direction is invalid")
        for key in ("concept", "execution", "platform_adaptations", "avoid", "acceptance_test"):
            _require_text(direction.get(key), field=f"media.{direction.get('kind')}.{key}", minimum=20)

    search = record.get("search_geo_system")
    if not isinstance(search, Mapping):
        raise CodexIntegratedCampaignError("search/GEO system is missing")
    nodes = search.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 7:
        raise CodexIntegratedCampaignError("search/GEO system requires seven native nodes")
    if {node.get("surface_id") for node in nodes if isinstance(node, Mapping)} != SEARCH_GEO_SURFACES:
        raise CodexIntegratedCampaignError("search/GEO surface coverage is incomplete")
    for node in nodes:
        if not isinstance(node, Mapping):
            raise CodexIntegratedCampaignError("search/GEO node is invalid")
        for key in ("query_or_question", "answer_job", "source_requirement", "rejection_condition"):
            _require_text(node.get(key), field=f"search.{node.get('surface_id')}.{key}", minimum=12)

    flight = record.get("seven_day_flight")
    if not isinstance(flight, list) or len(flight) != 7:
        raise CodexIntegratedCampaignError("seven-day flight is incomplete")
    if [row.get("day") for row in flight if isinstance(row, Mapping)] != list(range(1, 8)):
        raise CodexIntegratedCampaignError("seven-day flight order is invalid")
    for slot in flight:
        if not isinstance(slot, Mapping) or slot.get("status") != "draft_pending_human_review":
            raise CodexIntegratedCampaignError("flight slot bypasses human review")
        if not set(slot.get("surface_ids", [])) <= set(SURFACE_IDS):
            raise CodexIntegratedCampaignError("flight slot uses an unknown surface")
        for key in ("content_job", "learning_question", "decision_after_observation"):
            _require_text(slot.get(key), field=f"flight.{slot.get('day')}.{key}", minimum=12)

    experiments = record.get("experiment_registry")
    if not isinstance(experiments, list) or {row.get("experiment_id") for row in experiments if isinstance(row, Mapping)} != EXPERIMENT_IDS:
        raise CodexIntegratedCampaignError("four frozen organic experiments are required")
    for experiment in experiments:
        if not isinstance(experiment, Mapping):
            raise CodexIntegratedCampaignError("experiment contract is invalid")
        for key in (
            "hypothesis",
            "primary_metric",
            "numerator",
            "denominator",
            "minimum_sample_rule",
            "success_rule",
            "kill_rule",
        ):
            _require_text(experiment.get(key), field=f"experiment.{experiment.get('experiment_id')}.{key}", minimum=10)
        if experiment.get("causal_claim_allowed") is not False:
            raise CodexIntegratedCampaignError("pre-observation experiments cannot claim causality")

    if (
        record.get("human_review_completed") is not False
        or record.get("production_effect_observed") is not False
        or record.get("external_publish_executed") is not False
        or record.get("paid_media_spend_usd") != 0
    ):
        raise CodexIntegratedCampaignError("blueprint overclaims execution or effect")


def compile_codex_integrated_campaign_portfolio(
    *,
    showcase: Mapping[str, Any],
    blueprints: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind Codex craft references into two coherent, zero-budget campaign systems."""

    _verify_showcase(showcase)
    if blueprints.get("schema") != BLUEPRINT_SCHEMA:
        raise CodexIntegratedCampaignError("campaign blueprint schema is invalid")
    blueprint_rows = blueprints.get("blueprints")
    if not isinstance(blueprint_rows, list) or len(blueprint_rows) != 2:
        raise CodexIntegratedCampaignError("exactly two campaign blueprints are required")
    blueprint_by_model: dict[str, Mapping[str, Any]] = {}
    for row in blueprint_rows:
        if not isinstance(row, Mapping):
            raise CodexIntegratedCampaignError("campaign blueprint row is invalid")
        _verify_blueprint_record(row)
        model = str(row["business_model"])
        if model in blueprint_by_model:
            raise CodexIntegratedCampaignError("duplicate campaign blueprint business model")
        blueprint_by_model[model] = row

    source_bundles = showcase.get("bundles")
    if not isinstance(source_bundles, list) or len(source_bundles) != 2:
        raise CodexIntegratedCampaignError("source showcase bundle coverage is invalid")
    packs: list[dict[str, Any]] = []
    for source in source_bundles:
        if not isinstance(source, Mapping):
            raise CodexIntegratedCampaignError("source bundle is invalid")
        model = str(source.get("business_model"))
        blueprint = blueprint_by_model.get(model)
        if blueprint is None or blueprint.get("brief_id") != source.get("brief", {}).get("brief_id"):
            raise CodexIntegratedCampaignError("blueprint escaped the frozen source brief")
        source_candidates = source.get("candidates")
        if (
            not isinstance(source_candidates, list)
            or [row.get("surface_id") for row in source_candidates if isinstance(row, Mapping)] != list(SURFACE_IDS)
            or any(row.get("capability_quality_pass") is not True for row in source_candidates if isinstance(row, Mapping))
            or any(row.get("release_eligible") is not False for row in source_candidates if isinstance(row, Mapping))
        ):
            raise CodexIntegratedCampaignError("source candidate coverage or truth state is invalid")
        phase_by_surface = {
            surface_id: phase["phase_id"]
            for phase in blueprint["lifecycle_phases"]
            for surface_id in phase["surface_ids"]
        }
        candidates = [
            {
                **dict(row),
                "lifecycle_phase": phase_by_surface[row["surface_id"]],
                "source_candidate_sha256": _require_digest(
                    row.get("candidate_sha256"), field="candidate_sha256"
                ),
            }
            for row in source_candidates
        ]
        pack: dict[str, Any] = {
            "schema": PACK_SCHEMA,
            "business_model": model,
            "brief": dict(source["brief"]),
            "source_showcase_sha256": showcase["content_sha256"],
            "source_receipt_sha256": source["source_receipt_sha256"],
            "source_quality_audit_sha256": source["source_quality_audit_sha256"],
            "strategic_core": dict(blueprint["strategic_core"]),
            "channel_strategy": dict(blueprint["channel_strategy"]),
            "lifecycle_phases": list(blueprint["lifecycle_phases"]),
            "platform_candidates": candidates,
            "email_sequence": list(blueprint["email_sequence"]),
            "production_directions": list(blueprint["production_directions"]),
            "search_geo_system": dict(blueprint["search_geo_system"]),
            "seven_day_flight": list(blueprint["seven_day_flight"]),
            "experiment_registry": list(blueprint["experiment_registry"]),
            "capability_quality_pass_count": 13,
            "release_eligible_count": 0,
            "human_review_completed": False,
            "production_effect_observed": False,
            "causal_effect_claim_allowed": False,
            "named_product_pk_completed": False,
            "external_publish_executed": False,
            "automatic_send_spend_or_strategy_mutation": False,
            "paid_media_spend_usd": 0,
            "publication_policy_state": source["publication_policy_state"],
            "truth_boundary": (
                "This pack demonstrates a Codex-authored integrated campaign system bound to one frozen brief. "
                "It does not prove named-human preference, external publication, market effect, revenue, 4A quality or named-product superiority."
            ),
        }
        pack["content_sha256"] = _digest(pack)
        packs.append(pack)
    portfolio: dict[str, Any] = {
        "schema": PORTFOLIO_SCHEMA,
        "source_showcase_sha256": showcase["content_sha256"],
        "business_model_count": 2,
        "pack_count": 2,
        "platform_candidate_count": 26,
        "email_count": 8,
        "production_direction_count": 6,
        "search_geo_node_count": 14,
        "seven_day_flight_slot_count": 14,
        "experiment_count": 8,
        "capability_quality_pass_count": 26,
        "release_eligible_count": 0,
        "human_review_completed_count": 0,
        "production_effect_observed": False,
        "causal_effect_claim_allowed": False,
        "named_product_pk_completed_count": 0,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "external_publish_executed": False,
        "automatic_send_spend_or_strategy_mutation": False,
        "paid_media_spend_usd": 0,
        "packs": packs,
        "truth_boundary": (
            "The portfolio proves contract-bound Codex campaign-pack assembly for B2B and B2C. "
            "All outputs remain pre-human capability evidence; B2C remains a synthetic benchmark and cannot be published as product content."
        ),
    }
    portfolio["content_sha256"] = _digest(portfolio)
    verify_codex_integrated_campaign_portfolio(portfolio)
    return portfolio


def verify_codex_integrated_campaign_portfolio(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise CodexIntegratedCampaignError("integrated campaign portfolio digest is invalid")
    if (
        payload.get("schema") != PORTFOLIO_SCHEMA
        or payload.get("business_model_count") != 2
        or payload.get("pack_count") != 2
        or payload.get("platform_candidate_count") != 26
        or payload.get("email_count") != 8
        or payload.get("production_direction_count") != 6
        or payload.get("search_geo_node_count") != 14
        or payload.get("seven_day_flight_slot_count") != 14
        or payload.get("experiment_count") != 8
        or payload.get("capability_quality_pass_count") != 26
        or payload.get("release_eligible_count") != 0
        or payload.get("human_review_completed_count") != 0
        or payload.get("production_effect_observed") is not False
        or payload.get("causal_effect_claim_allowed") is not False
        or payload.get("named_product_pk_completed_count") != 0
        or payload.get("four_a_claim_eligible") is not False
        or payload.get("top1_claim_eligible") is not False
        or payload.get("external_publish_executed") is not False
        or payload.get("automatic_send_spend_or_strategy_mutation") is not False
        or payload.get("paid_media_spend_usd") != 0
    ):
        raise CodexIntegratedCampaignError("integrated campaign portfolio truth boundary drifted")
    packs = payload.get("packs")
    if not isinstance(packs, list) or [pack.get("business_model") for pack in packs if isinstance(pack, Mapping)] != ["b2b", "b2c"]:
        raise CodexIntegratedCampaignError("integrated campaign pack coverage drifted")
    for pack in packs:
        if not isinstance(pack, Mapping):
            raise CodexIntegratedCampaignError("integrated campaign pack is invalid")
        unsigned_pack = dict(pack)
        pack_sha = unsigned_pack.pop("content_sha256", None)
        if pack_sha != _digest(unsigned_pack):
            raise CodexIntegratedCampaignError("integrated campaign pack digest is invalid")
        if (
            pack.get("schema") != PACK_SCHEMA
            or pack.get("source_showcase_sha256") != payload.get("source_showcase_sha256")
            or pack.get("capability_quality_pass_count") != 13
            or pack.get("release_eligible_count") != 0
            or pack.get("human_review_completed") is not False
            or pack.get("production_effect_observed") is not False
            or pack.get("causal_effect_claim_allowed") is not False
            or pack.get("external_publish_executed") is not False
            or pack.get("automatic_send_spend_or_strategy_mutation") is not False
            or pack.get("paid_media_spend_usd") != 0
        ):
            raise CodexIntegratedCampaignError("integrated campaign pack truth boundary drifted")
        if [row.get("surface_id") for row in pack.get("platform_candidates", [])] != list(SURFACE_IDS):
            raise CodexIntegratedCampaignError("integrated campaign platform coverage drifted")
        if pack.get("business_model") == "b2c" and pack.get("publication_policy_state") != "permanently_blocked_synthetic_benchmark":
            raise CodexIntegratedCampaignError("B2C synthetic publication block drifted")


__all__ = [
    "BLUEPRINT_SCHEMA",
    "CodexIntegratedCampaignError",
    "PACK_SCHEMA",
    "PORTFOLIO_SCHEMA",
    "compile_codex_integrated_campaign_portfolio",
    "verify_codex_integrated_campaign_portfolio",
]
