#!/usr/bin/env python3
"""Separate narrative changes from raw HTML or PDF byte noise across IR runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-documents", type=Path, required=True)
    parser.add_argument("--previous-chunks", type=Path, required=True)
    parser.add_argument("--current-documents", type=Path, required=True)
    parser.add_argument("--current-chunks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    args = parse_args()
    previous_documents = {item["document_id"]: item for item in read_jsonl(args.previous_documents)}
    current_documents = {item["document_id"]: item for item in read_jsonl(args.current_documents)}
    previous_chunks = {(item["document_id"], item["locator"]): item for item in read_jsonl(args.previous_chunks)}
    current_chunks = {(item["document_id"], item["locator"]): item for item in read_jsonl(args.current_chunks)}
    records: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for identity in sorted(previous_chunks.keys() | current_chunks.keys()):
        old = previous_chunks.get(identity)
        new = current_chunks.get(identity)
        if old and new:
            disposition = "narrative_unchanged" if old["content_sha256"] == new["content_sha256"] else "narrative_changed"
        elif new:
            disposition = "chunk_newly_observed"
        else:
            disposition = "chunk_not_observed_in_current_run"
        counts[disposition] = counts.get(disposition, 0) + 1
        document_id, locator = identity
        record = {
            "document_id": document_id,
            "locator": locator,
            "disposition": disposition,
            "previous_source_uri": previous_documents.get(document_id, {}).get("source_uri"),
            "current_source_uri": current_documents.get(document_id, {}).get("source_uri"),
            "previous_document_sha256": previous_documents.get(document_id, {}).get("content_sha256"),
            "current_document_sha256": current_documents.get(document_id, {}).get("content_sha256"),
        }
        if old:
            record["previous_chunk_sha256"] = old["content_sha256"]
        if new:
            record["current_chunk_sha256"] = new["content_sha256"]
        records.append(record)
    changed_raw = sum(
        previous_documents[key]["content_sha256"] != current_documents[key]["content_sha256"]
        for key in previous_documents.keys() & current_documents.keys()
    )
    report = {
        "schema_version": "signalforge/ir-narrative-lineage/v1",
        "raw_documents_changed": changed_raw,
        "chunk_disposition_counts": dict(sorted(counts.items())),
        "records": records,
        "claim_boundary": "Missing chunks are collection observations, not proof that language was intentionally removed. Change interpretation requires both source versions.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"raw_documents_changed": changed_raw, "chunk_disposition_counts": report["chunk_disposition_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
