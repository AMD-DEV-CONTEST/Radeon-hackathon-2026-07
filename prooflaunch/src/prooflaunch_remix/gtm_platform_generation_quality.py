from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from itertools import combinations
from typing import Any, Mapping, Sequence

from .gtm_platform_native_challenger import (
    EXPECTED_SURFACE_COUNT,
    SURFACE_GENERATION_BLUEPRINTS,
    adapt_platform_native_candidate,
    candidate_failures,
    canonical_json,
    extract_first_json_object,
    verify_platform_native_challenger_plan,
    verify_platform_native_receipt,
)
from .gtm_platform_native_publication_audit import publication_failures


SCHEMA = "ProofLaunchPlatformGenerationQualityAuditV1"
TRACE_AUDIT_SCHEMA = "ProofLaunchPlatformGenerationTraceAuditV1"


class GTMPlatformGenerationQualityError(ValueError):
    """A pre-human platform craft audit is incomplete, unbound, or overclaimed."""


ABSTRACT_COPY_PATTERNS = (
    re.compile(r"\bimagine\b", re.I),
    re.compile(r"\bwhat if\b", re.I),
    re.compile(r"\btired of\b", re.I),
    re.compile(r"\bshare your\b", re.I),
    re.compile(r"\breflect on\b", re.I),
    re.compile(r"\bwe(?:'|’)re building\b", re.I),
    re.compile(r"\baims? to\b", re.I),
    re.compile(r"\bever wonder\b", re.I),
    re.compile(r"\b(?:visibility|transparency|confidence|alignment)\b", re.I),
)

VAGUE_THRESHOLD_PATTERNS = (
    re.compile(r"\bpre[- ]?(?:registered|defined) (?:threshold|baseline|benchmark)\b", re.I),
    re.compile(r"\b(?:below|above) \d+(?:\.\d+)?%", re.I),
    re.compile(r"\bmeasurable (?:improvement|increase|lift|change)\b", re.I),
    re.compile(r"\b(?:increase|improve|lift|rate)\b", re.I),
    re.compile(r"\bwithin \d+ (?:hours?|days?|weeks?|months?)\b", re.I),
)

UNVERIFIED_PRODUCT_DETAIL_PATTERNS = (
    re.compile(r"\bversion\s+\d", re.I),
    re.compile(r"\bnow supports?\b", re.I),
    re.compile(r"\binitial (?:testing|tests?) (?:shows?|reveals?|found)\b", re.I),
    re.compile(r"\b(?:generates?|provides?|includes?) (?:a |an |the )?(?:source map|confidence score|timestamps?)\b", re.I),
    re.compile(r"\bintegrat(?:es?|ion) with \[", re.I),
)

FABRICATED_ANECDOTE_PATTERNS = (
    re.compile(r"\bi (?:recently |just )?(?:rejected|approved|ran|tested|saw|found|reviewed)\b", re.I),
    re.compile(r"\bwe (?:recently|just|spent)\b", re.I),
    re.compile(r"\b(?:a|the) previous (?:post|campaign|launch|test|draft)\b", re.I),
    re.compile(r"\b(?:was|were) flagged internally\b", re.I),
    re.compile(r"\bq[1-4]\s+20\d{2}\b", re.I),
    re.compile(r"\bcompetitor [a-z](?:'s)?\b", re.I),
    re.compile(r"\bsales rep anecdote\b", re.I),
)

UNSUPPORTED_EFFECT_LANGUAGE_PATTERNS = (
    re.compile(r"\b(?:safeguards?|minimi[sz](?:e|es|ed|ing)|fosters?|promotes?|reshapes?)\b", re.I),
    re.compile(r"\bmore (?:predictable|accountable|efficient|effective|reliable)\b", re.I),
    re.compile(r"\b(?:predictable|accountable) execution cycle\b", re.I),
)

DANGLING_CONTENT_REFERENCE_PATTERNS = (
    re.compile(r"\b(?:the )?two responses (?:presented|provided)? ?below\b", re.I),
    re.compile(r"\bcompare (?:the )?two (?:responses|examples|versions)\b", re.I),
    re.compile(r"\b(?:example|response|asset) (?:presented|provided) below\b", re.I),
)

SYNTHETIC_SCENARIO_SIGNAL_PATTERNS = (
    re.compile(r"\bpath a\b.*\bpath b\b", re.I | re.S),
    re.compile(r"\bconsider a scenario\b", re.I),
    re.compile(r"\bassumes? .{0,80}\b(?:is|are) deployed\b", re.I),
    re.compile(r"\bhypothetical(?:ly)?\b", re.I),
    re.compile(r"\bcomposite (?:case|example|demo)\b", re.I),
)

SYNTHETIC_SCENARIO_LABELS = (
    "synthetic scenario",
    "hypothetical",
    "composite demo",
)

GENERIC_ORGANIZING_IDEA_PATTERNS = (
    re.compile(r"^(?:autonomous |ai )?gtm\b", re.I),
    re.compile(r"\b(?:workflow|validation|governance|traceability)\b", re.I),
)

PARTICIPATION_ACTIONS = (
    "apply",
    "audit",
    "choose",
    "compare",
    "evaluate",
    "inspect",
    "label",
    "map",
    "mark",
    "observe",
    "rewrite",
    "route",
    "score",
    "test",
    "trace",
)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _public_text(candidate: Mapping[str, Any]) -> str:
    blocks: list[str] = []
    for field in (
        "campaign_platform",
        "hook",
        "progression",
        "body",
        "cta",
        "participation_mechanism",
        "proof_integration",
        "falsifier",
    ):
        value = candidate.get(field)
        if isinstance(value, str):
            blocks.append(value)
        elif isinstance(value, list):
            blocks.extend(str(item) for item in value)
    return "\n".join(blocks)


def _non_proof_segments(candidate: Mapping[str, Any]) -> list[str]:
    segments: list[str] = []
    for field in (
        "campaign_platform",
        "hook",
        "progression",
        "body",
        "cta",
        "participation_mechanism",
        "falsifier",
    ):
        value = candidate.get(field)
        if isinstance(value, str):
            segments.append(value)
        elif isinstance(value, list):
            segments.extend(str(item) for item in value)
    return segments


def _unbound_product_reference_present(
    candidate: Mapping[str, Any], *, plan: Mapping[str, Any], surface_id: str
) -> bool:
    product_name = str(plan["brief"]["product_name"]).casefold()
    anchors = (
        "approved evidence",
        "generation",
        "review",
        "activation preparation",
        "learning",
        "automatic external release",
    )
    for segment in _non_proof_segments(candidate):
        folded = segment.casefold()
        if "approved product fact" in folded:
            neutral_fact_object = any(
                marker in folded
                for marker in (
                    "connect the approved product fact",
                    "bind text evidence to the exact approved product fact",
                    "place the approved product fact",
                    "separate the approved product fact",
                    "approved product fact supports asset preparation only",
                    "approved product fact, editorial inference",
                    "approved product fact, generated artifact",
                    "approved product fact may enter",
                )
            )
            if not neutral_fact_object:
                return True
        product_signal = (
            product_name in folded
            or "cortex-x" in folded
            or re.search(
                r"\b(?:this|the|a) governed (?:system|multimodal gtm employee)\b|\b(?:this|the) system\b",
                folded,
            )
            is not None
        )
        if not product_signal:
            continue
        anchor_count = sum(anchor in folded for anchor in anchors)
        exact_truth_supported = anchor_count >= 5
        neutral_entity_reference = any(
            marker in folded
            for marker in (
                "under evaluation",
                "presented as the governed product",
            )
        )
        explicit_limitation = any(
            marker in folded
            for marker in (
                "does not establish",
                "does not support",
                "does not prove",
                "remain unobserved",
                "remains unobserved",
                "no production effect observed",
            )
        )
        disclosed_affiliation = surface_id == "reddit" and any(
            marker in folded for marker in ("we built", "affiliation:", "product team")
        )
        governed_boundary = (
            "governed multimodal gtm employee" in folded
            and "automatic external release" in folded
            and explicit_limitation
        )
        if not (
            exact_truth_supported
            or neutral_entity_reference
            or explicit_limitation
            or disclosed_affiliation
            or governed_boundary
        ):
            return True
    return False


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _word_count(value: str) -> int:
    return len(re.findall(r"[a-z0-9]+", value.casefold()))


def _jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def generation_quality_failures(
    candidate: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    request: Mapping[str, Any],
    capability_reference_only: bool = False,
) -> tuple[str, ...]:
    publication_blockers = list(
        publication_failures(candidate, plan=plan, request=request)
    )
    if capability_reference_only:
        if (
            plan.get("business_model") != "b2c"
            or "synthetic benchmark"
            not in str(plan.get("brief", {}).get("product_truth", "")).casefold()
        ):
            raise GTMPlatformGenerationQualityError(
                "capability-reference mode requires the frozen synthetic B2C benchmark"
            )
        publication_blockers = [
            failure
            for failure in publication_blockers
            if failure != "synthetic_benchmark_is_not_publishable_product_content"
        ]
    failures: list[str] = publication_blockers
    surface_id = str(request["surface_id"])
    blueprint = SURFACE_GENERATION_BLUEPRINTS[surface_id]
    body = candidate.get("body")
    if not isinstance(body, list):
        return ("body_is_not_a_platform_blueprint_array",)
    normalized_body = [str(block).strip().casefold() for block in body]
    missing_markers = [
        marker
        for marker in blueprint["body_markers"]
        if not any(block.startswith(str(marker).casefold()) for block in normalized_body)
    ]
    if missing_markers:
        failures.append("missing_surface_blueprint_markers:" + "|".join(missing_markers))
    text = _public_text(candidate)
    if _unbound_product_reference_present(
        candidate, plan=plan, surface_id=surface_id
    ):
        failures.append("product_reference_adds_claim_outside_frozen_truth")
    for pattern in ABSTRACT_COPY_PATTERNS:
        if pattern.search(text):
            failures.append("abstract_or_generic_craft:" + pattern.pattern)
    if any(pattern.search(text) for pattern in UNVERIFIED_PRODUCT_DETAIL_PATTERNS):
        failures.append("unverified_product_feature_or_result")
    fabricated_without_disclosure = False
    for segment in _non_proof_segments(candidate):
        folded_segment = segment.casefold()
        for pattern in FABRICATED_ANECDOTE_PATTERNS:
            match = pattern.search(segment)
            if match and not any(
                label in folded_segment[: match.start()]
                for label in SYNTHETIC_SCENARIO_LABELS
            ):
                fabricated_without_disclosure = True
                break
        if fabricated_without_disclosure:
            break
    if fabricated_without_disclosure:
        failures.append("unbound_first_person_or_timeline_anecdote")
    if any(pattern.search(text) for pattern in UNSUPPORTED_EFFECT_LANGUAGE_PATTERNS):
        failures.append("unsupported_effect_language_outside_frozen_truth")
    if any(pattern.search(text) for pattern in DANGLING_CONTENT_REFERENCE_PATTERNS):
        folded_text = text.casefold()
        response_pair_present = (
            ("response a:" in folded_text and "response b:" in folded_text)
            or ("path a" in folded_text and "path b" in folded_text)
        )
        if not response_pair_present:
            failures.append("artifact_references_content_that_is_not_present")
    if any(pattern.search(text) for pattern in SYNTHETIC_SCENARIO_SIGNAL_PATTERNS) and not any(
        label in text.casefold() for label in SYNTHETIC_SCENARIO_LABELS
    ):
        failures.append("synthetic_capability_scenario_disclosure_missing")
    campaign_platform = str(candidate.get("campaign_platform", "")).strip()
    if any(pattern.search(campaign_platform) for pattern in GENERIC_ORGANIZING_IDEA_PATTERNS):
        failures.append("organizing_idea_is_a_generic_category_label")
    hook = str(candidate.get("hook", "")).strip()
    minimum_hook_words = 5 if surface_id in {"tiktok", "x", "copilot_answers"} else 8
    if _word_count(hook) < minimum_hook_words:
        failures.append("hook_is_too_thin_to_carry_a_distinct_thesis")
    edge_hook = str(request["edge_play"]["non_consensus_hook"])
    if _jaccard(hook, edge_hook) > 0.72:
        failures.append("hook_copies_the_strategy_card_instead_of_writing_the_artifact")
    if hook.endswith("?") and surface_id not in {"google_search", "bing_search", "chatgpt_answers"}:
        failures.append("question_hook_avoids_a_decisive_thesis")
    if sum("?" in block for block in [hook, *map(str, body)]) > 1:
        failures.append("question_stack_replaces_progression")
    progression = candidate.get("progression")
    if isinstance(progression, list) and any(
        _word_count(str(beat)) < 7 for beat in progression
    ):
        failures.append("progression_beat_is_a_label_not_an_editorial_move")
    default_body_words = 10 if surface_id in {"tiktok", "instagram", "x", "copilot_answers"} else 14

    def minimum_words_for_block(block: str) -> int:
        folded = block.strip().casefold()
        if folded.startswith("updated:"):
            return 5
        if folded.startswith("title:"):
            return 8
        if folded.startswith(("thumbnail:", "chapter:", "question:")):
            return 10
        return default_body_words

    if any(
        _word_count(block) < minimum_words_for_block(block)
        for block in map(str, body)
    ):
        failures.append("body_block_is_too_thin_for_direct_production")
    if str(candidate.get("cta", "")).strip() == str(plan["brief"]["offer"]).strip():
        failures.append("cta_copies_frozen_offer_instead_of_translating_surface_action")
    if str(candidate.get("proof_integration", "")).strip() != str(
        plan["brief"]["approved_claim"]
    ).strip():
        failures.append("proof_integration_contains_unapproved_editorial_wrapper")
    falsifier = str(candidate.get("falsifier", ""))
    if any(pattern.search(falsifier) for pattern in VAGUE_THRESHOLD_PATTERNS):
        failures.append("falsifier_uses_unbound_or_vague_threshold")
    if _word_count(falsifier) < 14 or not any(
        marker in falsifier.casefold()
        for marker in ("cannot", "fails", "does not", "no longer", "contradicts", "stop")
    ):
        failures.append("falsifier_lacks_a_specific_observable_stop_condition")
    participation = str(candidate.get("participation_mechanism", "")).strip()
    if _word_count(participation) < 12 or not any(
        re.search(rf"\b{action}\b", participation, re.I)
        for action in PARTICIPATION_ACTIONS
    ):
        failures.append("participation_is_not_a_self_contained_user_action")
    cta = str(candidate.get("cta", "")).strip()
    if _jaccard(cta, participation) > 0.9:
        failures.append("cta_duplicates_participation_instead_of_advancing_the_offer")
    if surface_id == "tiktok":
        tiktok_max_words = {
            "0:00 visual:": 32,
            "0:02 vo:": 26,
            "0:06 proof:": 32,
            "0:12 action:": 24,
        }
        if any(
            _word_count(block) > maximum
            for marker, maximum in tiktok_max_words.items()
            for block in map(str, body)
            if block.strip().casefold().startswith(marker)
        ):
            failures.append("tiktok_beat_exceeds_shootable_runtime_budget")
    if _word_count(text) < (70 if surface_id in {"tiktok", "instagram", "x"} else 110):
        failures.append("artifact_is_too_thin_for_the_surface_job")
    return tuple(dict.fromkeys(failures))


def compile_platform_generation_quality_audit(
    *,
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    capability_reference_only: bool = False,
) -> dict[str, Any]:
    verify_platform_native_challenger_plan(plan)
    verify_platform_native_receipt(receipt, plan=plan)
    if receipt.get("accepted_surface_count") != EXPECTED_SURFACE_COUNT:
        raise GTMPlatformGenerationQualityError("quality audit requires full surface coverage")
    requests = {row["surface_id"]: row for row in plan["requests"]}
    rows: list[dict[str, Any]] = []
    texts: dict[str, str] = {}
    for candidate in receipt["accepted_candidates"]:
        surface_id = str(candidate["surface_id"])
        publication_blockers = list(
            publication_failures(
                candidate, plan=plan, request=requests[surface_id]
            )
        )
        failures = list(
            generation_quality_failures(
                candidate,
                plan=plan,
                request=requests[surface_id],
                capability_reference_only=capability_reference_only,
            )
        )
        texts[surface_id] = _public_text(candidate)
        rows.append(
            {
                "surface_id": surface_id,
                "candidate_sha256": candidate["content_sha256"],
                "pre_human_quality_pass": not failures,
                "failure_count": len(failures),
                "failures": failures,
                "human_craft_review_completed": False,
                "production_effect_observed": False,
                **(
                    {
                        "capability_reference_only": True,
                        "mechanical_publication_ready": not publication_blockers,
                        "publication_blockers": publication_blockers,
                    }
                    if capability_reference_only
                    else {}
                ),
            }
        )
    ctas = Counter(str(row["cta"]).strip().casefold() for row in receipt["accepted_candidates"])
    repeated_ctas = {cta for cta, count in ctas.items() if count > 2}
    campaigns = Counter(
        str(row["campaign_platform"]).strip().casefold()
        for row in receipt["accepted_candidates"]
    )
    repeated_campaigns = {name for name, count in campaigns.items() if count > 1}
    candidate_by_surface = {
        str(row["surface_id"]): row for row in receipt["accepted_candidates"]
    }
    duplicate_pairs: list[dict[str, Any]] = []
    for left, right in combinations(texts, 2):
        score = _jaccard(texts[left], texts[right])
        if score > 0.55:
            duplicate_pairs.append(
                {"left_surface_id": left, "right_surface_id": right, "token_jaccard": round(score, 6)}
            )
    duplicate_surfaces = {
        surface
        for pair in duplicate_pairs
        for surface in (pair["left_surface_id"], pair["right_surface_id"])
    }
    for row in rows:
        surface_id = row["surface_id"]
        candidate = candidate_by_surface[surface_id]
        if str(candidate["cta"]).strip().casefold() in repeated_ctas:
            row["failures"].append("portfolio_reuses_one_cta_on_more_than_two_surfaces")
        if str(candidate["campaign_platform"]).strip().casefold() in repeated_campaigns:
            row["failures"].append("portfolio_reuses_campaign_platform_name")
        if surface_id in duplicate_surfaces:
            row["failures"].append("cross_surface_language_is_too_similar")
        row["failures"] = list(dict.fromkeys(row["failures"]))
        row["failure_count"] = len(row["failures"])
        row["pre_human_quality_pass"] = not row["failures"]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_sha256": plan["content_sha256"],
        "receipt_sha256": receipt["content_sha256"],
        "business_model": plan["business_model"],
        "surface_count": len(rows),
        "pre_human_quality_pass_count": sum(row["pre_human_quality_pass"] for row in rows),
        "blocked_count": sum(not row["pre_human_quality_pass"] for row in rows),
        "cross_surface_duplicate_pairs": duplicate_pairs,
        "rows": rows,
        "human_craft_review_completed_count": 0,
        "production_effect_observed": False,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "truth_boundary": (
            "This deterministic pre-human gate rejects platform-shape, sameness and generic-craft defects. "
            "A pass is not human preference, named-product superiority, publication, organic breakout, conversion, revenue, 4A quality or Top-1 evidence."
        ),
    }
    if capability_reference_only:
        payload.update(
            {
                "capability_reference_only": True,
                "mechanically_publication_ready_count": sum(
                    row["mechanical_publication_ready"] for row in rows
                ),
                "publication_blocked_count": sum(
                    not row["mechanical_publication_ready"] for row in rows
                ),
                "truth_boundary": (
                    "This deterministic gate evaluates a frozen synthetic B2C capability reference while preserving its permanent publication block. "
                    "A craft pass is not publication readiness, human preference, named-product superiority, organic breakout, conversion, revenue, 4A quality or Top-1 evidence."
                ),
            }
        )
    payload["content_sha256"] = _digest(payload)
    verify_platform_generation_quality_audit(payload)
    return payload


def compile_platform_generation_trace_audit(
    *, plan: Mapping[str, Any], trace: Mapping[str, Any]
) -> dict[str, Any]:
    """Audit all sealed raw attempts even when the formal receipt is partial."""

    verify_platform_native_challenger_plan(plan)
    unsigned_trace = dict(trace)
    supplied_trace_sha256 = unsigned_trace.pop("content_sha256", None)
    if supplied_trace_sha256 != _digest(unsigned_trace):
        raise GTMPlatformGenerationQualityError("generation trace digest is invalid")
    if (
        trace.get("plan_sha256") != plan.get("content_sha256")
        or trace.get("business_model") != plan.get("business_model")
    ):
        raise GTMPlatformGenerationQualityError("generation trace escaped the plan")
    attempts_by_surface = trace.get("attempts_by_surface")
    if not isinstance(attempts_by_surface, dict):
        raise GTMPlatformGenerationQualityError("generation trace attempts are invalid")
    requests = {row["surface_id"]: row for row in plan["requests"]}
    if not set(attempts_by_surface).issubset(requests):
        raise GTMPlatformGenerationQualityError("generation trace contains an unknown surface")
    rows: list[dict[str, Any]] = []
    for surface_id, request in requests.items():
        attempts = attempts_by_surface.get(surface_id, [])
        if not isinstance(attempts, list):
            raise GTMPlatformGenerationQualityError("generation trace surface attempts are invalid")
        sealed_attempts: list[dict[str, Any]] = []
        passing_candidate_sha256: str | None = None
        passing_attempt: int | None = None
        for index, attempt in enumerate(attempts, start=1):
            raw = str(attempt.get("raw_output", "")) if isinstance(attempt, dict) else ""
            try:
                candidate = adapt_platform_native_candidate(
                    extract_first_json_object(raw), plan=plan, request=request
                )
                base = candidate_failures(candidate, plan=plan, request=request)
                quality = (
                    generation_quality_failures(candidate, plan=plan, request=request)
                    if not base
                    else ()
                )
                candidate_sha256 = candidate["content_sha256"]
            except Exception as error:
                base = (str(error),)
                quality = ()
                candidate_sha256 = None
            passed = not base and not quality
            if passed:
                passing_candidate_sha256 = candidate_sha256
                passing_attempt = index
            sealed_attempts.append(
                {
                    "attempt": index,
                    "source": str(attempt.get("source", "unknown")) if isinstance(attempt, dict) else "invalid",
                    "raw_output_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    "candidate_sha256": candidate_sha256,
                    "base_contract_failures": list(base),
                    "pre_human_quality_failures": list(quality),
                    "pre_human_quality_pass": passed,
                }
            )
        rows.append(
            {
                "surface_id": surface_id,
                "attempt_count": len(sealed_attempts),
                "pre_human_quality_pass": passing_attempt is not None,
                "passing_attempt": passing_attempt,
                "passing_candidate_sha256": passing_candidate_sha256,
                "attempts": sealed_attempts,
            }
        )
    payload: dict[str, Any] = {
        "schema": TRACE_AUDIT_SCHEMA,
        "plan_sha256": plan["content_sha256"],
        "trace_sha256": supplied_trace_sha256,
        "business_model": plan["business_model"],
        "surface_count": EXPECTED_SURFACE_COUNT,
        "traced_surface_count": len(attempts_by_surface),
        "pre_human_quality_pass_count": sum(row["pre_human_quality_pass"] for row in rows),
        "blocked_or_missing_count": sum(not row["pre_human_quality_pass"] for row in rows),
        "rows": rows,
        "human_craft_review_completed_count": 0,
        "production_effect_observed": False,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "truth_boundary": (
            "This trace audit proves deterministic validation of sealed local attempts, including partial runs. "
            "It does not prove human preference, named-product superiority, publication, organic breakout, conversion, revenue, 4A quality or Top-1 status."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_platform_generation_trace_audit(payload)
    return payload


def verify_platform_generation_quality_audit(value: object) -> None:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise GTMPlatformGenerationQualityError("generation quality schema is invalid")
    unsigned = dict(value)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMPlatformGenerationQualityError("generation quality digest is invalid")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_SURFACE_COUNT:
        raise GTMPlatformGenerationQualityError("generation quality coverage is invalid")
    if value.get("pre_human_quality_pass_count") + value.get("blocked_count") != EXPECTED_SURFACE_COUNT:
        raise GTMPlatformGenerationQualityError("generation quality counts are invalid")
    if value.get("human_craft_review_completed_count") != 0:
        raise GTMPlatformGenerationQualityError("generation quality audit fabricated human review")
    for field in ("production_effect_observed", "four_a_claim_eligible", "top1_claim_eligible"):
        if value.get(field) is not False:
            raise GTMPlatformGenerationQualityError("generation quality audit overclaimed evidence")
    if value.get("capability_reference_only") is True:
        if (
            value.get("business_model") != "b2c"
            or value.get("mechanically_publication_ready_count") != 0
            or value.get("publication_blocked_count") != EXPECTED_SURFACE_COUNT
            or any(
                row.get("capability_reference_only") is not True
                or row.get("mechanical_publication_ready") is not False
                or "synthetic_benchmark_is_not_publishable_product_content"
                not in row.get("publication_blockers", ())
                for row in rows
            )
        ):
            raise GTMPlatformGenerationQualityError(
                "capability reference escaped its publication boundary"
            )


def verify_platform_generation_trace_audit(value: object) -> None:
    if not isinstance(value, dict) or value.get("schema") != TRACE_AUDIT_SCHEMA:
        raise GTMPlatformGenerationQualityError("generation trace audit schema is invalid")
    unsigned = dict(value)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMPlatformGenerationQualityError("generation trace audit digest is invalid")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_SURFACE_COUNT:
        raise GTMPlatformGenerationQualityError("generation trace audit coverage is invalid")
    if value.get("pre_human_quality_pass_count") + value.get("blocked_or_missing_count") != EXPECTED_SURFACE_COUNT:
        raise GTMPlatformGenerationQualityError("generation trace audit counts are invalid")
    if not 0 <= value.get("traced_surface_count", -1) <= EXPECTED_SURFACE_COUNT:
        raise GTMPlatformGenerationQualityError("generation trace audited-surface count is invalid")
    if value.get("human_craft_review_completed_count") != 0:
        raise GTMPlatformGenerationQualityError("generation trace audit fabricated human review")
    for field in ("production_effect_observed", "four_a_claim_eligible", "top1_claim_eligible"):
        if value.get(field) is not False:
            raise GTMPlatformGenerationQualityError("generation trace audit overclaimed evidence")
