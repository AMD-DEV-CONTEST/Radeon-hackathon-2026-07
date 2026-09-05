#!/usr/bin/env python3
"""Validate the public fixture inventory without revealing private scoring."""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIRED = {
    "chair_public_complete": "complete",
    "chair_incomplete": "incomplete",
    "chair_conflicting": "contradictory",
    "chair_privacy_risk": "privacy_risk",
    "chair_route_ineligible": "route_ineligible",
    "chair_correction": "correction",
    "chair_resume": "resume",
}
HEADER = re.compile(
    r"fixture_id:\s*([a-z0-9_]+);\s*category:\s*([a-z0-9_]+);\s*version:\s*([^\s-]+)"
)


def main() -> int:
    findings: list[str] = []
    fixtures = ROOT / "fixtures"
    expected = ROOT / "expected"

    for fixture_id, category in REQUIRED.items():
        fixture_path = fixtures / f"{fixture_id}.md"
        expected_path = expected / f"{fixture_id}.expected.json"
        if not fixture_path.is_file():
            findings.append(f"missing fixture: {fixture_path.relative_to(ROOT)}")
            continue
        if not expected_path.is_file():
            findings.append(f"missing expectation: {expected_path.relative_to(ROOT)}")
            continue

        text = fixture_path.read_text(encoding="utf-8")
        match = HEADER.search(text)
        if not match:
            findings.append(f"invalid fixture header: {fixture_path.name}")
        elif (match.group(1), match.group(2)) != (fixture_id, category):
            findings.append(f"header mismatch: {fixture_path.name}")

        try:
            contract = json.loads(expected_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"invalid JSON: {expected_path.name}: {exc}")
            continue
        if contract.get("fixture_id") != fixture_id:
            findings.append(f"fixture_id mismatch: {expected_path.name}")
        if contract.get("category") != category:
            findings.append(f"category mismatch: {expected_path.name}")
        acs = contract.get("primary_ac")
        if not isinstance(acs, list) or not acs or not all(re.fullmatch(r"AC-\d{2}", x) for x in acs):
            findings.append(f"invalid primary_ac: {expected_path.name}")
        if not contract.get("required_behavior") or not contract.get("forbidden_behavior"):
            findings.append(f"behavior contract incomplete: {expected_path.name}")

    known_files = {f"{fixture_id}.md" for fixture_id in REQUIRED}
    known_expected = {f"{fixture_id}.expected.json" for fixture_id in REQUIRED}
    extra_fixtures = sorted(p.name for p in fixtures.glob("*.md") if p.name not in known_files)
    extra_expected = sorted(p.name for p in expected.glob("*.json") if p.name not in known_expected)
    if extra_fixtures:
        findings.append(f"unregistered fixture(s): {', '.join(extra_fixtures)}")
    if extra_expected:
        findings.append(f"unregistered expectation(s): {', '.join(extra_expected)}")

    if findings:
        for finding in findings:
            print(f"FAIL AC-25: {finding}")
        return 1
    print("PASS AC-25: seven public fixture categories and contracts are complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
