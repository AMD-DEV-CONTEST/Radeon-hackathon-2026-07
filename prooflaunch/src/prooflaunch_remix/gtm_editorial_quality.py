from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .gtm_strategy import CampaignStrategyInput, GTMStrategy


SCHEMA = "ProofLaunchGTMEditorialQualityReceiptV1"


class EditorialQualityError(ValueError):
    """The editorial screen is incomplete, tampered, or overclaims quality."""


_SLOP_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("generic_era_opening", re.compile(r"\bin (?:today's|this) (?:(?:fast[- ]paced|ever[- ]changing) )?(?:digital )?world\b", re.I)),
    ("empty_unlock", re.compile(r"\bunlock (?:the )?(?:power|potential|future|possibilities)\b", re.I)),
    ("generic_transformation", re.compile(r"\b(?:revolutioni[sz]e|game[- ]changer|paradigm shift|next level)\b", re.I)),
    ("unsupported_certainty", re.compile(r"\b(?:guaranteed|always works|will go viral|effortless success)\b", re.I)),
    ("empty_summary", re.compile(r"\bin conclusion,? (?:it is|it's) (?:clear|evident|important)\b", re.I)),
)


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


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", text) if item.strip()]


def _classify_hook(text: str) -> list[str]:
    lowered = text.casefold()
    classes: list[str] = []
    if "?" in text:
        classes.append("question")
    if any(token in lowered for token in ("do not", "don't", "before accepting", "challenge")):
        classes.append("contrarian_or_challenge")
    if any(token in lowered for token in ("proof", "evidence", "source", "study")):
        classes.append("proof")
    if any(token in lowered for token in ("cost", "risk", "loss", "hidden")):
        classes.append("loss_or_risk")
    if any(token in lowered for token in ("show", "watch", "inspect", "see how", "demo")):
        classes.append("demonstration")
    if any(token in lowered for token in ("teams like", "people who", "identity", "operators")):
        classes.append("identity")
    return classes or ["unclassified_human_review_required"]


def _mechanical_check(check_id: str, passed: bool, evidence: Sequence[str], remedy: str) -> dict[str, object]:
    return {
        "check_id": check_id,
        "mechanical_pass": passed,
        "evidence": list(evidence),
        "remedy_if_failed": remedy,
        "human_editor_pass": None,
    }


def compile_editorial_quality_receipt(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    primary_copy: Mapping[str, object],
    secondary_copy: Mapping[str, object],
    video_hook: str,
    long_form_blocks: Sequence[str],
) -> dict[str, Any]:
    primary_text = "\n".join(
        [
            str(primary_copy.get("hook") or ""),
            *[str(item) for item in primary_copy.get("body", [])],
            str(primary_copy.get("call_to_action") or ""),
        ]
    )
    secondary_text = "\n".join(
        [
            str(secondary_copy.get("hook") or ""),
            *[str(item) for item in secondary_copy.get("body", [])],
            str(secondary_copy.get("call_to_action") or ""),
        ]
    )
    combined = "\n".join((primary_text, secondary_text, *long_form_blocks))
    slop_findings = [
        {
            "pattern_id": pattern_id,
            "match": match.group(0),
            "start": match.start(),
        }
        for pattern_id, pattern in _SLOP_PATTERNS
        for match in pattern.finditer(combined)
    ]
    hook_rows = [
        {
            "role": "primary",
            "classes": _classify_hook(str(primary_copy.get("hook") or "")),
            "hook_sha256": hashlib.sha256(str(primary_copy.get("hook") or "").encode("utf-8")).hexdigest(),
        },
        {
            "role": "secondary",
            "classes": _classify_hook(str(secondary_copy.get("hook") or "")),
            "hook_sha256": hashlib.sha256(str(secondary_copy.get("hook") or "").encode("utf-8")).hexdigest(),
        },
    ]
    claim_marker = strategy.proof_claim_id
    common_checks = [
        _mechanical_check(
            "evidence_binding",
            claim_marker in primary_text and claim_marker in secondary_text,
            [claim_marker],
            "Restore the exact evidence-card identifier in every factual draft.",
        ),
        _mechanical_check(
            "hook_is_classifiable",
            all(row["classes"] != ["unclassified_human_review_required"] for row in hook_rows),
            [str(row["classes"]) for row in hook_rows],
            "Rewrite the opening around one explicit question, proof, loss, challenge, identity or demonstration mechanism.",
        ),
        _mechanical_check(
            "anti_ai_slop",
            not slop_findings,
            [finding["pattern_id"] for finding in slop_findings],
            "Replace generic era language, empty transformation claims and unsupported certainty with specific audience, action and proof.",
        ),
        _mechanical_check(
            "channel_copy_not_duplicated",
            primary_text.casefold() != secondary_text.casefold(),
            [str(primary_copy.get("native_format")), str(secondary_copy.get("native_format"))],
            "Rebuild each asset around its platform-native attention and interaction behavior.",
        ),
    ]

    if request.audience.business_model.value == "b2b":
        specific = all(
            value.casefold() in combined.casefold()
            for value in (request.audience.name, request.audience.buying_context)
        )
        mode_check = _mechanical_check(
            "b2b_decision_specificity",
            specific,
            [request.audience.name, request.audience.buying_context, claim_marker],
            "Name the decision role, buying situation, operational consequence and source-bound proof without adding unverified ROI.",
        )
    else:
        specific = all(
            value.casefold() in combined.casefold()
            for value in (request.audience.core_problem, request.audience.desired_outcome)
        )
        mode_check = _mechanical_check(
            "b2c_perception_and_action_closure",
            specific,
            [request.audience.core_problem, request.audience.desired_outcome, claim_marker],
            "Make the trigger, desired progress, product role and next-step friction legible without fabricated urgency.",
        )

    humor_markers = [token for token in ("lol", "joke", "roast", "meme", "sarcasm") if token in combined.casefold()]
    humor_check = {
        "status": "not_used" if not humor_markers else "human_boundary_review_required",
        "markers": humor_markers,
        "required_review_axes": ["brand_identity", "cultural_context", "target_of_humor", "durable_brand_asset_risk"],
        "human_editor_pass": None,
    }

    long_form_text = "\n".join(long_form_blocks)
    long_form_word_count = len(long_form_text.split())
    if long_form_word_count < 120:
        long_form = {
            "status": "not_applicable_short_draft",
            "word_count": long_form_word_count,
            "axes": ["thesis", "information_gain", "evidence", "rhythm", "counterargument", "conclusion"],
            "human_editor_pass": None,
        }
    else:
        lower_long = long_form_text.casefold()
        long_form = {
            "status": "mechanically_screened_human_review_required",
            "word_count": long_form_word_count,
            "mechanical_signals": {
                "evidence_marker_present": claim_marker.casefold() in lower_long,
                "counterargument_marker_present": any(token in lower_long for token in ("however", "objection", "limitation", "counter")),
                "conclusion_present": len(_sentences(long_form_text)) >= 5,
            },
            "human_editor_pass": None,
        }

    spoken_sentences = _sentences(video_hook)
    long_spoken = [sentence for sentence in spoken_sentences if len(sentence.split()) > 24]
    spoken = {
        "status": "mechanical_pass_human_read_aloud_required" if not long_spoken else "revision_required",
        "sentence_count": len(spoken_sentences),
        "over_24_word_sentences": long_spoken,
        "semicolon_count": video_hook.count(";"),
        "parenthetical_count": video_hook.count("(") + video_hook.count(")"),
        "human_read_aloud_pass": None,
    }
    checks = [*common_checks, mode_check]
    failed_ids = [row["check_id"] for row in checks if not row["mechanical_pass"]]
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "strategy_id": strategy.strategy_id,
        "campaign_id": request.campaign_id,
        "hook_classification": hook_rows,
        "anti_ai_slop_findings": slop_findings,
        "mechanical_checks": checks,
        "mechanical_failed_check_ids": failed_ids,
        "mechanical_screen_passed": not failed_ids and spoken["status"] != "revision_required",
        "business_model_editor": request.audience.business_model.value,
        "humor_boundary": humor_check,
        "long_form_editor": long_form,
        "spoken_native_editor": spoken,
        "quality_state": "mechanically_screened_human_editor_unobserved",
        "human_editor_pass": None,
        "direct_publishability_observed": False,
        "external_publish_executed": False,
        "truth_boundary": (
            "This receipt proves deterministic editorial checks only. It cannot establish taste, originality, platform fit, "
            "direct publishability, human preference or market effect without named-human review and observation."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_editorial_quality_receipt(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise EditorialQualityError("editorial quality receipt seal is invalid")
    checks = payload.get("mechanical_checks")
    if not isinstance(checks, list) or len(checks) < 5:
        raise EditorialQualityError("editorial quality receipt is incomplete")
    if payload.get("human_editor_pass") is not None:
        raise EditorialQualityError("mechanical compilation cannot record a human editor pass")
    if payload.get("direct_publishability_observed") is not False:
        raise EditorialQualityError("mechanical compilation cannot prove publishability")
