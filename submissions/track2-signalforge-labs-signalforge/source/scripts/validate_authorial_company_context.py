#!/usr/bin/env python3
"""Validate a source-linked authorial company context artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


NUMERIC_LITERAL = re.compile(r"\d|[$€£¥]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("contracts/authorial-company-context.schema.json"),
    )
    return parser.parse_args()


def collect_source_references(artifact: dict[str, Any]) -> set[str]:
    references: set[str] = set()
    context = artifact["authorial_context"]
    for collection in ("product_families", "solution_domains", "analytical_interpretations"):
        for item in context[collection]:
            references.update(item["source_ids"])
    for claim in artifact["claim_boundary"]["issuer_claims"]:
        references.update(claim["source_ids"])
    return references


def validate(artifact: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors = [
        f"schema:{'/'.join(map(str, error.path))}:{error.message}"
        for error in Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(artifact)
    ]
    source_ids = [source["source_id"] for source in artifact.get("sources", [])]
    if len(source_ids) != len(set(source_ids)):
        errors.append("sources:duplicate source_id")
    missing = collect_source_references(artifact) - set(source_ids)
    if missing:
        errors.append(f"sources:unresolved references:{','.join(sorted(missing))}")
    projection = artifact.get("semantic_projection", {})
    digest = hashlib.sha256(projection.get("text", "").encode()).hexdigest()
    if digest != projection.get("projection_sha256"):
        errors.append("semantic_projection:projection hash mismatch")
    if projection.get("numeric_content") == "none" and NUMERIC_LITERAL.search(projection.get("text", "")):
        errors.append("semantic_projection:numeric literal survived")
    if artifact.get("status") != "approved_for_product" and artifact.get("review", {}).get("product_eligible"):
        errors.append("review:unapproved artifact cannot be product eligible")
    return sorted(errors)


def main() -> int:
    args = parse_args()
    artifact = json.loads(args.artifact.read_text())
    schema = json.loads(args.schema.read_text())
    errors = validate(artifact, schema)
    print(json.dumps({"artifact": str(args.artifact), "error_count": len(errors), "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
