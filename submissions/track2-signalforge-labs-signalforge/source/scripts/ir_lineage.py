#!/usr/bin/env python3
"""Compare two IR document manifests without treating absence as deletion proof."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def index_unique_uri(items: list[dict[str, Any]], population: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        uri = item.get("canonical_uri", "")
        if not uri or uri in result:
            raise ValueError(f"{population} manifest requires unique non-empty canonical_uri values")
        result[uri] = item
    return result


def compare(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_by_uri = index_unique_uri(previous, "previous")
    current_by_uri = index_unique_uri(current, "current")
    previous_by_hash: dict[str, list[dict[str, Any]]] = {}
    current_by_hash: dict[str, list[dict[str, Any]]] = {}
    for item in previous:
        previous_by_hash.setdefault(item["content_sha256"], []).append(item)
    for item in current:
        current_by_hash.setdefault(item["content_sha256"], []).append(item)
    for values in (*previous_by_hash.values(), *current_by_hash.values()):
        values.sort(key=lambda item: (item["canonical_uri"], item["document_id"]))

    def unique_new_uri(values: list[dict[str, Any]], known: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        candidates = [item for item in values if item["canonical_uri"] not in known]
        return candidates[0] if len(candidates) == 1 else None

    records: list[dict[str, Any]] = []
    for uri in sorted(previous_by_uri.keys() | current_by_uri.keys()):
        old = previous_by_uri.get(uri)
        new = current_by_uri.get(uri)
        if old and new:
            disposition = "unchanged" if old["content_sha256"] == new["content_sha256"] else "content_changed"
        elif new:
            moved_from = unique_new_uri(previous_by_hash.get(new["content_sha256"], []), current_by_uri)
            disposition = "moved_uri" if moved_from else "newly_observed"
        else:
            moved_to = unique_new_uri(current_by_hash.get(old["content_sha256"], []), previous_by_uri)
            disposition = "moved_uri" if moved_to else "not_observed_in_current_run"
        record = {"canonical_uri": uri, "disposition": disposition}
        if old:
            record.update(
                {
                    "previous_document_id": old["document_id"],
                    "previous_content_sha256": old["content_sha256"],
                    "previous_retrieved_at": old["retrieved_at"],
                }
            )
        if new:
            record.update(
                {
                    "current_document_id": new["document_id"],
                    "current_content_sha256": new["content_sha256"],
                    "current_retrieved_at": new["retrieved_at"],
                }
            )
        if old and new and disposition == "content_changed":
            record["supersession"] = {
                "superseded_document_id": old["document_id"],
                "superseding_document_id": new["document_id"],
            }
        elif new and disposition == "moved_uri":
            record["moved_from_uri"] = moved_from["canonical_uri"]
        elif old and disposition == "moved_uri":
            record["moved_to_uri"] = moved_to["canonical_uri"]
        records.append(record)
    return records


def resolve_sec_aliases(
    ir_documents: list[dict[str, Any]],
    sec_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bind byte-identical IR exhibits to SEC authority instead of duplicating embeddings."""

    sec_by_hash: dict[str, list[dict[str, Any]]] = {}
    for artifact in sec_artifacts:
        digest = artifact.get("content_sha256", "")
        if digest and artifact.get("document_id") and artifact.get("source_uri"):
            sec_by_hash.setdefault(digest, []).append(artifact)
    for artifacts in sec_by_hash.values():
        artifacts.sort(key=lambda item: (item["document_id"], item["source_uri"]))
    aliases: list[dict[str, Any]] = []
    for document in ir_documents:
        sec_matches = sec_by_hash.get(document.get("content_sha256", ""), [])
        if not sec_matches:
            continue
        sec = sec_matches[0]
        aliases.append(
            {
                "ir_document_id": document["document_id"],
                "sec_document_id": sec["document_id"],
                "content_sha256": document["content_sha256"],
                "canonical_authority": "sec",
                "canonical_source_uri": sec["source_uri"],
                "embedding_disposition": "alias_only_do_not_embed_duplicate",
            }
        )
    return sorted(aliases, key=lambda item: item["ir_document_id"])


def main() -> int:
    args = parse_args()
    records = compare(read_jsonl(args.previous), read_jsonl(args.current))
    counts: dict[str, int] = {}
    for record in records:
        counts[record["disposition"]] = counts.get(record["disposition"], 0) + 1
    report = {
        "schema_version": "signalforge/ir-temporal-lineage/v1",
        "counts": dict(sorted(counts.items())),
        "records": records,
        "claim_boundary": "Not observed in one bounded run is a collection gap, not proof that an issuer deleted a document.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
