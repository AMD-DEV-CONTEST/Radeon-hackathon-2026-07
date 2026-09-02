#!/usr/bin/env python3
"""Validate vector bytes and lineage back to silent projections and exact chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--vector-records", type=Path, required=True)
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--contracts", type=Path, default=Path("contracts"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    args = parse_args()
    import numpy as np

    records = read_jsonl(args.vector_records)
    projections = {item["chunk_id"]: item for item in read_jsonl(args.projections)}
    chunks = {item["chunk_id"]: item for item in read_jsonl(args.chunks)}
    schema = Draft202012Validator(
        json.loads((args.contracts / "ir-vector-record.schema.json").read_text()),
        format_checker=FormatChecker(),
    )
    errors: list[str] = []
    seen_vectors: set[str] = set()
    seen_chunks: set[str] = set()
    for index, record in enumerate(records, 1):
        for error in schema.iter_errors(record):
            errors.append(f"record:{index}:{'/'.join(map(str, error.path))}:{error.message}")
        if record.get("vector_id") in seen_vectors:
            errors.append(f"record:{index}:duplicate vector_id")
        if record.get("chunk_id") in seen_chunks:
            errors.append(f"record:{index}:duplicate chunk_id")
        seen_vectors.add(record.get("vector_id", ""))
        seen_chunks.add(record.get("chunk_id", ""))
        chunk = chunks.get(record.get("chunk_id"))
        projection = projections.get(record.get("chunk_id"))
        if not chunk or not projection:
            errors.append(f"record:{index}:missing chunk or projection")
            continue
        expected = {
            "projection_id": projection["projection_id"],
            "company_id": chunk["company_id"],
            "available_at": chunk["available_at"],
            "authority_tier": chunk["authority_tier"],
            "document_type": chunk["document_type"],
            "rights_class": chunk["rights_class"],
            "document_sha256": chunk["document_sha256"],
            "source_content_sha256": chunk["content_sha256"],
            "projection_sha256": projection["projection_sha256"],
        }
        for key, value in expected.items():
            if record.get(key) != value:
                errors.append(f"record:{index}:{key}:lineage mismatch")

    archive = np.load(args.vectors, allow_pickle=False)
    vector_chunk_ids = [str(item) for item in archive["chunk_ids"]]
    vector_values = archive["chunk_vectors"]
    if len(vector_chunk_ids) != len(vector_values) or len(records) != len(vector_values):
        errors.append("vector, ID, and record populations differ")
    record_by_chunk = {item.get("chunk_id"): item for item in records}
    for chunk_id, vector in zip(vector_chunk_ids, vector_values):
        record = record_by_chunk.get(chunk_id)
        if not record:
            errors.append(f"vector:{chunk_id}:missing record")
            continue
        if vector.ndim != 1 or vector.shape[0] != record["dimension"]:
            errors.append(f"vector:{chunk_id}:dimension mismatch")
        digest = hashlib.sha256(vector.astype("float32").tobytes()).hexdigest()
        if digest != record["vector_sha256"]:
            errors.append(f"vector:{chunk_id}:hash mismatch")

    report = {
        "schema_version": "signalforge/ir-vector-validation/v1",
        "record_count": len(records),
        "vector_count": len(vector_values),
        "error_count": len(errors),
        "errors": errors[:100],
        "claim_boundary": "Vector integrity and lineage do not establish source rights or retrieval quality.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("record_count", "vector_count", "error_count")}, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
