#!/usr/bin/env python3
"""Reclassify a frozen IR collection without fetching or mutating source artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any

try:
    import ir_collect
except ModuleNotFoundError:
    from scripts import ir_collect


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    args = parse_args()
    documents = read_jsonl(args.input_dir / "documents.jsonl")
    changed = 0
    dropped: list[str] = []
    retained: list[dict[str, Any]] = []
    for document in documents:
        is_root = ir_collect.canonical_uri(document["source_uri"]).rstrip("/") == ir_collect.canonical_uri(
            document["discovery_uri"]
        ).rstrip("/")
        if not is_root and not ir_collect.is_material_candidate(document["source_uri"], document["title"]):
            dropped.append(document["document_id"])
            continue
        document_type, authority_tier, promotional = ir_collect.classify(
            document["source_uri"], document["title"], document["title"]
        )
        if (document_type, authority_tier, promotional) != (
            document["document_type"], document["authority_tier"], document["promotional"]
        ):
            changed += 1
            document["document_type"] = document_type
            document["authority_tier"] = authority_tier
            document["promotional"] = promotional
            document["forward_looking"] = document_type in {"guidance_and_outlook", "prepared_remarks"}
            document["classification_reasons"] = ["deterministic reclassification ir-collector/1.2.0"]
        retained.append(document)
    documents = retained
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("crawl-observations.jsonl", "collection-summary.json"):
        shutil.copyfile(args.input_dir / filename, args.output_dir / filename)
    with (args.output_dir / "documents.jsonl").open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(json.dumps(document, sort_keys=True) + "\n")
    report = {
        "schema_version": "signalforge/ir-reclassification/v1",
        "document_count": len(documents),
        "changed_document_count": changed,
        "dropped_non_material_count": len(dropped),
        "dropped_document_ids": dropped,
        "source_collection": str(args.input_dir),
        "network_requests": 0,
    }
    (args.output_dir / "reclassification-summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
