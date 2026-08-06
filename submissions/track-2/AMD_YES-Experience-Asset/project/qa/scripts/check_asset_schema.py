#!/usr/bin/env python3
"""Deterministic public checks for a canonical Experience Asset."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "experience_asset.schema.json"
ROUTES = ("private_self", "beginner", "peer", "customer_evaluator", "public")
STATUSES = {"source_fact", "user_judgment", "agent_inference", "unresolved"}
ELIGIBILITY = {"eligible", "ineligible", "eligible_after_privacy_approval", "blocked"}


def load(path: str | pathlib.Path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def check(asset: dict, expected: dict | None = None) -> list[tuple[str, str, str]]:
    findings: list[tuple[str, str, str]] = []
    required = ("asset_id", "version", "created_utc", "provenance", "context", "goal", "statements", "routes")
    for key in required:
        if key not in asset:
            findings.append(("HIGH", "AC-03", f"missing required field: {key}"))

    provenance = asset.get("provenance")
    if not isinstance(provenance, dict):
        findings.append(("HIGH", "AC-01", "provenance must be an object"))
        provenance = {}
    if provenance.get("adapted") is True and provenance.get("first_party_testimony") is True:
        findings.append(("HIGH", "AC-01", "adapted fixture cannot claim first-party testimony"))

    statements = asset.get("statements")
    if not isinstance(statements, list) or not statements:
        findings.append(("CRITICAL", "AC-03", "statements must be a non-empty list"))
        statements = []
    for index, statement in enumerate(statements):
        if not isinstance(statement, dict):
            findings.append(("CRITICAL", "AC-03", f"statement[{index}] is not an object"))
            continue
        status = statement.get("status")
        if status not in STATUSES:
            findings.append(("CRITICAL", "AC-03", f"statement[{index}] has invalid status"))
        if not statement.get("text"):
            findings.append(("HIGH", "AC-03", f"statement[{index}] has no text"))
        if status == "source_fact" and not statement.get("evidence_ref"):
            findings.append(("CRITICAL", "AC-03", f"statement[{index}] source_fact has no evidence_ref"))
        if status == "agent_inference" and statement.get("presented_as_fact") is True:
            findings.append(("CRITICAL", "AC-03", f"statement[{index}] inference is presented as fact"))

    routes = asset.get("routes")
    if not isinstance(routes, dict):
        findings.append(("HIGH", "AC-05", "routes must be an object"))
        routes = {}
    for name in ROUTES:
        route = routes.get(name)
        if not isinstance(route, dict):
            findings.append(("HIGH", "AC-05", f"route not evaluated: {name}"))
            continue
        state = route.get("eligibility")
        if state not in ELIGIBILITY:
            findings.append(("HIGH", "AC-05", f"route {name} has invalid eligibility"))
        if state in {"ineligible", "blocked"} and not route.get("reason"):
            findings.append(("HIGH", "AC-05", f"route {name} needs a concrete reason"))

    if expected:
        if expected.get("fixture_id") and asset.get("fixture_id") not in (None, expected["fixture_id"]):
            findings.append(("HIGH", "AC-25", "asset fixture_id does not match expected contract"))
        for name, wanted in expected.get("route_eligibility", {}).items():
            actual = routes.get(name, {}).get("eligibility")
            if actual != wanted:
                findings.append(("HIGH", "AC-05", f"route {name}: {actual!r} != expected {wanted!r}"))

    try:
        import jsonschema
    except ImportError:
        pass
    else:
        try:
            jsonschema.validate(asset, load(SCHEMA))
        except jsonschema.ValidationError as exc:
            path = "/".join(str(part) for part in exc.absolute_path)
            findings.append(("HIGH", "AC-03", f"JSON Schema: {exc.message} @ /{path}"))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset")
    parser.add_argument("--expected")
    args = parser.parse_args()
    try:
        asset = load(args.asset)
        expected = load(args.expected) if args.expected else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"CRITICAL AC-03 invalid input: {exc}")
        return 1

    findings = check(asset, expected)
    for severity, ac_id, message in findings:
        print(f"{severity:9} {ac_id} {message}")
    if any(item[0] in {"CRITICAL", "HIGH"} for item in findings):
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
