from __future__ import annotations

import hashlib
import json
import re
from itertools import combinations
from typing import Any, Mapping, Sequence

from .gtm_platform_native_challenger import (
    EXPECTED_SURFACE_COUNT,
    candidate_failures,
    canonical_json,
    verify_platform_native_challenger_plan,
    verify_platform_native_receipt,
)


SCHEMA = "ProofLaunchPlatformNativePublicationAuditV1"


class GTMPlatformNativePublicationAuditError(ValueError):
    """A publication audit is incomplete, unbound, or overclaims readiness."""


PLACEHOLDER_PATTERNS = (
    re.compile(r"\[(?:[^\]]{0,80})(?:link|placeholder|hypothetical)(?:[^\]]{0,80})\]", re.I),
    re.compile(r"\bplaceholder\s+(?:url|link|asset|image|video)\b", re.I),
    re.compile(r"\bhypothetical\s+(?:url|link|asset)\b", re.I),
    re.compile(r"\b(?:image|video|audio)\s+link\b", re.I),
    re.compile(r"\blink to (?:a|an|the)\b", re.I),
)

UNBOUND_DELIVERY_PATTERNS = (
    re.compile(r"\bdownload\b", re.I),
    re.compile(r"\brequest access\b", re.I),
    re.compile(r"\btap to (?:see|view|open)\b", re.I),
    re.compile(r"\bclick to (?:see|view|open)\b", re.I),
)

UNBOUND_CASE_OR_TOOL_PATTERNS = (
    re.compile(r"[$£€]\s?\d[\d,.]*\s*(?:m|mm|million|b|billion)?\s+arr\b", re.I),
    re.compile(r"\b(?:sample|live)\s+(?:brief|case study)\b", re.I),
    re.compile(r"\b(?:diagnostic|assessment)\s+(?:tool|worksheet)\b", re.I),
    re.compile(r"\bpersonalized assessment\b", re.I),
    re.compile(r"\bi (?:recently|just) (?:dug into|reviewed|analysed|analyzed)\b", re.I),
    re.compile(r"\bgenerated (?:few|many|\d+) qualified leads\b", re.I),
    re.compile(r"\b(?:screen recording|demo video)\b", re.I),
    re.compile(r"\bsubmit a brief\b", re.I),
    re.compile(r"\breceive a (?:detailed )?(?:provenance trace|assessment|report)\b", re.I),
)

UNAPPROVED_FEATURE_EFFECT_PATTERNS = (
    re.compile(r"\b(?:eliminates?|ensures?|increases?|improves?|reduces?|accelerates?|boosts?)\b", re.I),
    re.compile(r"\b(?:solves?|prevents?|guarantees?)\b", re.I),
    re.compile(r"\b(?:safeguards?|minimi[sz](?:e|es|ed|ing)|fosters?|promotes?|reshapes?)\b", re.I),
    re.compile(r"\b(?:freeing your team|handles the heavy lifting)\b", re.I),
    re.compile(r"\bhandles? the operational details\b", re.I),
)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _public_text(candidate: Mapping[str, Any]) -> str:
    values: list[str] = []
    for field in (
        "campaign_platform",
        "hook",
        "progression",
        "body",
        "cta",
        "participation_mechanism",
        "proof_integration",
    ):
        value = candidate.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value)
    return "\n".join(values)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _assertive_match(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 90) : match.start()].casefold()
        if any(
            marker in prefix
            for marker in (
                "not claiming",
                "do not claim",
                "does not claim",
                "never claim",
                "cannot claim",
                "without claiming",
                "isn't about",
                "is not about",
                "hypothesis",
            )
        ):
            continue
        return True
    return False


def publication_failures(
    candidate: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    request: Mapping[str, Any],
) -> tuple[str, ...]:
    failures = list(candidate_failures(candidate, plan=plan, request=request))
    text = _public_text(candidate)
    folded = text.casefold()
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            failures.append("unresolved_placeholder_or_hypothetical_asset")
            break
    if any(pattern.search(text) for pattern in UNBOUND_DELIVERY_PATTERNS):
        failures.append("cta_requires_unbound_external_delivery_or_link")
    if any(pattern.search(text) for pattern in UNBOUND_CASE_OR_TOOL_PATTERNS):
        failures.append("unbound_case_or_tool_claim")
    for pattern in UNAPPROVED_FEATURE_EFFECT_PATTERNS:
        if _assertive_match(pattern, text):
            failures.append("unapproved_feature_or_effect_assertion")
            break
    approved_claim = str(plan["brief"]["approved_claim"]).casefold().rstrip(".")
    semantic_claim = re.sub(r"^the synthetic ", "the ", approved_claim)
    if folded.count(semantic_claim) > 1:
        failures.append("approved_claim_repeated_or_paraphrased_as_duplicate_proof")
    if plan.get("business_model") == "b2c":
        if "synthetic benchmark" not in folded:
            failures.append("synthetic_b2c_benchmark_disclosure_missing")
        failures.append("synthetic_benchmark_is_not_publishable_product_content")
    if request.get("surface_id") == "reddit" and not any(
        marker in folded
        for marker in ("we built", "i work on", "our team", "affiliation", "i'm building")
    ):
        failures.append("reddit_product_affiliation_disclosure_missing")
    offer = str(plan["brief"]["offer"]).casefold()
    cta = str(candidate.get("cta", "")).casefold()
    required_offer_markers = (
        ("inspect", "evidence", "join")
        if plan.get("business_model") == "b2b"
        else ("try", "challenge", "private")
    )
    if not any(marker in cta for marker in required_offer_markers):
        failures.append("cta_does_not_advance_the_frozen_offer")
    if "share" in cta and "share" not in offer:
        failures.append("cta_substitutes_engagement_for_the_frozen_offer")
    return tuple(dict.fromkeys(failures))


def compile_platform_native_publication_audit(
    bundles: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> dict[str, Any]:
    if len(bundles) != 2:
        raise GTMPlatformNativePublicationAuditError("audit requires one B2B and one B2C bundle")
    rows: list[dict[str, Any]] = []
    public_text_by_id: dict[str, str] = {}
    source_receipts: list[dict[str, str]] = []
    for plan, receipt in bundles:
        verify_platform_native_challenger_plan(plan)
        verify_platform_native_receipt(receipt, plan=plan)
        if receipt.get("accepted_surface_count") != EXPECTED_SURFACE_COUNT:
            raise GTMPlatformNativePublicationAuditError("audit input lacks full platform coverage")
        source_receipts.append(
            {
                "business_model": str(plan["business_model"]),
                "plan_sha256": str(plan["content_sha256"]),
                "receipt_sha256": str(receipt["content_sha256"]),
            }
        )
        requests = {row["surface_id"]: row for row in plan["requests"]}
        for candidate in receipt["accepted_candidates"]:
            surface_id = candidate["surface_id"]
            row_id = f"{plan['business_model']}:{surface_id}"
            failures = publication_failures(
                candidate, plan=plan, request=requests[surface_id]
            )
            text = _public_text(candidate)
            public_text_by_id[row_id] = text
            rows.append(
                {
                    "row_id": row_id,
                    "business_model": plan["business_model"],
                    "surface_id": surface_id,
                    "candidate_sha256": candidate["content_sha256"],
                    "mechanical_publication_ready": not failures,
                    "failure_count": len(failures),
                    "failures": list(failures),
                    "binary_llm_judges_required": [
                        "platform_native_and_not_cross_post_reformatted",
                        "hook_progression_and_participation_form_one_original_mechanism",
                        "every_product_assertion_stays_inside_frozen_truth_and_proof",
                    ],
                    "source_hidden_human_questions": [
                        "Would a senior platform editor publish this without major rework?",
                        "Does the artifact create user value without deceptive engagement or a product click?",
                    ],
                    "human_review_completed": False,
                    "external_publish_executed": False,
                }
            )
    duplicate_pairs: list[dict[str, Any]] = []
    for left, right in combinations(rows, 2):
        if left["business_model"] != right["business_model"]:
            continue
        score = _jaccard(public_text_by_id[left["row_id"]], public_text_by_id[right["row_id"]])
        if score > 0.72:
            duplicate_pairs.append(
                {
                    "left_row_id": left["row_id"],
                    "right_row_id": right["row_id"],
                    "token_jaccard": round(score, 6),
                    "maximum_allowed": 0.72,
                }
            )
    duplicate_row_ids = {
        row_id
        for pair in duplicate_pairs
        for row_id in (pair["left_row_id"], pair["right_row_id"])
    }
    for row in rows:
        if row["row_id"] in duplicate_row_ids:
            row["mechanical_publication_ready"] = False
            row["failures"].append("cross_surface_copy_is_too_similar")
            row["failure_count"] = len(row["failures"])
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_receipts": source_receipts,
        "row_count": len(rows),
        "b2b_row_count": sum(row["business_model"] == "b2b" for row in rows),
        "b2c_row_count": sum(row["business_model"] == "b2c" for row in rows),
        "mechanically_publication_ready_count": sum(
            row["mechanical_publication_ready"] for row in rows
        ),
        "blocked_count": sum(not row["mechanical_publication_ready"] for row in rows),
        "cross_surface_duplicate_pair_count": len(duplicate_pairs),
        "cross_surface_duplicate_pairs": duplicate_pairs,
        "rows": rows,
        "human_review_completed_count": 0,
        "external_publish_executed": False,
        "production_effect_observed": False,
        "truth_boundary": (
            "This audit distinguishes platform-contract validity from direct publication readiness. "
            "It proves only deterministic checks over local drafts; subjective craft, named-product preference, publication and outcomes remain unproven. "
            "The B2C lane is a synthetic generalization benchmark and is never publishable product content."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_platform_native_publication_audit(payload)
    return payload


def verify_platform_native_publication_audit(value: object) -> None:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise GTMPlatformNativePublicationAuditError("publication audit schema is invalid")
    unsigned = dict(value)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMPlatformNativePublicationAuditError("publication audit digest is invalid")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != 26:
        raise GTMPlatformNativePublicationAuditError("publication audit row coverage is invalid")
    if value.get("b2b_row_count") != 13 or value.get("b2c_row_count") != 13:
        raise GTMPlatformNativePublicationAuditError("publication audit business-model coverage is invalid")
    if value.get("mechanically_publication_ready_count") + value.get("blocked_count") != 26:
        raise GTMPlatformNativePublicationAuditError("publication audit status counts are invalid")
    if value.get("human_review_completed_count") != 0:
        raise GTMPlatformNativePublicationAuditError("publication audit fabricated human review")
    if value.get("external_publish_executed") is not False or value.get("production_effect_observed") is not False:
        raise GTMPlatformNativePublicationAuditError("publication audit authority was upgraded")
    for row in rows:
        if row.get("human_review_completed") is not False or row.get("external_publish_executed") is not False:
            raise GTMPlatformNativePublicationAuditError("publication audit row authority was upgraded")
