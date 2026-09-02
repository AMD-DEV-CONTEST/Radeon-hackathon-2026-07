#!/usr/bin/env python3
"""Build a reproducible 160-intent silver retrieval population for 20 issuers."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from typing import Any


INTENTS = {
    "history": {
        "question": "What official evidence explains {issuer}'s company history?",
        "keywords": ("history", "founded", "established", "company"),
        "classes": ("corporate_profile_and_history",),
    },
    "products_segments": {
        "question": "What does {issuer} sell, and how does it describe its products or business segments?",
        "keywords": ("product", "platform", "service", "customer", "segment", "business"),
        "classes": ("business_products_and_segments", "corporate_profile_and_history", "official_strategy_or_risk_update"),
    },
    "strategy": {
        "question": "What strategic priorities does management describe for {issuer}?",
        "keywords": ("strategy", "priority", "investment", "growth", "innovation"),
        "classes": ("official_strategy_or_risk_update", "investor_presentation", "shareholder_letter"),
    },
    "earnings_explanation": {
        "question": "How does management explain {issuer}'s latest reported results?",
        "keywords": ("earnings", "revenue", "margin", "results", "driven"),
        "classes": ("earnings_release", "prepared_remarks", "official_earnings_transcript"),
    },
    "guidance": {
        "question": "What outlook or guidance has {issuer} officially communicated?",
        "keywords": ("outlook", "guidance", "expect", "forecast", "forward-looking"),
        "classes": ("guidance_and_outlook", "prepared_remarks", "earnings_release", "investor_presentation"),
    },
    "risk": {
        "question": "What risks or uncertainties does {issuer} emphasize in official investor material?",
        "keywords": ("risk", "uncertainty", "competition", "regulation", "challenge"),
        "classes": ("official_strategy_or_risk_update", "investor_presentation", "prepared_remarks"),
    },
    "governance": {
        "question": "What official evidence describes {issuer}'s governance and board oversight?",
        "keywords": ("governance", "board", "committee", "oversight", "director"),
        "classes": ("governance_document", "board_and_committee_material", "annual_meeting_material"),
    },
    "capital_allocation": {
        "question": "How does {issuer} describe capital allocation to investors?",
        "keywords": ("capital allocation", "dividend", "repurchase", "investment", "shareholder"),
        "classes": ("capital_allocation_update", "earnings_release", "investor_presentation", "shareholder_letter"),
    },
}
TOKEN = re.compile(r"[a-z0-9]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--population-version", default="v3")
    parser.add_argument("--as-of", required=True, help="RFC3339 point-in-time boundary")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def score(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(lowered.count(keyword) for keyword in keywords)


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def main() -> int:
    args = parse_args()
    registry = json.loads(args.registry.read_text())
    documents = read_jsonl(args.documents)
    chunks = read_jsonl(args.chunks)
    try:
        as_of = parse_time(args.as_of)
    except ValueError as error:
        raise SystemExit(f"invalid --as-of: {error}") from error
    document_by_id = {item["document_id"]: item for item in documents}
    by_company: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        by_company.setdefault(chunk["company_id"], []).append(chunk)
    questions: list[dict[str, Any]] = []
    for source in registry["sources"]:
        company_chunks = [
            item for item in by_company.get(source["company_id"], [])
            if parse_time(item["available_at"]) <= as_of
        ]
        for intent, policy in INTENTS.items():
            eligible = [item for item in company_chunks if item["document_type"] in policy["classes"]]
            ranked = sorted(
                eligible,
                key=lambda item: (-score(item["section"] + " " + item["text"], policy["keywords"]), item["chunk_id"]),
            )
            relevant = [item["chunk_id"] for item in ranked[:2]]
            identity = f"{source['company_id']}:{intent}"
            questions.append(
                {
                    "question_id": "irq-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                    "intent": intent,
                    "text": policy["question"].format(issuer=source["issuer"]),
                    "company_ids": [source["company_id"]],
                    "document_types": list(policy["classes"]),
                    "top_k": 5,
                    "as_of": args.as_of,
                    "relevant_chunk_ids": relevant,
                    "expected_abstain": not relevant,
                    "label_status": "silver_deterministic_bootstrap",
                }
            )
    questions.sort(key=lambda item: hashlib.sha256((f"split-{args.population_version}:" + item["question_id"]).encode()).hexdigest())
    for index, question in enumerate(questions):
        question["split"] = "development" if index < 100 else "sealed_holdout"
    report = {
        "schema_version": "signalforge/ir-retrieval-eval/v1",
        "population_id": f"us-technology-20-eight-intents-{args.population_version}",
        "as_of": args.as_of,
        "question_count": len(questions),
        "development_count": 100,
        "sealed_holdout_count": 60,
        "label_authority": "silver; deterministic bootstrap requiring human adjudication before product claims",
        "documents": documents,
        "chunks": chunks,
        "questions": questions,
    }
    if len(questions) != 160:
        raise SystemExit(f"expected 160 questions, got {len(questions)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"question_count": 160, "answerable": sum(not item["expected_abstain"] for item in questions), "abstain": sum(item["expected_abstain"] for item in questions)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
