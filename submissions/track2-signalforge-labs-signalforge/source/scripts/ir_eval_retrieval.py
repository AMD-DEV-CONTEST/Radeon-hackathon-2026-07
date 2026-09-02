#!/usr/bin/env python3
"""Evaluate filtered BM25 over the private IR silver population."""

from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
import math
from pathlib import Path
import re
from typing import Any


TOKEN = re.compile(r"[a-z0-9]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("development", "sealed_holdout", "all"), default="all")
    return parser.parse_args()


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def bm25(query: str, chunks: list[dict[str, Any]]) -> list[tuple[float, str]]:
    if not chunks:
        return []
    terms = tokens(query)
    frequencies = [Counter(tokens(item["section"] + " " + item["text"])) for item in chunks]
    lengths = [sum(value.values()) for value in frequencies]
    average = sum(lengths) / len(lengths)
    document_frequency = Counter(term for term in set(terms) for value in frequencies if term in value)
    scored: list[tuple[float, str]] = []
    for chunk, frequency, length in zip(chunks, frequencies, lengths):
        value = 0.0
        for term in terms:
            count = frequency[term]
            if not count:
                continue
            inverse = math.log(1 + (len(chunks) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            value += inverse * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / max(1, average)))
        if value > 0:
            scored.append((value, chunk["chunk_id"]))
    return sorted(scored, key=lambda item: (-item[0], item[1]))


def main() -> int:
    args = parse_args()
    evaluation = json.loads(args.eval.read_text())
    questions = [item for item in evaluation["questions"] if args.split == "all" or item["split"] == args.split]
    chunks = evaluation["chunks"]
    recall = precision = complete = citation = context = 0.0
    abstain_correct = answerable = abstentions = 0
    results: list[dict[str, Any]] = []
    chunk_by_id = {item["chunk_id"]: item for item in chunks}
    for question in questions:
        eligible = [
            item for item in chunks
            if item["company_id"] in question["company_ids"] and item["document_type"] in question["document_types"]
            and parse_time(item["available_at"]) <= parse_time(question["as_of"])
        ]
        hits = [item[1] for item in bm25(question["text"], eligible)[: question["top_k"]]]
        relevant = set(question["relevant_chunk_ids"])
        found = relevant.intersection(hits)
        if question["expected_abstain"]:
            abstentions += 1
            abstain_correct += not hits
        else:
            answerable += 1
            recall += len(found) / len(relevant)
            precision += len(found) / len(hits) if hits else 0
            complete += found == relevant
        citation += sum(item in chunk_by_id for item in hits) / len(hits) if hits else 1
        context += sum(chunk_by_id[item]["token_estimate"] for item in hits)
        results.append({"question_id": question["question_id"], "hit_ids": hits, "missing_ids": sorted(relevant - found)})
    report = {
        "schema_version": "signalforge/ir-retrieval-benchmark/v1",
        "method": "bm25-filtered/v1",
        "split": args.split,
        "question_count": len(questions),
        "answerable_count": answerable,
        "abstention_count": abstentions,
        "metrics": {
            "recall_at_k": recall / answerable if answerable else 0,
            "precision_at_k": precision / answerable if answerable else 0,
            "complete_evidence_rate": complete / answerable if answerable else 0,
            "abstention_accuracy": abstain_correct / abstentions if abstentions else 1,
            "citation_correctness": citation / len(questions) if questions else 0,
            "mean_context_tokens": context / len(questions) if questions else 0,
        },
        "results": results,
        "claim_boundary": "Silver labels are a pipeline-development baseline, not product retrieval accuracy.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["metrics"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
