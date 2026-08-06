from __future__ import annotations

import hashlib
import html
import json
from typing import Any, Mapping


CONFIG_SCHEMA = "ProofLaunchCodexSearchAnswerSuperChallengersDraftV1"
SEO_SCHEMA = "ProofLaunchSEONamedPKSuperChallengerV1"
GEO_SCHEMA = "ProofLaunchGEONamedPKSuperChallengerV1"


class SearchAnswerNamedPKError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = _digest(result)
    return result


def compile_search_answer(config: Mapping[str, Any], *, evidence: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], str]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise SearchAnswerNamedPKError("search-answer config schema drifted")
    page = config.get("page")
    faqs = config.get("faqs")
    panel = config.get("geo_measurement_panel")
    if not isinstance(page, Mapping) or not isinstance(faqs, list) or len(faqs) != 6 or not isinstance(panel, Mapping):
        raise SearchAnswerNamedPKError("search-answer content is incomplete")
    if len(config.get("seo_opponent_stress_tests", {})) != 10 or len(config.get("geo_opponent_stress_tests", {})) != 10:
        raise SearchAnswerNamedPKError("named search-product coverage drifted")
    if panel.get("status") != "not_run" or panel.get("automatic_query_execution") is not False or panel.get("automatic_content_mutation") is not False:
        raise SearchAnswerNamedPKError("unobserved GEO measurement was promoted")
    if len(evidence) < 3 or any(not row.get("sha256") for row in evidence):
        raise SearchAnswerNamedPKError("search-answer evidence binding is incomplete")
    common = {
        "campaign_id": "prooflaunch-rejection-rule-v9",
        "evidence_bindings": evidence,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "external_publish_executed": False,
        "truth_boundary": config["truth_boundary"],
    }
    seo = _seal({
        "schema": SEO_SCHEMA,
        **common,
        "owned_page": {"route": page["route"], "canonical": "https://prooflaunch.local" + page["route"], "indexability": "noindex_until_named_human_release", "intent": page["search_intent"], "title": page["title"], "h1": page["h1"], "meta_description": page["meta_description"]},
        "structured_data": {"types": ["WebPage", "SoftwareApplication", "FAQPage"], "claim_citations_required": True, "validation_status": "local_draft_not_deployed"},
        "internal_link_graph": list(page["internal_links"]),
        "performance_audit": {"lighthouse_observed": False, "siteone_observed": False, "runtime_external_resources": 0, "replay_required_after_deployment": True},
        "crawl_audit": {"local_document_compiled": True, "robots_state": "noindex", "deployment_observed": False, "crawl_observed": False, "ranking_observed": False},
        "content_brief": {"answer_first": True, "search_intent": page["search_intent"], "direct_answer": page["direct_answer"], "approved_product_fact": page["approved_product_fact"], "evaluation_steps": list(page["evaluation_steps"]), "nonfit": page["nonfit"], "duplicate_intent_policy": "one canonical owner", "keyword_stuffing_allowed": False},
        "opponent_stress_tests": dict(config["seo_opponent_stress_tests"]),
        "open_source_modifications": list(config["open_source_modifications"]["seo"]),
        "measured_organic_delta": None,
    })
    geo_faqs = []
    for row in faqs:
        geo_faqs.append({"question": row["question"], "answer_draft": row["answer"], "citation": {"evidence_sha256": evidence[0]["sha256"], "evidence_path": evidence[0]["path"]}, "truth_status": "draft_only"})
    geo = _seal({
        "schema": GEO_SCHEMA,
        **common,
        "entity": {"name": "ProofLaunch Cortex-X", "approved_fact": page["approved_product_fact"], "unobserved": ["preference", "reach", "conversion", "revenue", "named-product superiority"]},
        "direct_answer": page["direct_answer"],
        "faqs": geo_faqs,
        "measurement_panel": dict(panel),
        "opponent_stress_tests": dict(config["geo_opponent_stress_tests"]),
        "open_source_modifications": list(config["open_source_modifications"]["geo"]),
        "measured_answer_share": None,
        "measured_citation_share": None,
    })
    faq_schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": row["question"], "acceptedAnswer": {"@type": "Answer", "text": row["answer"]}} for row in faqs]}
    steps = "".join(f"<li><h2>{html.escape(row['name'])}</h2><p>{html.escape(row['test'])}</p><p><strong>Failure:</strong> {html.escape(row['failure'])}</p></li>" for row in page["evaluation_steps"])
    faq_html = "".join(f"<details><summary>{html.escape(row['question'])}</summary><p>{html.escape(row['answer'])}</p></details>" for row in faqs)
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(page['title'])}</title><meta name="description" content="{html.escape(page['meta_description'])}"><meta name="robots" content="noindex,nofollow"><script type="application/ld+json">{json.dumps(faq_schema, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')}</script><style>:root{{--bg:#080b12;--panel:#111725;--ink:#f3f6ff;--muted:#aeb8ce;--line:#303b54;--violet:#a88cff;--amber:#f2ab3a}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 Inter,system-ui,sans-serif}}main{{max-width:980px;margin:auto;padding:56px 24px 96px}}header,section,details{{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:28px;margin:0 0 22px}}h1{{font-size:clamp(42px,7vw,78px);line-height:.98;letter-spacing:-.055em}}h2{{font-size:24px}}.answer{{font-size:24px;border-left:5px solid var(--amber);padding-left:20px}}.fact{{color:var(--violet)}}li{{margin-bottom:26px}}summary{{font-weight:800;cursor:pointer}}</style></head><body><main><header><p>PROOFLAUNCH · DECISION GUIDE</p><h1>{html.escape(page['h1'])}</h1><p class="answer">{html.escape(page['direct_answer'])}</p><p class="fact">Approved product fact: {html.escape(page['approved_product_fact'])}</p></header><section><h2>Five tests before authority</h2><ol>{steps}</ol></section><section><h2>When this is not a fit</h2><p>{html.escape(page['nonfit'])}</p></section><section><h2>Questions buyers should ask</h2>{faq_html}</section></main></body></html>'''
    return seo, geo, document


def verify(payload: Mapping[str, Any], schema: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != schema or supplied != _digest(unsigned):
        raise SearchAnswerNamedPKError("search-answer seal is invalid")
    if payload.get("completed_named_product_pk_count") != 0 or payload.get("candidate_win_count") != 0 or payload.get("external_publish_executed") is not False:
        raise SearchAnswerNamedPKError("search-answer truth boundary drifted")


__all__ = ["GEO_SCHEMA", "SEO_SCHEMA", "SearchAnswerNamedPKError", "compile_search_answer", "verify"]
