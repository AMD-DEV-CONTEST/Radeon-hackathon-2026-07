#!/usr/bin/env python3
"""Reject fabricated percentages and unsupported ETA claims (AC-17)."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


def check(event: dict) -> list[str]:
    findings: list[str] = []
    percent = event.get("percent")
    if percent is not None:
        if not isinstance(percent, (int, float)) or isinstance(percent, bool) or not 0 <= percent <= 100:
            findings.append("percent must be a number from 0 to 100")
        basis = event.get("percent_basis")
        if not basis:
            findings.append("percent has no declared work-unit basis")
        elif basis == "milestones_done/milestones_total":
            done = event.get("milestones_done")
            total = event.get("milestones_total")
            if not isinstance(done, int) or not isinstance(total, int) or total <= 0 or not 0 <= done <= total:
                findings.append("milestone counts are invalid")
            elif isinstance(percent, (int, float)) and not isinstance(percent, bool):
                expected = round(100 * done / total)
                if abs(percent - expected) > 1:
                    findings.append(f"percent {percent} does not match {done}/{total} ({expected})")

    eta = event.get("eta_seconds")
    if eta is not None:
        history = event.get("eta_history_sample_size")
        basis = event.get("eta_basis")
        if not isinstance(eta, (int, float)) or isinstance(eta, bool) or eta < 0:
            findings.append("eta_seconds must be a non-negative number")
        if not basis or not isinstance(history, int) or history < 3:
            findings.append("ETA needs a named historical basis and at least three comparable runs")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("progress")
    args = parser.parse_args()
    try:
        event = json.loads(pathlib.Path(args.progress).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"HIGH AC-17 invalid progress event: {exc}")
        return 1
    findings = check(event)
    for finding in findings:
        print(f"HIGH AC-17 {finding}")
    if findings:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
