#!/usr/bin/env python3
"""Merge company-isolated IR runs into one deterministic private corpus."""

from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import re
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--collection", type=Path, action="append", required=True)
    parser.add_argument("--transform", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def unique(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        value = record[key]
        if value in by_key and by_key[value] != record:
            raise ValueError(f"conflicting {key}: {value}")
        by_key[value] = record
    return [by_key[value] for value in sorted(by_key)]


def inferred_years(document: dict[str, Any]) -> list[int]:
    text = document["title"] + " " + document["canonical_uri"]
    years = {int(value) for value in re.findall(r"\b(20[0-9]{2})\b", text)}
    years.update(2000 + int(value) for value in re.findall(r"\bFY[' -]?([2-9][0-9])\b", text, re.IGNORECASE))
    return sorted(years)


def main() -> int:
    args = parse_args()
    if len(args.collection) != len(args.transform):
        raise SystemExit("collection and transform directory counts must match")
    registry = json.loads(args.registry.read_text())
    observations: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    for collection, transform in zip(args.collection, args.transform):
        observations.extend(read_jsonl(collection / "crawl-observations.jsonl"))
        documents.extend(read_jsonl(collection / "documents.jsonl"))
        chunks.extend(read_jsonl(transform / "chunks.jsonl"))
        projections.extend(read_jsonl(transform / "semantic-projections.jsonl"))
    documents = unique(documents, "document_id")
    chunks = unique(chunks, "chunk_id")
    projections = unique(projections, "projection_id")
    document_ids = {item["document_id"] for item in documents}
    if any(item["document_id"] not in document_ids for item in chunks):
        raise SystemExit("chunk references a document outside the merged corpus")
    ticker_by_company = {item["company_id"]: item["primary_ticker"] for item in registry["sources"]}
    company_coverage = []
    for source in registry["sources"]:
        company_documents = [item for item in documents if item["company_id"] == source["company_id"]]
        company_chunks = [item for item in chunks if item["company_id"] == source["company_id"]]
        present = sorted({item["document_type"] for item in company_documents})
        years = sorted({year for item in company_documents for year in inferred_years(item)})
        required_years = set(range(registry["historical_policy"]["complete_window_start_year"], dt.datetime.now(dt.timezone.utc).year + 1))
        company_coverage.append(
            {
                "ticker": source["primary_ticker"],
                "company_id": source["company_id"],
                "document_count": len(company_documents),
                "chunk_count": len(company_chunks),
                "present_material_classes": present,
                "missing_material_classes": sorted(set(registry["material_classes"]) - set(present)),
                "inferred_archive_years": years,
                "missing_inferred_archive_years": sorted(required_years - set(years)),
            }
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "crawl-observations.jsonl", observations)
    write_jsonl(args.output_dir / "documents.jsonl", documents)
    write_jsonl(args.output_dir / "chunks.jsonl", chunks)
    write_jsonl(args.output_dir / "semantic-projections.jsonl", projections)
    report = {
        "schema_version": "signalforge/ir-corpus-coverage/v1",
        "issuer_count": len(registry["sources"]),
        "issuers_with_documents": sum(item["document_count"] > 0 for item in company_coverage),
        "observation_count": len(observations),
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "projection_count": len(projections),
        "documents_by_class": dict(sorted(Counter(item["document_type"] for item in documents).items())),
        "chunks_by_ticker": dict(sorted(Counter(ticker_by_company[item["company_id"]] for item in chunks).items())),
        "company_coverage": company_coverage,
        "claim_boundary": "Coverage measures bounded discovery and parsing, not complete issuer archives or rights approval.",
    }
    (args.output_dir / "coverage.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("issuers_with_documents", "document_count", "chunk_count", "projection_count")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
