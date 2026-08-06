#!/usr/bin/env python3
"""Check that a PR body contains enough context for risk-based review (AC-22)."""

from __future__ import annotations

import argparse
import os
import re
import sys

L2_NAMES = (
    "Canonical state",
    "Persistence and resume",
    "Evidence discipline",
    "Runtime permission",
    "Privacy and publication",
    "Local inference",
    "Failure behavior",
    "Observability",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-env", default="PR_BODY")
    args = parser.parse_args()
    body = os.environ.get(args.body_env, "")
    lean_failures: list[str] = []
    lean_fields = {
        "main behavior/risk": r"Main behavior/risk changed[：:][ \t]*\S",
        "checks": r"Checks run and result[^:：]*[：:][ \t]*\S",
        "rollback": r"Rollback/revert path[：:][ \t]*\S",
    }
    for name, pattern in lean_fields.items():
        if not re.search(pattern, body, re.IGNORECASE):
            lean_failures.append(f"no non-empty {name} field")

    # Preserve compatibility with the earlier detailed quality-contract
    # mapping. Deep-audit PRs may still use it, but routine PRs can use the
    # lean review essentials above.
    mapping_failures: list[str] = []
    if not re.search(r"\bAC-\d{2}\b", body):
        mapping_failures.append("no AC-* identifier")
    if not re.search(r"\bM[1-5]\b|cross[- ]cutting|渲染与进度", body, re.IGNORECASE):
        mapping_failures.append("no L1 milestone or explicit cross-cutting scope")
    if not any(name.casefold() in body.casefold() for name in L2_NAMES):
        mapping_failures.append("no recognized L2 capability gate")
    if not re.search(r"chair_[a-z_]+|not applicable|N/A|不适用", body, re.IGNORECASE):
        mapping_failures.append("no public fixture or explicit not-applicable reason")
    if not re.search(
        r"(?:Test/fixture result|Artifact or trace snapshot|If performance-related[^:]*):[ \t]+\S|公开证据[：:][ \t]*\S",
        body,
        re.IGNORECASE,
    ):
        mapping_failures.append("no non-empty public evidence item")

    if lean_failures and mapping_failures:
        for failure in lean_failures:
            print(f"ADVISORY AC-22: {failure}")
        print("ADVISORY AC-22: add the lean review essentials or a complete deep-audit mapping")
        return 1
    print("PASS AC-22: enough PR context is present for risk-based review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
