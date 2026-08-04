#!/usr/bin/env python3
"""Verify that every Track 2 submission deliverable is present and consistent.

Run from the radeonpilot/ project root:
    python scripts/verify_submission.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "README.md",
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    ".env.example",
    "LICENSE",
    "docs/PROJECT_SPECIFICATION.md",
    "docs/ARCHITECTURE.md",
    "docs/REPRODUCE.md",
    "docs/DEMO_SCRIPT.md",
    "pi-bridge/package.json",
    "pi-bridge/models.json",
    "pi-bridge/src/server.mjs",
    "pi-bridge/src/orchestrator.mjs",
    "pi-bridge/src/sessions.mjs",
    "src/radeonpilot/orchestrator.py",
    "src/radeonpilot/tools.py",
    "src/radeonpilot/rag.py",
    "src/radeonpilot/memory.py",
    "scripts/setup_server.sh",
    "scripts/start_endpoint.sh",
    "scripts/benchmark_vllm.py",
    "submission/team.json",
    "submission/links.json",
]

KNOWLEDGE_DIR = ROOT / "data" / "knowledge"


def check_files() -> list[str]:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    return missing


def check_knowledge() -> bool:
    return KNOWLEDGE_DIR.exists() and len(list(KNOWLEDGE_DIR.glob("*.md"))) >= 3


def check_benchmarks() -> list[str]:
    results = ROOT / "benchmarks" / "results"
    found = [path.name for path in results.glob("*.json")] if results.exists() else []
    return found


def check_team() -> list[str]:
    problems = []
    team_path = ROOT / "submission" / "team.json"
    if team_path.exists():
        try:
            team = json.loads(team_path.read_text(encoding="utf-8"))
            for key in ("application_name", "track"):
                if not team.get(key):
                    problems.append(f"submission/team.json missing '{key}'")
        except json.JSONDecodeError:
            problems.append("submission/team.json is not valid JSON")
    return problems


def main() -> int:
    print("RadeonPilot submission verifier")
    print("==============================")
    missing = check_files()
    if missing:
        print(f"[FAIL] Missing {len(missing)} required files:")
        for path in missing:
            print(f"  - {path}")
    else:
        print(f"[OK] All {len(REQUIRED_FILES)} required files present")

    print(f"[{'OK' if check_knowledge() else 'FAIL'}] Knowledge corpus (>=3 markdown docs)")

    benchmarks = check_benchmarks()
    if benchmarks:
        print(f"[OK] Benchmark records: {', '.join(sorted(benchmarks))}")
    else:
        print("[WARN] No benchmark JSON yet (capture on the Radeon instance)")

    team_problems = check_team()
    if team_problems:
        for problem in team_problems:
            print(f"[FAIL] {problem}")
    else:
        print("[OK] submission/team.json populated")

    ok = not missing and check_knowledge() and not team_problems
    print("\nRESULT:", "PASS" if ok else "INCOMPLETE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
