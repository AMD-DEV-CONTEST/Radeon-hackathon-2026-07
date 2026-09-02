"""
scripts/determinex_validate.py — Standalone CLI for the Universal Oracle Pack
=========================================================================
Thin wrapper around scripts/validators/VALIDATOR_MAP so the Sprint 3 oracles
are usable from the shell immediately, without waiting for hive/compiler.py
integration.

Usage:
    python scripts/determinex_validate.py <kind> [--file PATH | --stdin] [--meta JSON]

Examples:
    cat my.sh | python scripts/determinex_validate.py bash --stdin
    python scripts/determinex_validate.py dockerfile --file Dockerfile
    python scripts/determinex_validate.py sql --file query.sql --meta '{"sql_dialect":"postgres"}'
    python scripts/determinex_validate.py yaml --file values.yaml --meta '{"yamllint_strict":true}'

Exits 0 on pass, 1 on fail, 2 on usage / I/O error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from validators import VALIDATOR_MAP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Determinex Universal Oracle Pack — standalone validator CLI"
    )
    parser.add_argument(
        "kind",
        choices=sorted(VALIDATOR_MAP.keys()),
        help="Validator to run (Sprint 3 adds: bash, powershell, dockerfile, yaml, xdist, sql)",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", type=Path, help="Path to file to validate")
    src.add_argument("--stdin", action="store_true", help="Read content from stdin")
    parser.add_argument(
        "--meta",
        type=str,
        default="{}",
        help="JSON dict of task_meta options (see each validator's docstring)",
    )
    parser.add_argument(
        "--json", dest="json_out", action="store_true", help="Emit JSON result instead of text"
    )
    args = parser.parse_args(argv)

    try:
        task_meta = json.loads(args.meta)
        if not isinstance(task_meta, dict):
            print("ERROR: --meta must be a JSON object", file=sys.stderr)
            return 2
    except json.JSONDecodeError as e:
        print(f"ERROR: --meta is not valid JSON: {e}", file=sys.stderr)
        return 2

    if args.file:
        try:
            content = args.file.read_text(encoding="utf-8")
        except OSError as e:
            print(f"ERROR: cannot read {args.file}: {e}", file=sys.stderr)
            return 2
    else:
        content = sys.stdin.read()

    validator = VALIDATOR_MAP[args.kind]
    passed, reason = validator(content, task_meta)

    if args.json_out:
        print(
            json.dumps({"kind": args.kind, "passed": passed, "reason": reason}, ensure_ascii=False)
        )
    else:
        status = "PASS" if passed else "FAIL"
        print(f"[{args.kind}] {status}: {reason}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
