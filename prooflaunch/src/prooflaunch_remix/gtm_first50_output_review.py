from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Mapping, Sequence

from .gtm_codex_lighthouse_portfolio import (
    verify_lighthouse_portfolio,
    verify_lighthouse_quality_portfolio,
)


QUEUE_SCHEMA = "ProofLaunchFirst50OutputHumanReadQueueV1"
SEED_SCHEMA = "ProofLaunchFirst50Level1SeedManifestV1"
RECEIPT_SCHEMA = "ProofLaunchFirst50NamedHumanReadReceiptV1"
CODEX_PREREVIEW_SCHEMA = "ProofLaunchFirst50CodexPrereviewV1"
HUMAN_ATTESTATION = (
    "I personally read every assigned output and recorded my own release judgment "
    "and observed failure, without treating machine preflight as a human conclusion."
)

FAILURE_BUCKETS: dict[str, dict[str, str]] = {
    "brief_drift": {
        "question": "Did the output change the audience, objective, offer, stage or budget?",
        "oracle": "immutable brief fields and their digests remain exact",
        "mutation": "replace one immutable brief field with a different frozen-case value",
    },
    "claim_or_product_detail_hallucination": {
        "question": "Did it add or strengthen a product fact beyond the approved evidence?",
        "oracle": "every factual product claim is an exact approved claim or explicitly a hypothesis",
        "mutation": "inject one unsupported product, customer, performance or availability fact",
    },
    "platform_flattening": {
        "question": "Could the same expression be pasted unchanged onto a different platform?",
        "oracle": "surface-specific structure, interaction and CTA markers remain present",
        "mutation": "replace the native structure with another surface's unchanged structure",
    },
    "spray_and_pray_distribution": {
        "question": "Did the output expand channels without an explicit job and stop rule?",
        "oracle": "initial flight remains limited to the frozen focus surfaces",
        "mutation": "add an unscheduled platform or paid lane to the initial flight",
    },
    "generic_campaign_platform": {
        "question": "Is the idea interchangeable with a generic AI-marketing campaign?",
        "oracle": "industry tension, buying motion and owner proof remain recoverable",
        "mutation": "remove the industry tension, buying motion and owner-specific proof",
    },
    "synthetic_or_unobserved_effect_leakage": {
        "question": "Did it present an unobserved result, lift, popularity or causality as fact?",
        "oracle": "unobserved outcomes remain hypotheses with a falsifier",
        "mutation": "convert one hypothesis into a guaranteed or already-achieved outcome",
    },
    "rights_privacy_or_regulatory_escape": {
        "question": "Did it escape evidence rights, privacy or specialist-review constraints?",
        "oracle": "rights, validity, release scope and regulated review remain blocking gates",
        "mutation": "remove one required rights, validity, privacy or specialist approval gate",
    },
    "missing_falsifier_or_stop_rule": {
        "question": "Could the team tell when this idea should stop or be rejected?",
        "oracle": "a located falsifier and operational stop rule remain attached",
        "mutation": "delete the falsifier or replace the stop rule with an open-ended continue rule",
    },
    "vanity_metric_optimization": {
        "question": "Did it optimize reach or engagement without a qualified business action?",
        "oracle": "metric, numerator, denominator, qualification and decision rule remain bound",
        "mutation": "replace the qualified outcome with views, impressions or raw likes",
    },
    "ai_slop_or_spoken_non_native": {
        "question": "Does the language rely on generic AI cadence or fail a natural read-aloud test?",
        "oracle": "bounded anti-slop tokens and spoken-native constraints remain satisfied",
        "mutation": "inject generic era framing, empty transformation language or article-readout cadence",
    },
}

CODEX_PREREVIEW_BUCKETS: dict[str, dict[str, str]] = {
    "strategy_safe_but_not_commercially_sharp": {
        "repair": "Lead with one differentiated customer decision and compress the proof boundary into one adjacent line.",
        "human_question": "Would a senior strategist keep this organizing idea after removing the safety scaffolding?",
    },
    "email_reviews_research_instead_of_progressing_lifecycle": {
        "repair": "Give the email one lifecycle job and a useful product-adjacent next step, while retaining consent and suppression gates.",
        "human_question": "Does the email advance a real buyer or user state rather than recruit another evaluator?",
    },
    "seo_informs_but_weakly_converts": {
        "repair": "Add an owned tool, diagnostic or decision artifact that naturally continues the search intent into qualified action.",
        "human_question": "After receiving information gain, is the reader's next qualified action obvious and credible?",
    },
    "video_proves_boundary_before_product_payoff": {
        "repair": "Show the product-mediated payoff or decision in the first three seconds, then attach the limitation without turning the film into a warning card.",
        "human_question": "Would the first three seconds earn attention from a target user who did not already care about compliance?",
    },
    "geo_answer_lacks_live_citation_evidence": {
        "repair": "Bind every direct answer to current, named, retrievable sources and a last-reviewed time before publication.",
        "human_question": "Could an answer engine quote this safely with a located source and current evidence boundary?",
    },
    "expert_copy_lacks_owner_specific_market_proof": {
        "repair": "Preserve the expert insight but attach one owner-approved workflow artifact, observation or measurable proof unit.",
        "human_question": "Does this feel like proprietary operating knowledge rather than polished general advice?",
    },
    "social_hook_leads_to_research_not_product_desire": {
        "repair": "Keep the native hook, but make the product role and desired progress visible before asking for research participation.",
        "human_question": "Would the target audience want the product experience, not merely answer the creator's question?",
    },
    "search_asset_has_decision_tool_but_no_verified_offer_transition": {
        "repair": "Connect the decision tool to an owner-approved offer with fit, non-fit and next-review conditions.",
        "human_question": "Does the search asset move a qualified evaluator toward a defensible offer decision?",
    },
}

_SHA = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")


class First50OutputReviewError(ValueError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _with_digest(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = _digest(result)
    return result


def _verify_digest(payload: Mapping[str, Any], schema: str) -> None:
    if payload.get("schema") != schema:
        raise First50OutputReviewError(f"unexpected schema for {schema}")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise First50OutputReviewError(f"invalid content digest for {schema}")


def _output_row(
    candidate: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    kind: str,
    ordinal: int,
    payload: Mapping[str, Any],
    surface: str | None = None,
) -> dict[str, Any]:
    selector = dict(candidate["selector"])
    artifact_sha256 = _digest(payload)
    output_id = f"first50-{candidate['candidate_id'][-12:]}-{kind}-{ordinal:02d}"
    failures = [
        str(row.get("gate_id"))
        for row in audit.get("gate_checks", [])
        if isinstance(row, Mapping) and row.get("passed") is not True
    ]
    return {
        "output_id": output_id,
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": candidate["content_sha256"],
        "selector": selector,
        "artifact_kind": kind,
        "surface": surface,
        "artifact_payload": dict(payload),
        "artifact_sha256": artifact_sha256,
        "source_locator": (
            "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json#candidate="
            + candidate["candidate_id"]
            + f"&kind={kind}&ordinal={ordinal}"
        ),
        "machine_preflight": {
            "level_1_passed": audit.get("level_1", {}).get("passed") is True,
            "gate_count": len(audit.get("gate_checks", [])),
            "located_failure_ids": failures,
            "counts_as_human_reading": False,
        },
        "human_review_state": "awaiting_named_human",
    }


def compile_first50_output_review_queue(
    portfolio: Mapping[str, Any],
    quality_portfolio: Mapping[str, Any],
) -> dict[str, Any]:
    verify_lighthouse_portfolio(portfolio)
    verify_lighthouse_quality_portfolio(quality_portfolio, portfolio=portfolio)
    candidates = portfolio["candidates"]
    audits = quality_portfolio["audits"]
    audit_by_candidate = {row["candidate_sha256"]: row for row in audits}
    rows: list[dict[str, Any]] = []
    first_by_model: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        audit = audit_by_candidate.get(candidate["content_sha256"])
        if audit is None:
            raise First50OutputReviewError("candidate has no bound Level-1 audit")
        model = str(candidate["selector"]["business_model"])
        first_by_model.setdefault(model, candidate)
        rows.extend(
            [
                _output_row(candidate, audit, kind="campaign_system", ordinal=0, payload=candidate["campaign_system"]),
                _output_row(
                    candidate,
                    audit,
                    kind="platform_asset",
                    ordinal=0,
                    payload=candidate["platform_assets"][0],
                    surface=str(candidate["platform_assets"][0]["surface_id"]),
                ),
                _output_row(
                    candidate,
                    audit,
                    kind="platform_asset",
                    ordinal=1,
                    payload=candidate["platform_assets"][1],
                    surface=str(candidate["platform_assets"][1]["surface_id"]),
                ),
                _output_row(candidate, audit, kind="email", ordinal=0, payload=candidate["email"], surface="email"),
                _output_row(candidate, audit, kind="seo_page", ordinal=0, payload=candidate["seo_page"], surface="seo"),
                _output_row(candidate, audit, kind="video_script", ordinal=0, payload=candidate["video_script"], surface="video"),
            ]
        )
    for model in ("b2b", "b2c"):
        candidate = first_by_model.get(model)
        if candidate is None:
            raise First50OutputReviewError("both B2B and B2C candidates are required")
        audit = audit_by_candidate[candidate["content_sha256"]]
        rows.append(
            _output_row(
                candidate,
                audit,
                kind="geo_answer",
                ordinal=0,
                payload=candidate["geo_answer"],
                surface="geo",
            )
        )
    rows.sort(key=lambda row: row["output_id"])
    if len(rows) != 50:
        raise First50OutputReviewError("first-output queue must contain exactly 50 outputs")
    kind_counts = Counter(row["artifact_kind"] for row in rows)
    model_counts = Counter(row["selector"]["business_model"] for row in rows)
    queue = _with_digest(
        {
            "schema": QUEUE_SCHEMA,
            "source_portfolio_sha256": portfolio["content_sha256"],
            "source_quality_portfolio_sha256": quality_portfolio["content_sha256"],
            "output_count": 50,
            "business_model_counts": dict(sorted(model_counts.items())),
            "artifact_kind_counts": dict(sorted(kind_counts.items())),
            "industry_archetype_count": len(
                {row["selector"]["industry_archetype"] for row in rows}
            ),
            "lifecycle_count": len({row["selector"]["lifecycle"] for row in rows}),
            "budget_tier_count": len({row["selector"]["budget"] for row in rows}),
            "machine_preflight_pass_count": sum(
                row["machine_preflight"]["level_1_passed"] for row in rows
            ),
            "named_human_read_count": 0,
            "t073_complete": False,
            "allowed_failure_buckets": [
                {"bucket_id": key, **value} for key, value in FAILURE_BUCKETS.items()
            ],
            "review_contract": {
                "required_per_output": [
                    "direct_publishable",
                    "major_rework",
                    "blocking_defect",
                    "failure_bucket",
                    "evidence_span",
                    "written_reason",
                ],
                "named_reviewer_required": True,
                "attestation": HUMAN_ATTESTATION,
                "machine_preflight_visible_but_non_authoritative": True,
                "all_50_required_before_aggregation": True,
            },
            "outputs": rows,
            "truth_boundary": (
                "These are fifty actual, content-addressed outputs from eight synthetic clean-room product runs. "
                "Level-1 preflight proves mechanics only. No person has yet read all fifty here, so T073, "
                "publishability, preference, release, effect, 4A quality and named-product superiority remain unproven."
            ),
        }
    )
    verify_first50_output_review_queue(queue, portfolio=portfolio, quality_portfolio=quality_portfolio)
    return queue


def verify_first50_output_review_queue(
    queue: Mapping[str, Any],
    *,
    portfolio: Mapping[str, Any] | None = None,
    quality_portfolio: Mapping[str, Any] | None = None,
) -> None:
    _verify_digest(queue, QUEUE_SCHEMA)
    rows = queue.get("outputs")
    if not isinstance(rows, list) or len(rows) != 50 or queue.get("output_count") != 50:
        raise First50OutputReviewError("first-output queue count is invalid")
    if queue.get("business_model_counts") != {"b2b": 25, "b2c": 25}:
        raise First50OutputReviewError("first-output queue is not B2B/B2C balanced")
    expected_kinds = {
        "campaign_system": 8,
        "email": 8,
        "geo_answer": 2,
        "platform_asset": 16,
        "seo_page": 8,
        "video_script": 8,
    }
    if queue.get("artifact_kind_counts") != expected_kinds:
        raise First50OutputReviewError("first-output artifact coverage drifted")
    if (
        queue.get("industry_archetype_count") != 8
        or queue.get("lifecycle_count") != 4
        or queue.get("budget_tier_count") != 3
        or queue.get("machine_preflight_pass_count") != 50
        or queue.get("named_human_read_count") != 0
        or queue.get("t073_complete") is not False
    ):
        raise First50OutputReviewError("first-output authority or coverage drifted")
    ids: set[str] = set()
    digests: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise First50OutputReviewError("first-output row is invalid")
        output_id = str(row.get("output_id", ""))
        artifact_sha256 = str(row.get("artifact_sha256", ""))
        if (
            not _SAFE_ID.fullmatch(output_id)
            or output_id in ids
            or not _SHA.fullmatch(artifact_sha256)
            or artifact_sha256 in digests
            or artifact_sha256 != _digest(row.get("artifact_payload"))
            or row.get("human_review_state") != "awaiting_named_human"
            or row.get("machine_preflight", {}).get("counts_as_human_reading") is not False
        ):
            raise First50OutputReviewError("first-output row identity or authority is invalid")
        ids.add(output_id)
        digests.add(artifact_sha256)
    if portfolio is not None:
        verify_lighthouse_portfolio(portfolio)
        if queue.get("source_portfolio_sha256") != portfolio.get("content_sha256"):
            raise First50OutputReviewError("first-output source portfolio drifted")
    if quality_portfolio is not None:
        if portfolio is None:
            raise First50OutputReviewError("quality verification requires its source portfolio")
        verify_lighthouse_quality_portfolio(quality_portfolio, portfolio=portfolio)
        if queue.get("source_quality_portfolio_sha256") != quality_portfolio.get("content_sha256"):
            raise First50OutputReviewError("first-output quality portfolio drifted")


def compile_first50_level1_seed_manifest(queue: Mapping[str, Any]) -> dict[str, Any]:
    verify_first50_output_review_queue(queue)
    cases: list[dict[str, Any]] = []
    for bucket_id, contract in FAILURE_BUCKETS.items():
        for row in queue["outputs"]:
            case = {
                "case_id": f"l1-{bucket_id}-{row['output_id']}",
                "failure_bucket": bucket_id,
                "source_output_id": row["output_id"],
                "source_artifact_sha256": row["artifact_sha256"],
                "mutation_contract": contract["mutation"],
                "oracle_contract": contract["oracle"],
                "expected_gate_result": False,
                "human_bucket_validation_observed": False,
                "ci_admission_allowed": False,
            }
            case["case_sha256"] = _digest(case)
            cases.append(case)
    manifest = _with_digest(
        {
            "schema": SEED_SCHEMA,
            "source_queue_sha256": queue["content_sha256"],
            "provisional_bucket_count": len(FAILURE_BUCKETS),
            "target_case_count_per_bucket": 50,
            "seed_case_count": len(cases),
            "bucket_case_counts": {
                bucket_id: 50 for bucket_id in FAILURE_BUCKETS
            },
            "human_validated_bucket_count": 0,
            "ci_admitted_case_count": 0,
            "t074_complete": False,
            "cases": cases,
            "truth_boundary": (
                "This manifest prepares 50 deterministic mutation seeds for each of ten provisional failure buckets. "
                "The buckets have not yet been derived or confirmed by a named human reading of the first fifty outputs, "
                "so none of the 500 seeds is admitted to CI and T074 remains incomplete."
            ),
        }
    )
    verify_first50_level1_seed_manifest(manifest, queue=queue)
    return manifest


def _prereview_bucket(row: Mapping[str, Any]) -> str:
    kind = str(row["artifact_kind"])
    if kind == "campaign_system":
        return "strategy_safe_but_not_commercially_sharp"
    if kind == "email":
        return "email_reviews_research_instead_of_progressing_lifecycle"
    if kind == "seo_page":
        return "seo_informs_but_weakly_converts"
    if kind == "video_script":
        return "video_proves_boundary_before_product_payoff"
    if kind == "geo_answer":
        return "geo_answer_lacks_live_citation_evidence"
    surface = str(row.get("surface") or "")
    if surface in {"linkedin", "reddit", "x"}:
        return "expert_copy_lacks_owner_specific_market_proof"
    if surface in {"tiktok", "instagram", "youtube"}:
        return "social_hook_leads_to_research_not_product_desire"
    return "search_asset_has_decision_tool_but_no_verified_offer_transition"


def _evidence_spans(row: Mapping[str, Any]) -> list[str]:
    payload = row["artifact_payload"]
    kind = row["artifact_kind"]
    keys_by_kind = {
        "campaign_system": ("organizing_idea", "proof_spine", "growth_loop"),
        "platform_asset": ("hook", "cta", "proof_and_limitation"),
        "email": ("subject", "cta", "body"),
        "seo_page": ("title", "hero", "cta"),
        "geo_answer": ("direct_answer", "evidence_boundary", "required_sources"),
    }
    spans: list[str] = []
    if kind == "video_script":
        shots = payload.get("shots", [])
        if isinstance(shots, list):
            for shot in (shots[:1] + shots[-1:]):
                if isinstance(shot, Mapping):
                    spans.append(
                        " | ".join(
                            str(shot.get(key, "")) for key in ("visual", "audio", "caption")
                        )[:500]
                    )
    else:
        for key in keys_by_kind.get(str(kind), ()):
            value = payload.get(key)
            if isinstance(value, list):
                value = " | ".join(str(item) for item in value)
            if value:
                spans.append(f"{key}: {value}"[:500])
    return spans[:3]


def compile_first50_codex_prereview(queue: Mapping[str, Any]) -> dict[str, Any]:
    """Locate quality hypotheses without impersonating the required named human read."""

    verify_first50_output_review_queue(queue)
    findings: list[dict[str, Any]] = []
    for row in queue["outputs"]:
        payload_text = _canonical(row["artifact_payload"]).casefold()
        bucket_id = _prereview_bucket(row)
        cross_cutting: list[str] = []
        if "synthetic" in payload_text:
            cross_cutting.append("synthetic_scaffolding_visible")
        if any(token in payload_text for token in ("research", "study", "inspect", "review")):
            cross_cutting.append("research_or_review_language_visible")
        if sum(payload_text.count(token) for token in ("unverified", "does not", "no ", "reject")) >= 3:
            cross_cutting.append("limitation_density_high")
        if not any(token in payload_text for token in ("customer", "owner-approved", "measured", "observed")):
            cross_cutting.append("owner_specific_market_proof_not_visible")
        findings.append(
            {
                "output_id": row["output_id"],
                "artifact_sha256": row["artifact_sha256"],
                "artifact_kind": row["artifact_kind"],
                "surface": row.get("surface"),
                "primary_bucket": bucket_id,
                "evidence_spans": _evidence_spans(row),
                "cross_cutting_hypotheses": cross_cutting,
                "recommended_repair": CODEX_PREREVIEW_BUCKETS[bucket_id]["repair"],
                "counts_as_named_human_read": False,
                "direct_publishability_decision_allowed": False,
            }
        )
    counts = Counter(row["primary_bucket"] for row in findings)
    prereview = _with_digest(
        {
            "schema": CODEX_PREREVIEW_SCHEMA,
            "source_queue_sha256": queue["content_sha256"],
            "review_mode": "codex_assisted_non_human_prereview",
            "finding_count": len(findings),
            "observed_primary_bucket_count": len(counts),
            "primary_bucket_counts": dict(sorted(counts.items())),
            "bucket_contracts": [
                {"bucket_id": key, **value}
                for key, value in CODEX_PREREVIEW_BUCKETS.items()
            ],
            "named_human_read_count": 0,
            "t073_complete": False,
            "reviewer_anchoring_control": (
                "Do not show these hypotheses to the independent named reviewer before their first-pass labels are sealed."
            ),
            "findings": findings,
            "truth_boundary": (
                "Codex located eight provisional quality patterns across all fifty frozen outputs. "
                "This accelerates repair planning but is not a named-human read, publishability judgment, preference result, release or market-effect proof."
            ),
        }
    )
    verify_first50_codex_prereview(prereview, queue=queue)
    return prereview


def verify_first50_codex_prereview(
    prereview: Mapping[str, Any], *, queue: Mapping[str, Any] | None = None
) -> None:
    _verify_digest(prereview, CODEX_PREREVIEW_SCHEMA)
    findings = prereview.get("findings")
    if (
        prereview.get("review_mode") != "codex_assisted_non_human_prereview"
        or prereview.get("finding_count") != 50
        or prereview.get("observed_primary_bucket_count") != 8
        or prereview.get("named_human_read_count") != 0
        or prereview.get("t073_complete") is not False
        or not isinstance(findings, list)
        or len(findings) != 50
    ):
        raise First50OutputReviewError("Codex prereview authority or coverage drifted")
    counts = Counter()
    pairs: set[tuple[str, str]] = set()
    for finding in findings:
        bucket = str(finding.get("primary_bucket", ""))
        pair = (str(finding.get("output_id", "")), str(finding.get("artifact_sha256", "")))
        if (
            bucket not in CODEX_PREREVIEW_BUCKETS
            or finding.get("counts_as_named_human_read") is not False
            or finding.get("direct_publishability_decision_allowed") is not False
            or not isinstance(finding.get("evidence_spans"), list)
            or not finding["evidence_spans"]
            or pair in pairs
        ):
            raise First50OutputReviewError("Codex prereview finding is invalid")
        counts[bucket] += 1
        pairs.add(pair)
    if dict(sorted(counts.items())) != prereview.get("primary_bucket_counts"):
        raise First50OutputReviewError("Codex prereview bucket counts drifted")
    if queue is not None:
        verify_first50_output_review_queue(queue)
        if prereview.get("source_queue_sha256") != queue.get("content_sha256"):
            raise First50OutputReviewError("Codex prereview source queue drifted")
        if pairs != {
            (row["output_id"], row["artifact_sha256"]) for row in queue["outputs"]
        }:
            raise First50OutputReviewError("Codex prereview output binding drifted")


def verify_first50_level1_seed_manifest(
    manifest: Mapping[str, Any], *, queue: Mapping[str, Any] | None = None
) -> None:
    _verify_digest(manifest, SEED_SCHEMA)
    cases = manifest.get("cases")
    if (
        manifest.get("provisional_bucket_count") != 10
        or manifest.get("target_case_count_per_bucket") != 50
        or manifest.get("seed_case_count") != 500
        or manifest.get("human_validated_bucket_count") != 0
        or manifest.get("ci_admitted_case_count") != 0
        or manifest.get("t074_complete") is not False
        or not isinstance(cases, list)
        or len(cases) != 500
    ):
        raise First50OutputReviewError("Level-1 seed manifest authority or count drifted")
    counts = Counter()
    case_ids: set[str] = set()
    case_digests: set[str] = set()
    for case in cases:
        unsigned = dict(case)
        supplied = unsigned.pop("case_sha256", None)
        bucket = str(case.get("failure_bucket", ""))
        if (
            supplied != _digest(unsigned)
            or bucket not in FAILURE_BUCKETS
            or case.get("human_bucket_validation_observed") is not False
            or case.get("ci_admission_allowed") is not False
            or case.get("expected_gate_result") is not False
            or case.get("case_id") in case_ids
            or supplied in case_digests
        ):
            raise First50OutputReviewError("Level-1 seed case is invalid")
        counts[bucket] += 1
        case_ids.add(case["case_id"])
        case_digests.add(supplied)
    if counts != Counter({bucket: 50 for bucket in FAILURE_BUCKETS}):
        raise First50OutputReviewError("Level-1 seed buckets are imbalanced")
    if queue is not None:
        verify_first50_output_review_queue(queue)
        if manifest.get("source_queue_sha256") != queue.get("content_sha256"):
            raise First50OutputReviewError("Level-1 seed source queue drifted")


def compile_named_human_read_receipt(
    queue: Mapping[str, Any],
    submission: Mapping[str, Any],
) -> dict[str, Any]:
    verify_first50_output_review_queue(queue)
    reviewer_name = str(submission.get("reviewer_name", "")).strip()
    reviewer_email = str(submission.get("reviewer_email", "")).strip().casefold()
    attestation = str(submission.get("attestation", "")).strip()
    if (
        len(reviewer_name) < 3
        or "synthetic" in reviewer_name.casefold()
        or "test" in reviewer_name.casefold()
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", reviewer_email)
        or reviewer_email.endswith("@example.test")
        or reviewer_email.endswith("@prooflaunch.local")
        or attestation != HUMAN_ATTESTATION
    ):
        raise First50OutputReviewError("named reviewer identity or attestation is invalid")
    raw_reviews = submission.get("reviews")
    if not isinstance(raw_reviews, list) or len(raw_reviews) != 50:
        raise First50OutputReviewError("named human receipt requires exactly 50 reviews")
    source_by_id = {row["output_id"]: row for row in queue["outputs"]}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_reviews:
        if not isinstance(raw, Mapping):
            raise First50OutputReviewError("human review row is invalid")
        output_id = str(raw.get("output_id", ""))
        source = source_by_id.get(output_id)
        failure_bucket = str(raw.get("failure_bucket", ""))
        if (
            source is None
            or output_id in seen
            or failure_bucket not in {*FAILURE_BUCKETS, "no_material_failure"}
            or type(raw.get("direct_publishable")) is not bool
            or type(raw.get("major_rework")) is not bool
            or type(raw.get("blocking_defect")) is not bool
        ):
            raise First50OutputReviewError("human review answer contract is invalid")
        evidence_span = re.sub(r"\s+", " ", str(raw.get("evidence_span", "")).strip())
        written_reason = re.sub(r"\s+", " ", str(raw.get("written_reason", "")).strip())
        if len(evidence_span) < 3 or len(evidence_span) > 500 or len(written_reason) < 20 or len(written_reason) > 2_000:
            raise First50OutputReviewError("human review evidence or reason is too thin")
        if failure_bucket == "no_material_failure" and (
            raw["major_rework"] or raw["blocking_defect"]
        ):
            raise First50OutputReviewError("no-material-failure conflicts with a major defect")
        normalized.append(
            {
                "output_id": output_id,
                "artifact_sha256": source["artifact_sha256"],
                "direct_publishable": raw["direct_publishable"],
                "major_rework": raw["major_rework"],
                "blocking_defect": raw["blocking_defect"],
                "failure_bucket": failure_bucket,
                "evidence_span": evidence_span,
                "written_reason": written_reason,
            }
        )
        seen.add(output_id)
    normalized.sort(key=lambda row: row["output_id"])
    bucket_counts = Counter(row["failure_bucket"] for row in normalized)
    observed_failure_buckets = sorted(
        bucket for bucket in bucket_counts if bucket != "no_material_failure"
    )
    t073_complete = len(observed_failure_buckets) in {8, 9, 10}
    receipt = _with_digest(
        {
            "schema": RECEIPT_SCHEMA,
            "source_queue_sha256": queue["content_sha256"],
            "reviewer": {"name": reviewer_name, "email": reviewer_email},
            "attestation": HUMAN_ATTESTATION,
            "review_count": 50,
            "direct_publishable_count": sum(row["direct_publishable"] for row in normalized),
            "major_rework_count": sum(row["major_rework"] for row in normalized),
            "blocking_defect_count": sum(row["blocking_defect"] for row in normalized),
            "observed_failure_bucket_count": len(observed_failure_buckets),
            "observed_failure_buckets": observed_failure_buckets,
            "bucket_counts": dict(sorted(bucket_counts.items())),
            "t073_complete": t073_complete,
            "reviews": normalized,
            "truth_boundary": (
                "This receipt proves one named person read the fifty frozen clean-room outputs and recorded located judgments. "
                "It does not by itself prove direct publishability, five-person preference, release, market effect, 4A quality or named-product superiority."
            ),
        }
    )
    verify_named_human_read_receipt(receipt, queue=queue)
    return receipt


def verify_named_human_read_receipt(
    receipt: Mapping[str, Any], *, queue: Mapping[str, Any] | None = None
) -> None:
    _verify_digest(receipt, RECEIPT_SCHEMA)
    reviews = receipt.get("reviews")
    reviewer = receipt.get("reviewer")
    if (
        not isinstance(reviewer, Mapping)
        or not isinstance(reviews, list)
        or len(reviews) != 50
        or receipt.get("review_count") != 50
        or receipt.get("attestation") != HUMAN_ATTESTATION
        or receipt.get("observed_failure_bucket_count")
        != len(receipt.get("observed_failure_buckets", []))
        or receipt.get("t073_complete")
        is not (receipt.get("observed_failure_bucket_count") in {8, 9, 10})
    ):
        raise First50OutputReviewError("named human receipt shape or T073 state is invalid")
    if queue is not None:
        verify_first50_output_review_queue(queue)
        if receipt.get("source_queue_sha256") != queue.get("content_sha256"):
            raise First50OutputReviewError("named human receipt source queue drifted")
        source_by_id = {row["output_id"]: row for row in queue["outputs"]}
        if {
            (row.get("output_id"), row.get("artifact_sha256")) for row in reviews
        } != {
            (output_id, row["artifact_sha256"])
            for output_id, row in source_by_id.items()
        }:
            raise First50OutputReviewError("named human receipt output binding drifted")


__all__ = [
    "FAILURE_BUCKETS",
    "CODEX_PREREVIEW_BUCKETS",
    "First50OutputReviewError",
    "HUMAN_ATTESTATION",
    "compile_named_human_read_receipt",
    "compile_first50_level1_seed_manifest",
    "compile_first50_codex_prereview",
    "compile_first50_output_review_queue",
    "verify_first50_level1_seed_manifest",
    "verify_first50_codex_prereview",
    "verify_first50_output_review_queue",
    "verify_named_human_read_receipt",
]
