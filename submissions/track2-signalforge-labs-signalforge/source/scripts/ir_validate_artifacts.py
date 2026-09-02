#!/usr/bin/env python3
"""Validate IR registries, ledgers, documents, chunks, and silent projections."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


FINANCIAL_LITERAL = re.compile(
    r"(?<![A-Za-z0-9_])-?\d{1,3}(?:\.\d+)?\s+(?:to|through|[-–—])\s+-?\d{1,3}(?:\.\d+)?"
    r"(?=\s+(?:in\s+constant\s+currency|percent(?:age)?|bps?\b|million\b|billion\b|trillion\b))"
    r"|(?:[$€£]\s*)-?\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:million|billion|trillion|(?-i:[MBTK])))?"
    r"|(?<![A-Za-z0-9_])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:\s*(?:%|bps?|million|billion|trillion|(?-i:[MBTK])))?"
    r"|(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?\s*(?:%|bps?|million|billion|trillion|(?-i:[MBTKxX]))",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--contracts", type=Path, default=Path("contracts"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(json.loads(path.read_text()), format_checker=FormatChecker())


def validate_records(records: list[dict[str, Any]], schema: Draft202012Validator, label: str) -> list[str]:
    errors: list[str] = []
    for index, record in enumerate(records, 1):
        for error in sorted(schema.iter_errors(record), key=lambda item: list(item.path)):
            errors.append(f"{label}:{index}:{'/'.join(map(str, error.path))}:{error.message}")
    return errors


def main() -> int:
    args = parse_args()
    registry = json.loads(args.registry.read_text())
    observations = read_jsonl(args.observations)
    documents = read_jsonl(args.documents)
    chunks = read_jsonl(args.chunks)
    projections = read_jsonl(args.projections)
    errors: list[str] = []
    errors.extend(validate_records([registry], validator(args.contracts / "ir-source-registry-v2.schema.json"), "registry"))
    errors.extend(validate_records(observations, validator(args.contracts / "ir-crawl-observation.schema.json"), "observation"))
    errors.extend(validate_records(documents, validator(args.contracts / "ir-document-v2.schema.json"), "document"))
    errors.extend(validate_records(chunks, validator(args.contracts / "evidence-chunk.schema.json"), "chunk"))
    errors.extend(validate_records(projections, validator(args.contracts / "ir-semantic-projection.schema.json"), "projection"))

    document_ids = {item["document_id"] for item in documents}
    chunk_by_id = {item["chunk_id"]: item for item in chunks}
    projection_ids: set[str] = set()
    for chunk in chunks:
        if chunk["document_id"] not in document_ids:
            errors.append(f"chunk:{chunk['chunk_id']}:missing document")
        digest = hashlib.sha256(chunk["text"].encode()).hexdigest()
        if digest != chunk["content_sha256"]:
            errors.append(f"chunk:{chunk['chunk_id']}:content hash mismatch")
    for projection in projections:
        if projection["projection_id"] in projection_ids:
            errors.append(f"projection:{projection['projection_id']}:duplicate")
        projection_ids.add(projection["projection_id"])
        chunk = chunk_by_id.get(projection["chunk_id"])
        if not chunk or projection["source_content_sha256"] != chunk.get("content_sha256"):
            errors.append(f"projection:{projection['projection_id']}:source link mismatch")
        if hashlib.sha256(projection["text"].encode()).hexdigest() != projection["projection_sha256"]:
            errors.append(f"projection:{projection['projection_id']}:projection hash mismatch")
        if FINANCIAL_LITERAL.search(projection["text"]):
            errors.append(f"projection:{projection['projection_id']}:financial literal survived")
    if len(projections) != len(chunks):
        errors.append("projection population differs from chunk population")

    report = {
        "schema_version": "signalforge/ir-artifact-validation/v1",
        "counts": {
            "observations": len(observations),
            "documents": len(documents),
            "chunks": len(chunks),
            "projections": len(projections),
        },
        "error_count": len(errors),
        "errors": errors[:100],
        "rights_status": "quarantined_pending_review" if any(item["rights_class"].endswith("pending_review") for item in documents) else "reviewed",
        "claim_boundary": "Schema validity does not establish source rights, retrieval quality, or product readiness.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"counts": report["counts"], "error_count": len(errors)}, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
