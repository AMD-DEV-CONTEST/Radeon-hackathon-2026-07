from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Mapping, Sequence


class GTMBreakoutEvidenceError(ValueError):
    """A case, claim, or generalized mechanism escaped the evidence contract."""


SCHEMA = "ProofLaunchGTMBreakoutEvidenceCorpusV1"
COMPILED_SCHEMA = "ProofLaunchGTMBreakoutEvidenceLedgerV1"
EXPANDED_INDEX_SCHEMA = "ProofLaunchGTMBreakoutExpandedCaseIndexV2"
PROMOTION_QUEUE_SCHEMA = "ProofLaunchGTMBreakoutCasePromotionQueueV2"
EVIDENCE_GRADES = {"A", "B", "C", "D"}
CASE_KINDS = {"award_creative", "growth_claim", "research_constraint", "counterexample"}
CLAIM_STATUSES = {
    "official_result",
    "primary_self_report",
    "independent_secondary",
    "peer_reviewed_or_preprint",
    "anecdotal_unverified",
}
SPEND_STATUSES = {
    "paid_media_present",
    "paid_media_unknown",
    "mostly_organic_not_zero",
    "zero_paid_media_primary_verified",
    "zero_paid_media_self_report_only",
}
_DATE = re.compile(r"^20(?:2[0-6])-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: Any, field: str, minimum: int = 8) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise GTMBreakoutEvidenceError(f"{field} is missing or too thin")
    return value.strip()


def _list(value: Any, field: str, minimum_count: int = 1) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum_count:
        raise GTMBreakoutEvidenceError(f"{field} is incomplete")
    return value


def _verify_source(source: Mapping[str, Any], field: str) -> None:
    _text(source.get("title"), f"{field}.title")
    url = _text(source.get("url"), f"{field}.url")
    if not url.startswith("https://"):
        raise GTMBreakoutEvidenceError(f"{field}.url must be HTTPS")
    if source.get("source_class") not in {
        "award_body",
        "company_or_founder",
        "academic",
        "independent_media",
        "community_post",
    }:
        raise GTMBreakoutEvidenceError(f"{field}.source_class is unsupported")


def verify_evidence_corpus(corpus: Mapping[str, Any]) -> dict[str, Any]:
    if corpus.get("schema") != SCHEMA:
        raise GTMBreakoutEvidenceError("evidence schema is unsupported")
    if corpus.get("research_window") != {"start": "2020-01-01", "end": "2026-08-04"}:
        raise GTMBreakoutEvidenceError("research window drifted")

    cases = _list(corpus.get("cases"), "cases", 12)
    seen: set[str] = set()
    grade_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    business_counts: Counter[str] = Counter()
    industry_counts: Counter[str] = Counter()
    spend_counts: Counter[str] = Counter()

    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise GTMBreakoutEvidenceError(f"cases[{index}] is invalid")
        case_id = _text(case.get("case_id"), f"cases[{index}].case_id", 4)
        if case_id in seen:
            raise GTMBreakoutEvidenceError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        observed_on = _text(case.get("observed_on"), f"cases[{index}].observed_on")
        if not _DATE.fullmatch(observed_on) or not "2020-01-01" <= observed_on <= "2026-08-04":
            raise GTMBreakoutEvidenceError(f"{case_id} falls outside the research window")
        grade = case.get("evidence_grade")
        kind = case.get("case_kind")
        status = case.get("claim_status")
        spend = case.get("spend_status")
        if grade not in EVIDENCE_GRADES or kind not in CASE_KINDS:
            raise GTMBreakoutEvidenceError(f"{case_id} has an unsupported evidence class")
        if status not in CLAIM_STATUSES or spend not in SPEND_STATUSES:
            raise GTMBreakoutEvidenceError(f"{case_id} has an unsupported claim/spend status")
        if grade == "A" and status not in {"official_result", "peer_reviewed_or_preprint"}:
            raise GTMBreakoutEvidenceError(f"{case_id} overstates grade A evidence")
        if spend == "zero_paid_media_primary_verified" and status not in {"official_result", "peer_reviewed_or_preprint"}:
            raise GTMBreakoutEvidenceError(f"{case_id} overstates a zero-paid-media claim")
        for field in ("market", "company", "campaign_or_study", "industry", "business_model"):
            _text(case.get(field), f"cases[{index}].{field}", 2)
        if case.get("business_model") not in {"b2b", "b2c", "mixed", "research"}:
            raise GTMBreakoutEvidenceError(f"{case_id} has an unsupported business model")
        for source_index, source in enumerate(_list(case.get("sources"), f"{case_id}.sources")):
            if not isinstance(source, Mapping):
                raise GTMBreakoutEvidenceError(f"{case_id}.sources[{source_index}] is invalid")
            _verify_source(source, f"{case_id}.sources[{source_index}]")
        for field in (
            "verified_claims",
            "excluded_or_unverified_claims",
            "mechanism_observations",
            "causal_confounds",
            "transferable_primitives",
            "nontransferable_context",
        ):
            for item_index, item in enumerate(_list(case.get(field), f"{case_id}.{field}")):
                _text(item, f"{case_id}.{field}[{item_index}]", 12)
        measurement = case.get("measurement")
        if not isinstance(measurement, Mapping):
            raise GTMBreakoutEvidenceError(f"{case_id}.measurement is required")
        for field in ("baseline", "window", "outcome", "revenue_link"):
            _text(measurement.get(field), f"{case_id}.measurement.{field}", 5)
        if case.get("verbatim_copy_reuse_allowed") is not False:
            raise GTMBreakoutEvidenceError(f"{case_id} permits reference-copy reuse")
        grade_counts[grade] += 1
        kind_counts[kind] += 1
        business_counts[str(case["business_model"])] += 1
        industry_counts[str(case["industry"])] += 1
        spend_counts[str(spend)] += 1

    mechanisms = _list(corpus.get("generalized_mechanisms"), "generalized_mechanisms", 6)
    mechanism_ids: set[str] = set()
    for index, mechanism in enumerate(mechanisms):
        if not isinstance(mechanism, Mapping):
            raise GTMBreakoutEvidenceError(f"generalized_mechanisms[{index}] is invalid")
        mechanism_id = _text(mechanism.get("mechanism_id"), f"mechanisms[{index}].mechanism_id", 4)
        if mechanism_id in mechanism_ids:
            raise GTMBreakoutEvidenceError(f"duplicate mechanism_id: {mechanism_id}")
        mechanism_ids.add(mechanism_id)
        evidence_case_ids = _list(mechanism.get("evidence_case_ids"), f"{mechanism_id}.evidence_case_ids", 2)
        if len(set(evidence_case_ids)) != len(evidence_case_ids) or not set(evidence_case_ids).issubset(seen):
            raise GTMBreakoutEvidenceError(f"{mechanism_id} cites invalid evidence")
        for field in (
            "mechanism",
            "when_it_works",
            "when_it_fails",
            "b2b_adaptation",
            "b2c_adaptation",
            "generation_rule",
            "measurement_rule",
        ):
            _text(mechanism.get(field), f"{mechanism_id}.{field}", 20)
        if mechanism.get("claim_zero_paid_media") is not False:
            raise GTMBreakoutEvidenceError(f"{mechanism_id} promotes an unproven zero-spend claim")

    industry_language = _list(corpus.get("industry_language_contracts"), "industry_language_contracts", 8)
    for index, contract in enumerate(industry_language):
        if not isinstance(contract, Mapping):
            raise GTMBreakoutEvidenceError(f"industry_language_contracts[{index}] is invalid")
        for field in (
            "segment",
            "buyer_or_user",
            "decision_tension",
            "proof_language",
            "native_voice",
            "forbidden_shortcut",
        ):
            _text(contract.get(field), f"industry_language_contracts[{index}].{field}", 8)

    return {
        "case_count": len(cases),
        "mechanism_count": len(mechanisms),
        "industry_language_contract_count": len(industry_language),
        "grade_counts": dict(sorted(grade_counts.items())),
        "kind_counts": dict(sorted(kind_counts.items())),
        "business_model_counts": dict(sorted(business_counts.items())),
        "industry_counts": dict(sorted(industry_counts.items())),
        "spend_status_counts": dict(sorted(spend_counts.items())),
        "verified_zero_paid_media_case_count": spend_counts["zero_paid_media_primary_verified"],
    }


def compile_evidence_ledger(corpus: Mapping[str, Any]) -> dict[str, Any]:
    audit = verify_evidence_corpus(corpus)
    payload: dict[str, Any] = {
        "schema": COMPILED_SCHEMA,
        "status": "research_seed_verified_for_mechanism_use_not_outcome_prediction",
        "research_window": corpus["research_window"],
        "audit": audit,
        "cases": corpus["cases"],
        "generalized_mechanisms": corpus["generalized_mechanisms"],
        "industry_language_contracts": corpus["industry_language_contracts"],
        "training_policy": corpus["training_policy"],
        "truth_boundary": (
            "Award recognition validates creative judgment, not zero spend or causality. Company and founder metrics remain "
            "self-reported unless independently audited. No case authorizes revenue prediction, reference-copy reuse, "
            "inauthentic engagement, or automated publishing."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_evidence_ledger(ledger: Mapping[str, Any]) -> None:
    unsigned = dict(ledger)
    supplied = unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or not _SHA.fullmatch(supplied) or supplied != _digest(unsigned):
        raise GTMBreakoutEvidenceError("compiled evidence digest is invalid")
    corpus = {
        "schema": SCHEMA,
        "research_window": ledger.get("research_window"),
        "cases": ledger.get("cases"),
        "generalized_mechanisms": ledger.get("generalized_mechanisms"),
        "industry_language_contracts": ledger.get("industry_language_contracts"),
        "training_policy": ledger.get("training_policy"),
    }
    rebuilt = compile_evidence_ledger(corpus)
    if rebuilt != ledger:
        raise GTMBreakoutEvidenceError("compiled evidence aggregates drifted")


def load_and_compile(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        source = json.load(handle)
    return compile_evidence_ledger(source)


def compile_expanded_case_index(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(cases) < 60:
        raise GTMBreakoutEvidenceError("expanded discovery index requires at least sixty named cases")
    seen: set[str] = set()
    years: Counter[int] = Counter()
    models: Counter[str] = Counter()
    industries: Counter[str] = Counter()
    sources: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(cases):
        case = dict(raw)
        case_id = _text(case.get("case_id"), f"expanded_cases[{index}].case_id", 4)
        if case_id in seen:
            raise GTMBreakoutEvidenceError(f"duplicate expanded case_id: {case_id}")
        seen.add(case_id)
        year = case.get("year")
        if not isinstance(year, int) or not 2020 <= year <= 2026:
            raise GTMBreakoutEvidenceError(f"{case_id} has an invalid year")
        for field in ("campaign", "brand", "award_category", "industry_family", "geography"):
            _text(case.get(field), f"{case_id}.{field}", 2)
        if case.get("business_model") not in {"b2b", "b2c", "mixed", "public_interest"}:
            raise GTMBreakoutEvidenceError(f"{case_id} has an invalid business model")
        source_url = _text(case.get("source_url"), f"{case_id}.source_url")
        if not source_url.startswith("https://"):
            raise GTMBreakoutEvidenceError(f"{case_id} source must be HTTPS")
        if case.get("source_class") != "official_award_body":
            raise GTMBreakoutEvidenceError(f"{case_id} lacks official award-body provenance")
        if case.get("promotion_status") != "pending_case_level_claim_audit" or case.get("training_eligible") is not False:
            raise GTMBreakoutEvidenceError(f"{case_id} escaped the discovery-only boundary")
        if case.get("english_market_transfer_requires_local_validation") is not True:
            raise GTMBreakoutEvidenceError(f"{case_id} bypasses English-market validation")
        required = _list(case.get("required_next_evidence"), f"{case_id}.required_next_evidence", 5)
        if set(required) != {"baseline", "spend_scope", "time_window", "outcome_chain", "causal_confounds"}:
            raise GTMBreakoutEvidenceError(f"{case_id} promotion evidence is incomplete")
        case["verified_scope"] = "Official award-body page confirms the named work/category context only; metrics and causal claims require case-level audit."
        normalized.append(case)
        years[year] += 1
        models[str(case["business_model"])] += 1
        industries[str(case["industry_family"])] += 1
        sources.add(source_url)
    payload: dict[str, Any] = {
        "schema": EXPANDED_INDEX_SCHEMA,
        "status": "discovery_only_not_training_eligible",
        "research_window": {"start": "2020-01-01", "end": "2026-08-04"},
        "case_count": len(normalized),
        "official_source_page_count": len(sources),
        "year_counts": {str(key): value for key, value in sorted(years.items())},
        "business_model_counts": dict(sorted(models.items())),
        "industry_family_counts": dict(sorted(industries.items())),
        "cases": normalized,
        "promotion_contract": {
            "destination": COMPILED_SCHEMA,
            "required_case_level_fields": ["baseline", "spend_scope", "time_window", "outcome_chain", "causal_confounds"],
            "automatic_promotion_allowed": False,
            "human_evidence_review_required": True,
            "copy_or_voice_reuse_allowed": False,
        },
        "truth_boundary": (
            "This expanded index increases named-case breadth without pretending that an award listing proves spend, causality, "
            "organic growth, conversion, revenue, or English-market transferability."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_expanded_case_index(index: Mapping[str, Any]) -> None:
    unsigned = dict(index)
    supplied = unsigned.pop("content_sha256", None)
    if index.get("schema") != EXPANDED_INDEX_SCHEMA or supplied != _digest(unsigned):
        raise GTMBreakoutEvidenceError("expanded index digest or schema is invalid")
    rebuilt = compile_expanded_case_index(index.get("cases", []))
    if rebuilt != index:
        raise GTMBreakoutEvidenceError("expanded case aggregates drifted")


def compile_case_promotion_queue(index: Mapping[str, Any]) -> dict[str, Any]:
    verify_expanded_case_index(index)
    high_value_terms = (
        "b2b",
        "industrial",
        "manufactur",
        "engineering",
        "construction",
        "real estate",
        "software",
        "financial",
        "banking",
        "professional",
        "agriculture",
        "supply chain",
        "medical",
    )
    english_priority_terms = (
        "United States",
        "United Kingdom",
        "Canada",
        "Australia",
        "New Zealand",
        "Singapore",
        "Ireland",
        "Global",
    )
    task_specs = {
        "baseline": "Record the pre-campaign comparator, denominator, and observation date.",
        "spend_scope": "Separate paid media, production, talent, affiliate, sponsorship, owned inventory, and labour.",
        "time_window": "Record campaign start/end dates and the exact outcome observation window.",
        "outcome_chain": "Separate reach, qualified engagement, activation, retention, conversion, and revenue evidence.",
        "causal_confounds": "Record seasonality, launches, pricing, distribution, PR, partnerships, and concurrent media.",
    }
    queue: list[dict[str, Any]] = []
    task_count = 0
    for case in index["cases"]:
        searchable = f"{case['business_model']} {case['industry_family']}".casefold()
        priority_score = 30 if case["business_model"] == "b2b" else 10
        priority_score += 10 * sum(term in searchable for term in high_value_terms)
        priority_score += 10 if any(term in case["geography"] for term in english_priority_terms) else 0
        priority_score += max(0, int(case["year"]) - 2022)
        tasks = [
            {
                "evidence_type": evidence_type,
                "status": "missing_case_level_evidence",
                "acceptance_requirement": requirement,
                "automatic_inference_allowed": False,
            }
            for evidence_type, requirement in task_specs.items()
        ]
        task_count += len(tasks)
        queue.append(
            {
                "case_id": case["case_id"],
                "campaign": case["campaign"],
                "brand": case["brand"],
                "year": case["year"],
                "business_model": case["business_model"],
                "industry_family": case["industry_family"],
                "geography": case["geography"],
                "source_url": case["source_url"],
                "priority_score": priority_score,
                "priority_band": "p0" if priority_score >= 55 else "p1" if priority_score >= 35 else "p2",
                "promotion_status": "blocked_pending_five_evidence_tasks",
                "training_eligible": False,
                "tasks": tasks,
            }
        )
    queue.sort(key=lambda item: (-item["priority_score"], -item["year"], item["case_id"]))
    payload: dict[str, Any] = {
        "schema": PROMOTION_QUEUE_SCHEMA,
        "source_index_sha256": index["content_sha256"],
        "case_count": len(queue),
        "audit_unit_count": task_count,
        "priority_band_counts": dict(sorted(Counter(item["priority_band"] for item in queue).items())),
        "queue": queue,
        "promotion_gate": {
            "all_five_tasks_required": True,
            "human_evidence_review_required": True,
            "causal_or_zero_spend_claim_from_award_listing_allowed": False,
            "training_promotion_is_manual": True,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_promotion_queue(queue: Mapping[str, Any], index: Mapping[str, Any]) -> None:
    unsigned = dict(queue)
    supplied = unsigned.pop("content_sha256", None)
    if queue.get("schema") != PROMOTION_QUEUE_SCHEMA or supplied != _digest(unsigned):
        raise GTMBreakoutEvidenceError("promotion queue digest or schema is invalid")
    rebuilt = compile_case_promotion_queue(index)
    if rebuilt != queue:
        raise GTMBreakoutEvidenceError("promotion queue drifted from its expanded index")
