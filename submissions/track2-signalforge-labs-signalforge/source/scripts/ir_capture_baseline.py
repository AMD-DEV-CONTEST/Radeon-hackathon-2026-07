#!/usr/bin/env python3
"""Capture immutable hashes and headline metrics for the Sprint 05 baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_metrics(value: Any, results: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        required = {"recall_at_k", "precision_at_k", "complete_evidence_rate", "citation_correctness"}
        if required.issubset(value):
            results.append({key: value[key] for key in sorted(required | ({"mean_context_tokens"} & set(value)))})
        for child in value.values():
            find_metrics(child, results)
    elif isinstance(value, list):
        for child in value:
            find_metrics(child, results)


def main() -> int:
    args = parse_args()
    relative_paths = [
        "fixtures/retrieval/golden-eval.json",
        "fixtures/investor-relations/document-manifest.json",
        "configs/sources/investor-relations.json",
        "configs/retrieval/retrieval-policy-v1.json",
        "evidence/retrieval/retrieval-granite-small-english.json",
        "evidence/retrieval/retrieval-granite-97m.json",
        "evidence/retrieval/qdrant-granite-small-english.json",
        "evidence/retrieval/qdrant-granite-97m.json",
    ]
    artifacts: list[dict[str, Any]] = []
    for relative in relative_paths:
        path = args.root / relative
        if not path.is_file():
            raise SystemExit(f"baseline artifact missing: {relative}")
        metrics: list[dict[str, Any]] = []
        if path.suffix == ".json":
            find_metrics(json.loads(path.read_text()), metrics)
        artifacts.append({"path": relative, "sha256": digest(path), "metric_snapshots": metrics})
    report = {
        "schema_version": "signalforge/ir-regression-baseline/v1",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "claim_boundary": "These hashes preserve the pre-expansion Sprint 05 behavior; they do not claim the new corpus is equivalent.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact_count": len(artifacts)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
