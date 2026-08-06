from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA = "ProofLaunchGTMCodexCandidateQualityAuditV1"
MAX_CROSS_ASSET_JACCARD = 0.72
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SLUG = re.compile(r"^/?[a-z0-9]+(?:[-/][a-z0-9]+)*$")
_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)

CRITIC_IDS = (
    "campaign_system_specific_not_generic",
    "platform_expression_native_not_reformatted",
    "audience_language_and_objection_fit",
    "proof_and_limitation_co_present",
)

_REQUIRED_TOP_LEVEL = (
    "selector",
    "fixture",
    "campaign_system",
    "channel_decision",
    "platform_assets",
    "email",
    "seo_page",
    "geo_answer",
    "video_script",
    "experiment",
    "truth_boundary",
)

_AUTHORITY_EFFECT_FIELDS = frozenset(
    {
        "release_eligible",
        "release_approved",
        "publish_approved",
        "automatic_publish_enabled",
        "automatic_send_enabled",
        "automatic_spend_enabled",
        "automatic_strategy_mutation_enabled",
        "automatic_strategy_mutation_executed",
        "external_publish_executed",
        "external_send_executed",
        "external_contact_executed",
        "human_review_completed",
        "preference_observed",
        "named_product_pk_won",
        "effect_alignment_achieved",
        "production_effect_observed",
        "causal_effect_claim_allowed",
        "causal_revenue_claim_allowed",
        "causal_revenue_effect_proven",
        "four_a_claim_eligible",
        "top1_claim_eligible",
        "automatic_external_action_count",
        "paid_media_spend_usd",
        "spend_executed_usd",
        "external_action_count",
    }
)

_PENDING_RELEASE_STATES = frozenset(
    {
        "pending",
        "pending_human_review",
        "pending_named_human_review",
        "draft_pending_human_review",
        "sealed_candidate_pending_human_review",
    }
)

_NEGATIONS = (
    "not ",
    "no ",
    "never ",
    "cannot ",
    "can't ",
    "does not ",
    "is not ",
    "unproven ",
    "without ",
    "can imply ",
    "words that ",
    "avoid ",
    "prohibit ",
    "reject ",
    "stop ",
    "不",
    "未",
    "无",
    "不能",
    "不会",
)

_FORBIDDEN_PATTERNS = (
    ("guaranteed_outcome_claim", re.compile(r"\bguarantee(?:d|s)?\b", re.I)),
    (
        "top1_claim",
        re.compile(
            r"(?:\btop[\s-]*1\b|#\s*1\b|\bnumber\s+one\b|全球第一|世界第一|第一名)",
            re.I,
        ),
    ),
    ("four_a_claim", re.compile(r"(?:\b4a(?:[\s-]*(?:grade|level|quality))?\b|4A级)", re.I)),
    ("viral_claim", re.compile(r"(?:\bviral\b|爆款)", re.I)),
    (
        "revenue_claim",
        re.compile(
            r"(?:\b(?:increase|grow|boost|drive|deliver|generate|double|triple|lift)\b.{0,48}\brevenue\b|"
            r"\brevenue\b.{0,48}\b(?:increase|growth|lift|gain|double|triple)\b|"
            r"营收.{0,24}(?:增长|提升|翻倍|暴涨)|(?:增长|提升|翻倍|暴涨).{0,24}营收)",
            re.I | re.S,
        ),
    ),
)


class CodexCandidateQualityError(ValueError):
    """A candidate or its deterministic quality receipt is malformed or tampered."""


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CodexCandidateQualityError("value is not canonical JSON") from error


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def candidate_content_sha256(candidate: Mapping[str, Any]) -> str:
    unsigned = dict(candidate)
    unsigned.pop("content_sha256", None)
    return sha256_json(unsigned)


def _seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = sha256_json(payload)
    return sealed


def compile_codex_candidate_eval_plan() -> dict[str, Any]:
    """Return the frozen evaluation plan; it grants no model-judge authority."""

    return {
        "schema": "ProofLaunchGTMCodexCandidateEvalPlanV1",
        "dataset": {
            "smoke_case_count": 24,
            "smoke_coverage": "2_business_models_x_4_lifecycles_x_3_budgets",
            "heldout_case_count": 60,
            "heldout_coverage": "20_industry_archetypes_x_3_prespecified_slices",
            "regulated_case_count": 72,
            "mechanical_case_count": 456,
            "calibration_and_heldout_digest_overlap_allowed": False,
        },
        "level_1": {
            "deterministic": True,
            "blocks_on_any_failure": True,
            "maximum_cross_asset_token_jaccard": MAX_CROSS_ASSET_JACCARD,
            "critical_failure_tolerance": 0,
        },
        "level_2_model_critics": {
            "critic_ids": list(CRITIC_IDS),
            "human_labelled_cases_per_critic": 100,
            "balanced_positive_negative_required": True,
            "minimum_tpr_exclusive": 0.8,
            "minimum_tnr_exclusive": 0.8,
            "minimum_tpr_wilson_lower_95_exclusive": 0.7,
            "minimum_tnr_wilson_lower_95_exclusive": 0.7,
            "may_block": True,
            "may_locate_failures": True,
            "counts_in_preference_denominator": False,
            "may_promote_or_release": False,
        },
        "level_3_human_development_gate": {
            "heldout_case_count": 12,
            "independent_humans_per_case": 5,
            "source_hidden": True,
            "model_may_substitute": False,
            "development_result_is_not_named_product_or_market_effect": True,
        },
        "regression_gate": {
            "run_level_1_on_every_candidate": True,
            "run_24_smoke_on_every_change": True,
            "run_456_mechanical_before_release_queue": True,
            "failure_action": "reject_fail_closed_with_located_failures",
        },
        "truth_boundary": (
            "This plan evaluates deterministic candidate mechanics and prepares separately "
            "calibrated model critics and source-hidden human review. Model critics may only "
            "block or locate failures and never count as preference, promotion, release, "
            "publication, production effect, or causal revenue evidence."
        ),
    }


class _Audit:
    def __init__(self) -> None:
        self.failures: list[dict[str, Any]] = []
        self.gates: set[str] = set()

    def check(self, gate_id: str) -> None:
        self.gates.add(gate_id)

    def fail(
        self,
        gate_id: str,
        path: str,
        code: str,
        message: str,
        *,
        observed: object | None = None,
        threshold: object | None = None,
    ) -> None:
        self.gates.add(gate_id)
        row: dict[str, Any] = {
            "gate_id": gate_id,
            "path": path,
            "code": code,
            "message": message,
            "severity": "critical",
        }
        if observed is not None:
            row["observed"] = observed
        if threshold is not None:
            row["threshold"] = threshold
        self.failures.append(row)

    def gate_checks(self) -> list[dict[str, Any]]:
        failed = {row["gate_id"] for row in self.failures}
        counts = {
            gate: sum(row["gate_id"] == gate for row in self.failures)
            for gate in self.gates
        }
        return [
            {
                "gate_id": gate,
                "passed": gate not in failed,
                "failure_count": counts[gate],
                "severity": "critical",
            }
            for gate in sorted(self.gates)
        ]


def _mapping(value: object, audit: _Audit, gate: str, path: str) -> Mapping[str, Any] | None:
    audit.check(gate)
    if not isinstance(value, Mapping):
        audit.fail(gate, path, "mapping_required", "field must be an object")
        return None
    return value


def _text(
    value: object,
    audit: _Audit,
    gate: str,
    path: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> str | None:
    audit.check(gate)
    if not isinstance(value, str) or len(value.strip()) < minimum:
        audit.fail(
            gate,
            path,
            "text_too_short_or_missing",
            f"field must contain at least {minimum} non-whitespace characters",
            observed=len(value.strip()) if isinstance(value, str) else None,
            threshold=minimum,
        )
        return None
    result = value.strip()
    if maximum is not None and len(result) > maximum:
        audit.fail(
            gate,
            path,
            "text_too_long",
            f"field must contain no more than {maximum} characters",
            observed=len(result),
            threshold=maximum,
        )
    return result


def _first(mapping: Mapping[str, Any], names: Sequence[str]) -> tuple[str, object]:
    for name in names:
        if name in mapping:
            return name, mapping[name]
    return names[0], None


def _required_alias_text(
    mapping: Mapping[str, Any],
    names: Sequence[str],
    audit: _Audit,
    gate: str,
    path: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> str | None:
    name, value = _first(mapping, names)
    return _text(
        value,
        audit,
        gate,
        f"{path}.{name}",
        minimum=minimum,
        maximum=maximum,
    )


def _approved_claim(candidate: Mapping[str, Any], audit: _Audit) -> str | None:
    gate = "fixture_and_approved_claim"
    fixture = _mapping(candidate.get("fixture"), audit, gate, "fixture")
    if fixture is None:
        return None
    for aliases, minimum in (
        (("brand_name",), 3),
        (("product_name",), 3),
        (("audience",), 20),
        (("jtbd", "job_to_be_done"), 20),
        (("offer",), 20),
    ):
        _required_alias_text(
            fixture,
            aliases,
            audit,
            gate,
            "fixture",
            minimum=minimum,
        )
    claim = _required_alias_text(
        fixture,
        ("approved_claim", "approved_claim_exact_text", "claim"),
        audit,
        gate,
        "fixture",
        minimum=12,
    )
    prohibited = fixture.get("prohibited_claims")
    if (
        not isinstance(prohibited, list)
        or len(prohibited) < 1
        or any(not isinstance(item, str) or len(item.strip()) < 12 for item in prohibited)
    ):
        audit.fail(
            gate,
            "fixture.prohibited_claims",
            "prohibited_claims_missing",
            "fixture requires at least one explicit prohibited claim",
        )
    voice = fixture.get("voice")
    if (
        not isinstance(voice, list)
        or len(voice) < 2
        or any(not isinstance(item, str) or len(item.strip()) < 3 for item in voice)
    ):
        audit.fail(
            gate,
            "fixture.voice",
            "voice_contract_missing",
            "fixture requires at least two usable voice principles",
        )
    return claim


def _selector(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "selector_contract"
    selector = _mapping(candidate.get("selector"), audit, gate, "selector")
    if selector is None:
        return
    _required_alias_text(
        selector,
        ("industry_archetype", "industry", "product_category"),
        audit,
        gate,
        "selector",
        minimum=3,
    )
    for field, allowed in (
        ("business_model", {"b2b", "b2c"}),
        ("lifecycle", {"pre_pmf", "launch", "growth", "mature"}),
        ("budget", {"zero", "small", "scaled"}),
    ):
        value = selector.get(field)
        if value not in allowed:
            audit.fail(
                gate,
                f"selector.{field}",
                "invalid_selector_value",
                f"{field} is outside the frozen selector vocabulary",
                observed=value,
                threshold=sorted(allowed),
            )


def _campaign_system(candidate: Mapping[str, Any], audit: _Audit) -> Mapping[str, Any] | None:
    gate = "campaign_system_contract"
    system = _mapping(candidate.get("campaign_system"), audit, gate, "campaign_system")
    if system is None:
        return None
    requirements = (
        (("campaign_system_name", "name", "title"), 6),
        (("human_tension",), 20),
        (("category_enemy",), 20),
        (("organizing_idea",), 20),
        (("proof_spine",), 20),
        (("promise_hypothesis",), 20),
        (("falsifier", "rejection_rule"), 20),
        (("growth_loop",), 20),
    )
    for aliases, minimum in requirements:
        _required_alias_text(
            system,
            aliases,
            audit,
            gate,
            "campaign_system",
            minimum=minimum,
        )
    return system


def _selected_platforms(
    candidate: Mapping[str, Any], audit: _Audit
) -> tuple[str, str] | None:
    gate = "channel_surface_binding"
    decision = _mapping(candidate.get("channel_decision"), audit, gate, "channel_decision")
    if decision is None:
        return None
    platforms: list[object]
    for list_name in ("platforms", "selected_platforms", "focus_platforms"):
        value = decision.get(list_name)
        if isinstance(value, list):
            platforms = value
            break
    else:
        _, primary = _first(
            decision,
            ("primary_surface", "primary_platform", "primary_channel"),
        )
        _, secondary = _first(
            decision,
            ("secondary_surface", "secondary_platform", "secondary_channel"),
        )
        platforms = [primary, secondary]
    normalized = [item.strip().casefold() for item in platforms if isinstance(item, str) and item.strip()]
    if len(platforms) != 2 or len(normalized) != 2:
        audit.fail(
            gate,
            "channel_decision",
            "exactly_two_platforms_required",
            "channel decision must name exactly two platforms",
            observed=len(normalized),
            threshold=2,
        )
        return None
    if normalized[0] == normalized[1]:
        audit.fail(
            gate,
            "channel_decision",
            "platforms_must_differ",
            "primary and secondary platforms must be different",
        )
        return None
    excluded = decision.get("excluded_surfaces")
    if not isinstance(excluded, list) or any(
        not isinstance(item, str) or not item.strip() for item in excluded
    ):
        audit.fail(
            gate,
            "channel_decision.excluded_surfaces",
            "excluded_surfaces_invalid",
            "channel decision requires an explicit excluded-surface list",
        )
    elif set(normalized) & {item.strip().casefold() for item in excluded}:
        audit.fail(
            gate,
            "channel_decision.excluded_surfaces",
            "selected_surface_is_excluded",
            "a selected platform cannot also be excluded",
        )
    _required_alias_text(
        decision,
        ("reason",),
        audit,
        gate,
        "channel_decision",
        minimum=20,
    )
    return normalized[0], normalized[1]


def _asset_text(asset: Mapping[str, Any]) -> str:
    fields = (
        "hook",
        "headline",
        "body",
        "full_copy",
        "copy",
        "caption",
        "script",
        "cta",
        "proof_and_limitation",
    )
    return "\n".join(str(asset[name]).strip() for name in fields if isinstance(asset.get(name), str))


def _jaccard(left: str, right: str) -> float:
    left_tokens = set(_TOKEN.findall(left.casefold()))
    right_tokens = set(_TOKEN.findall(right.casefold()))
    if not left_tokens and not right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def _platform_assets(
    candidate: Mapping[str, Any],
    audit: _Audit,
    selected: tuple[str, str] | None,
) -> list[Mapping[str, Any]]:
    contract_gate = "platform_asset_contract"
    binding_gate = "channel_surface_binding"
    diversity_gate = "cross_asset_diversity"
    audit.check(contract_gate)
    audit.check(diversity_gate)
    raw = candidate.get("platform_assets")
    if not isinstance(raw, list) or len(raw) != 2 or any(not isinstance(row, Mapping) for row in raw):
        audit.fail(
            contract_gate,
            "platform_assets",
            "exactly_two_platform_assets_required",
            "platform_assets must contain exactly two objects",
            observed=len(raw) if isinstance(raw, list) else None,
            threshold=2,
        )
        return []
    assets = list(raw)
    observed_platforms: list[str] = []
    for index, asset in enumerate(assets):
        prefix = f"platform_assets[{index}]"
        platform = _required_alias_text(
            asset,
            ("platform", "surface_id", "channel"),
            audit,
            contract_gate,
            prefix,
            minimum=1,
        )
        if platform:
            observed_platforms.append(platform.casefold())
        _required_alias_text(
            asset,
            ("native_format",),
            audit,
            contract_gate,
            prefix,
            minimum=12,
        )
        _required_alias_text(
            asset,
            ("audience_state",),
            audit,
            contract_gate,
            prefix,
            minimum=20,
        )
        _required_alias_text(asset, ("hook", "headline"), audit, contract_gate, prefix, minimum=12)
        _required_alias_text(
            asset,
            ("full_copy", "body", "copy", "caption", "script"),
            audit,
            contract_gate,
            prefix,
            minimum=60,
        )
        _required_alias_text(asset, ("cta",), audit, contract_gate, prefix, minimum=8)
        _required_alias_text(
            asset,
            ("participation", "participation_mechanism"),
            audit,
            contract_gate,
            prefix,
            minimum=20,
        )
        _required_alias_text(
            asset,
            ("proof_and_limitation",),
            audit,
            contract_gate,
            prefix,
            minimum=20,
        )
        _required_alias_text(
            asset,
            ("event_name",),
            audit,
            contract_gate,
            prefix,
            minimum=6,
        )
    if selected is not None and sorted(observed_platforms) != sorted(selected):
        audit.fail(
            binding_gate,
            "platform_assets[*].platform",
            "assets_do_not_match_channel_decision",
            "the two asset platforms must exactly match the channel decision",
            observed=sorted(observed_platforms),
            threshold=sorted(selected),
        )
    if len(assets) == 2:
        score = _jaccard(_asset_text(assets[0]), _asset_text(assets[1]))
        if score > MAX_CROSS_ASSET_JACCARD:
            audit.fail(
                diversity_gate,
                "platform_assets",
                "cross_asset_language_too_similar",
                "the two platform assets are insufficiently differentiated",
                observed=round(score, 6),
                threshold=MAX_CROSS_ASSET_JACCARD,
            )
    return assets


def _email(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "email_contract"
    email = _mapping(candidate.get("email"), audit, gate, "email")
    if email is None:
        return
    for aliases, minimum in (
        (("trigger",), 20),
        (("delay",), 3),
        (("segment",), 20),
    ):
        _required_alias_text(email, aliases, audit, gate, "email", minimum=minimum)
    _required_alias_text(email, ("subject",), audit, gate, "email", minimum=8, maximum=80)
    _required_alias_text(
        email,
        ("preview_text", "preview"),
        audit,
        gate,
        "email",
        minimum=12,
        maximum=160,
    )
    _required_alias_text(email, ("body",), audit, gate, "email", minimum=80)
    _required_alias_text(email, ("cta",), audit, gate, "email", minimum=8)
    _required_alias_text(email, ("suppression",), audit, gate, "email", minimum=20)
    _required_alias_text(email, ("exit",), audit, gate, "email", minimum=20)


def _seo(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "seo_contract"
    page = _mapping(candidate.get("seo_page"), audit, gate, "seo_page")
    if page is None:
        return
    _required_alias_text(page, ("query",), audit, gate, "seo_page", minimum=8)
    slug = _required_alias_text(page, ("slug",), audit, gate, "seo_page", minimum=3, maximum=80)
    if slug and not _SLUG.fullmatch(slug):
        audit.fail(gate, "seo_page.slug", "invalid_slug", "slug must be lowercase kebab-case")
    _required_alias_text(page, ("title",), audit, gate, "seo_page", minimum=15, maximum=70)
    _required_alias_text(
        page,
        ("meta_description", "meta"),
        audit,
        gate,
        "seo_page",
        minimum=50,
        maximum=170,
    )
    _required_alias_text(page, ("hero",), audit, gate, "seo_page", minimum=8)
    outline = page.get("outline")
    if not isinstance(outline, list) or len(outline) < 3:
        audit.fail(
            gate,
            "seo_page.outline",
            "outline_too_shallow",
            "SEO outline requires at least three sections",
            observed=len(outline) if isinstance(outline, list) else None,
            threshold=3,
        )
    else:
        for index, item in enumerate(outline):
            value = item.get("heading") if isinstance(item, Mapping) else item
            _text(value, audit, gate, f"seo_page.outline[{index}]", minimum=6)
    _, schema_value = _first(
        page,
        ("schema_types", "schema_markup", "structured_data", "schema"),
    )
    if not isinstance(schema_value, (Mapping, list)) or not schema_value:
        audit.fail(
            gate,
            "seo_page.schema_markup",
            "structured_data_missing",
            "SEO page requires non-empty structured data",
        )
    links = page.get("internal_links")
    if not isinstance(links, list) or len(links) < 2:
        audit.fail(
            gate,
            "seo_page.internal_links",
            "internal_links_missing",
            "SEO page requires at least two internal links",
            observed=len(links) if isinstance(links, list) else None,
            threshold=2,
        )
    else:
        normalized: list[str] = []
        for index, item in enumerate(links):
            if isinstance(item, Mapping):
                _, item = _first(item, ("href", "url", "path"))
            value = _text(item, audit, gate, f"seo_page.internal_links[{index}]", minimum=2)
            if value:
                normalized.append(value)
        if len(set(normalized)) != len(normalized):
            audit.fail(gate, "seo_page.internal_links", "duplicate_internal_links", "internal links must be distinct")
    _required_alias_text(page, ("cta",), audit, gate, "seo_page", minimum=8)
    _required_alias_text(
        page,
        ("rejection_condition",),
        audit,
        gate,
        "seo_page",
        minimum=20,
    )


def _geo(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "geo_contract"
    answer = _mapping(candidate.get("geo_answer"), audit, gate, "geo_answer")
    if answer is None:
        return
    _required_alias_text(answer, ("question", "query"), audit, gate, "geo_answer", minimum=12)
    _required_alias_text(answer, ("answer", "direct_answer"), audit, gate, "geo_answer", minimum=80)
    _required_alias_text(
        answer,
        ("entity_statement",),
        audit,
        gate,
        "geo_answer",
        minimum=20,
    )
    _required_alias_text(
        answer,
        ("proof_and_limitation", "evidence_boundary"),
        audit,
        gate,
        "geo_answer",
        minimum=20,
    )
    _, sources = _first(answer, ("required_sources", "sources"))
    if not isinstance(sources, list) or len(sources) < 2:
        audit.fail(
            gate,
            "geo_answer.sources",
            "geo_sources_missing",
            "GEO answer requires at least two located sources",
            observed=len(sources) if isinstance(sources, list) else None,
            threshold=2,
        )
        return
    for index, source in enumerate(sources):
        path = f"geo_answer.sources[{index}]"
        if isinstance(source, Mapping):
            _required_alias_text(source, ("title", "source_id", "name"), audit, gate, path, minimum=3)
            _required_alias_text(
                source,
                ("locator", "url", "evidence_uri", "source"),
                audit,
                gate,
                path,
                minimum=8,
            )
        else:
            _text(source, audit, gate, path, minimum=8)
    _required_alias_text(answer, ("nonfit",), audit, gate, "geo_answer", minimum=20)
    _required_alias_text(answer, ("cta",), audit, gate, "geo_answer", minimum=8)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _video(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "video_timeline_contract"
    video = _mapping(candidate.get("video_script"), audit, gate, "video_script")
    if video is None:
        return
    duration = _number(video.get("duration_seconds"))
    if duration is None or abs(duration - 15.0) > 1e-9:
        audit.fail(
            gate,
            "video_script.duration_seconds",
            "video_duration_not_15_seconds",
            "video duration must be exactly 15 seconds",
            observed=duration,
            threshold=15,
        )
    shots = video.get("shots")
    if not isinstance(shots, list) or len(shots) != 3 or any(not isinstance(row, Mapping) for row in shots):
        audit.fail(
            gate,
            "video_script.shots",
            "exactly_three_shots_required",
            "video script must contain exactly three shot objects",
            observed=len(shots) if isinstance(shots, list) else None,
            threshold=3,
        )
        return
    timeline: list[tuple[float, float]] = []
    for index, shot in enumerate(shots):
        prefix = f"video_script.shots[{index}]"
        _, start_raw = _first(shot, ("start_second", "start", "start_seconds"))
        _, end_raw = _first(shot, ("end_second", "end", "end_seconds"))
        start, end = _number(start_raw), _number(end_raw)
        if start is None or end is None or start >= end:
            audit.fail(gate, prefix, "invalid_shot_interval", "each shot requires a finite increasing interval")
        else:
            timeline.append((start, end))
        _required_alias_text(shot, ("visual", "visual_direction"), audit, gate, prefix, minimum=20)
        _required_alias_text(shot, ("voiceover", "audio", "dialogue"), audit, gate, prefix, minimum=10)
        _required_alias_text(shot, ("caption",), audit, gate, prefix, minimum=6)
        _required_alias_text(shot, ("acceptance_test",), audit, gate, prefix, minimum=20)
    if len(timeline) == 3:
        contiguous = (
            abs(timeline[0][0]) <= 1e-9
            and abs(timeline[-1][1] - 15.0) <= 1e-9
            and all(abs(timeline[index][1] - timeline[index + 1][0]) <= 1e-9 for index in range(2))
        )
        if not contiguous:
            audit.fail(
                gate,
                "video_script.shots",
                "timeline_not_contiguous_0_to_15",
                "three shots must continuously and exactly cover seconds 0 through 15",
                observed=[[start, end] for start, end in timeline],
                threshold=[[0, "continuous"], ["continuous", "continuous"], ["continuous", 15]],
            )


def _experiment(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "experiment_contract"
    experiment = _mapping(candidate.get("experiment"), audit, gate, "experiment")
    if experiment is None:
        return
    _required_alias_text(experiment, ("hypothesis",), audit, gate, "experiment", minimum=20)
    _required_alias_text(
        experiment,
        ("primary_metric",),
        audit,
        gate,
        "experiment",
        minimum=5,
    )
    numerator = _required_alias_text(experiment, ("numerator",), audit, gate, "experiment", minimum=5)
    denominator = _required_alias_text(experiment, ("denominator",), audit, gate, "experiment", minimum=5)
    if numerator and denominator and numerator.casefold() == denominator.casefold():
        audit.fail(gate, "experiment", "numerator_equals_denominator", "numerator and denominator must differ")
    baseline = experiment.get("baseline")
    if baseline is None or baseline == "" or baseline == {} or baseline == []:
        audit.fail(gate, "experiment.baseline", "baseline_missing", "experiment requires a frozen baseline")
    _, sample = _first(
        experiment,
        ("minimum_sample", "min_sample", "sample_floor", "minimum_sample_rule"),
    )
    sample_is_valid = (
        type(sample) is int and sample > 0
    ) or (
        isinstance(sample, str)
        and len(sample.strip()) >= 20
        and any(int(match) > 0 for match in re.findall(r"\b\d+\b", sample))
    )
    if not sample_is_valid:
        audit.fail(
            gate,
            "experiment.minimum_sample_rule",
            "minimum_sample_invalid",
            "minimum sample must be a positive integer or a rule containing a positive numeric floor",
        )
    _required_alias_text(experiment, ("success_rule",), audit, gate, "experiment", minimum=20)
    _required_alias_text(experiment, ("kill_rule", "stop_rule"), audit, gate, "experiment", minimum=20)
    if experiment.get("causal_claim_allowed") is not False:
        audit.fail(
            gate,
            "experiment.causal_claim_allowed",
            "causal_claim_must_remain_false",
            "a candidate-generation experiment cannot claim causal effect",
            observed=experiment.get("causal_claim_allowed"),
            threshold=False,
        )


def _iter_strings(value: object, path: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            rows.extend(_iter_strings(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_iter_strings(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        rows.append((path, value))
    return rows


def _negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 180) : start].casefold()
    clause = re.split(r"[\n.!?;。！？；]", prefix)[-1]
    return any(marker in clause for marker in _NEGATIONS)


def _forbidden_claims(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "forbidden_effect_claims"
    audit.check(gate)
    public_sections = {
        key: candidate.get(key)
        for key in (
            "campaign_system",
            "platform_assets",
            "email",
            "seo_page",
            "geo_answer",
            "video_script",
        )
    }
    seen: set[tuple[str, str]] = set()
    for path, text in _iter_strings(public_sections):
        if path.endswith(
            (
                ".suppression",
                ".exit",
                ".rejection_condition",
                ".nonfit",
                ".falsifier",
            )
        ):
            # These fields state explicit prohibitions/stop conditions rather than claims.
            continue
        for code, pattern in _FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                if _negated(text, match.start()):
                    continue
                key = (path, code)
                if key in seen:
                    continue
                seen.add(key)
                audit.fail(
                    gate,
                    path,
                    code,
                    "candidate contains a prohibited guarantee, Top-1, 4A, viral, or revenue-effect claim",
                    observed=match.group(0)[:120],
                    threshold=0,
                )


def _proof_binding(
    candidate: Mapping[str, Any],
    approved_claim: str | None,
    audit: _Audit,
) -> None:
    gate = "approved_claim_exact_binding"
    audit.check(gate)
    if not approved_claim:
        return
    locations: list[str] = []
    system = candidate.get("campaign_system")
    if isinstance(system, Mapping) and isinstance(system.get("proof_spine"), str):
        locations.append(system["proof_spine"])
    for path, text in _iter_strings(candidate):
        if path.endswith("proof_and_limitation"):
            locations.append(text)
    if not any(approved_claim in text for text in locations):
        audit.fail(
            gate,
            "campaign_system.proof_spine|*.proof_and_limitation",
            "approved_claim_not_present_verbatim",
            "the approved claim must appear verbatim in proof_spine or proof_and_limitation",
            threshold=approved_claim,
        )


def _release_and_authority(candidate: Mapping[str, Any], audit: _Audit) -> None:
    state_gate = "release_state_pending"
    authority_gate = "authority_effect_boundary"
    audit.check(state_gate)
    audit.check(authority_gate)
    states: list[tuple[str, object]] = []
    if "release_state" in candidate:
        states.append(("release_state", candidate.get("release_state")))
    assets = candidate.get("platform_assets")
    if isinstance(assets, list):
        states.extend(
            (f"platform_assets[{index}].release_state", asset.get("release_state"))
            for index, asset in enumerate(assets)
            if isinstance(asset, Mapping)
        )
    if len(states) < 2:
        audit.fail(
            state_gate,
            "platform_assets[*].release_state",
            "release_state_missing",
            "each platform asset must declare a pending human-review release state",
        )
    for path, state in states:
        if not isinstance(state, str) or state not in _PENDING_RELEASE_STATES:
            audit.fail(
                state_gate,
                path,
                "release_state_not_pending",
                "candidate release state must remain pending human review",
                observed=state,
                threshold=sorted(_PENDING_RELEASE_STATES),
            )

    def walk(value: object, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                if key in _AUTHORITY_EFFECT_FIELDS:
                    valid = item is False or (type(item) in {int, float} and item == 0)
                    if not valid:
                        audit.fail(
                            authority_gate,
                            child,
                            "authority_or_effect_leak",
                            "authority and effect fields must remain false or zero",
                            observed=item,
                            threshold="false_or_zero",
                        )
                walk(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(candidate)


def _top_level(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "top_level_and_compiler_binding"
    audit.check(gate)
    for key in _REQUIRED_TOP_LEVEL:
        if key not in candidate:
            audit.fail(gate, key, "required_field_missing", f"required top-level field is missing: {key}")
    _text(candidate.get("schema"), audit, gate, "schema", minimum=8)
    _text(candidate.get("work_order_id"), audit, gate, "work_order_id", minimum=8)
    for key in ("work_order_sha256", "protocol_sha256"):
        value = candidate.get(key)
        if not isinstance(value, str) or not _DIGEST.fullmatch(value):
            audit.fail(gate, key, "compiler_digest_invalid", f"{key} must be a lowercase SHA-256 digest")


def _truth_boundary(candidate: Mapping[str, Any], audit: _Audit) -> None:
    gate = "truth_boundary_contract"
    text = _text(candidate.get("truth_boundary"), audit, gate, "truth_boundary", minimum=40)
    if text is not None:
        folded = text.casefold()
        if not any(
            marker in folded
            for marker in (
                "does not prove",
                "not evidence",
                "unproven",
                "not approved",
                "not authorized",
                "not publishable",
                "no verified effect",
                "no market effect",
                "no production effect",
                "remain incomplete",
                "不证明",
                "未证明",
                "未获批准",
            )
        ):
            audit.fail(
                gate,
                "truth_boundary",
                "truth_boundary_lacks_nonproof_marker",
                "truth boundary must explicitly state what the candidate does not prove",
            )


def compile_codex_candidate_quality_audit(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Run the fail-closed Level-1 audit over one bound Codex campaign candidate."""

    if not isinstance(candidate, Mapping):
        raise CodexCandidateQualityError("candidate must be an object")
    audit = _Audit()
    computed_candidate_sha256 = candidate_content_sha256(candidate)
    supplied_candidate_sha256 = candidate.get("content_sha256")
    audit.check("candidate_digest")
    if supplied_candidate_sha256 is not None and supplied_candidate_sha256 != computed_candidate_sha256:
        audit.fail(
            "candidate_digest",
            "content_sha256",
            "candidate_digest_mismatch",
            "candidate content digest is invalid",
            observed=supplied_candidate_sha256,
            threshold=computed_candidate_sha256,
        )

    _top_level(candidate, audit)
    _selector(candidate, audit)
    approved_claim = _approved_claim(candidate, audit)
    _campaign_system(candidate, audit)
    selected = _selected_platforms(candidate, audit)
    _platform_assets(candidate, audit, selected)
    _email(candidate, audit)
    _seo(candidate, audit)
    _geo(candidate, audit)
    _video(candidate, audit)
    _experiment(candidate, audit)
    _proof_binding(candidate, approved_claim, audit)
    _forbidden_claims(candidate, audit)
    _release_and_authority(candidate, audit)
    _truth_boundary(candidate, audit)

    failures = sorted(
        audit.failures,
        key=lambda row: (row["gate_id"], row["path"], row["code"]),
    )
    passed = not failures
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "candidate_sha256": computed_candidate_sha256,
        "candidate_supplied_digest_present": supplied_candidate_sha256 is not None,
        "work_order_id": candidate.get("work_order_id"),
        "work_order_sha256": candidate.get("work_order_sha256"),
        "protocol_sha256": candidate.get("protocol_sha256"),
        "level_1": {
            "deterministic": True,
            "passed": passed,
            "gate_count": len(audit.gates),
            "critical_failure_count": len(failures),
            "located_failures": failures,
            "gate_checks": audit.gate_checks(),
        },
        "located_failures": failures,
        "gate_checks": audit.gate_checks(),
        "failure_count": len(failures),
        "passed": passed,
        "status": "passed_level_1_pending_human_review" if passed else "rejected_fail_closed",
        "release_state": "pending_human_review",
        "release_eligible": False,
        "human_preference_observed": False,
        "model_critic_vote_counted_in_preference": False,
        "model_critic_promotion_authority": False,
        "automatic_publish_enabled": False,
        "automatic_send_enabled": False,
        "automatic_spend_enabled": False,
        "external_publish_executed": False,
        "external_action_count": 0,
        "production_effect_observed": False,
        "causal_effect_claim_allowed": False,
        "causal_revenue_effect_proven": False,
        "four_a_quality_proven": False,
        "top1_claim_eligible": False,
        "eval_plan": compile_codex_candidate_eval_plan(),
        "truth_boundary": (
            "A passing receipt proves only deterministic Level-1 structure, grounding, "
            "platform differentiation, experiment, and authority-boundary checks for one "
            "content-addressed candidate. It does not prove human preference, publication, "
            "4A quality, Top-1 standing, virality, production effect, conversion, revenue, "
            "causal lift, or named-product superiority."
        ),
    }
    return _seal(payload)


def verify_codex_candidate_quality_audit(
    receipt: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping) or receipt.get("schema") != SCHEMA:
        raise CodexCandidateQualityError("candidate quality receipt schema is invalid")
    unsigned = dict(receipt)
    supplied = unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or not _DIGEST.fullmatch(supplied) or sha256_json(unsigned) != supplied:
        raise CodexCandidateQualityError("candidate quality receipt digest is invalid")
    level_1 = receipt.get("level_1")
    if not isinstance(level_1, Mapping):
        raise CodexCandidateQualityError("candidate quality Level-1 receipt is missing")
    failures = level_1.get("located_failures")
    if (
        not isinstance(failures, list)
        or receipt.get("passed") is not (len(failures) == 0)
        or level_1.get("passed") is not receipt.get("passed")
        or level_1.get("critical_failure_count") != len(failures)
        or receipt.get("located_failures") != failures
        or receipt.get("failure_count") != len(failures)
        or receipt.get("gate_checks") != level_1.get("gate_checks")
        or receipt.get("release_state") != "pending_human_review"
    ):
        raise CodexCandidateQualityError("candidate quality verdict is inconsistent")
    false_fields = (
        "release_eligible",
        "human_preference_observed",
        "model_critic_vote_counted_in_preference",
        "model_critic_promotion_authority",
        "automatic_publish_enabled",
        "automatic_send_enabled",
        "automatic_spend_enabled",
        "external_publish_executed",
        "production_effect_observed",
        "causal_effect_claim_allowed",
        "causal_revenue_effect_proven",
        "four_a_quality_proven",
        "top1_claim_eligible",
    )
    if any(receipt.get(field) is not False for field in false_fields) or receipt.get("external_action_count") != 0:
        raise CodexCandidateQualityError("candidate quality receipt leaked authority or effect")
    if receipt.get("eval_plan") != compile_codex_candidate_eval_plan():
        raise CodexCandidateQualityError("candidate quality eval plan drifted")
    if candidate is not None:
        expected = compile_codex_candidate_quality_audit(candidate)
        if canonical_json_bytes(expected) != canonical_json_bytes(receipt):
            raise CodexCandidateQualityError("candidate quality receipt is not bound to candidate")
    return dict(receipt)


# Concise aliases for callers that treat the Level-1 audit as a pure evaluator.
audit_codex_candidate_quality = compile_codex_candidate_quality_audit
canonical_digest = sha256_json
compile_candidate_quality_audit = compile_codex_candidate_quality_audit
verify_candidate_quality_audit = verify_codex_candidate_quality_audit


__all__ = [
    "CRITIC_IDS",
    "MAX_CROSS_ASSET_JACCARD",
    "SCHEMA",
    "CodexCandidateQualityError",
    "audit_codex_candidate_quality",
    "candidate_content_sha256",
    "canonical_digest",
    "canonical_json_bytes",
    "compile_codex_candidate_eval_plan",
    "compile_codex_candidate_quality_audit",
    "compile_candidate_quality_audit",
    "sha256_json",
    "verify_candidate_quality_audit",
    "verify_codex_candidate_quality_audit",
]
