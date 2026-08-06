#!/usr/bin/env python3
"""validate_clean_readme.py — validate the clean-shell README walk result (Todo 11/F4).

The result JSON (from run_clean_readme.sh) records each README shell command and
whether it ran successfully. Exit 0 when every command was executed successfully.

Usage:
  python scripts/validate_clean_readme.py <result.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_clean_readme.py <result.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"RESULT_NOT_FOUND: {path}", file=sys.stderr)
        return 1
    result = json.loads(path.read_text())
    commands = result.get("commands", [])
    failures = [c for c in commands if c.get("ok") is not True]
    if failures:
        for c in failures:
            print(f"CLEAN_README_FAIL: {c.get('cmd', '?')} -> {c.get('error', 'nonzero')}", file=sys.stderr)
        print("CLEAN_README_FAIL", file=sys.stderr)
        return 1
    print(f"CLEAN_README_OK: {len(commands)} commands executed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
