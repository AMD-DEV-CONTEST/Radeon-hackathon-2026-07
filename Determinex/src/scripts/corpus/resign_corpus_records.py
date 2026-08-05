#!/usr/bin/env python3
"""Re-sign existing corpus JSONL files with the durable configured HMAC key.

This is a migration tool for rows written before DETERMINEX_CORPUS_HMAC_KEY was
configured. It creates a sibling .bak file before replacing each JSONL file.
Record payloads are preserved except for:
  - _sig recomputed with the current durable key
  - signature_key_scope set to "durable"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.corpus_manager import hmac_key_scope, resign_record, verify_signature


def _iter_jsonl(root: Path):
    if root.is_file() and root.suffix == ".jsonl":
        yield root
    elif root.is_dir():
        yield from sorted(root.rglob("*.jsonl"))


def resign_path(path: Path, *, dry_run: bool = False) -> dict:
    records = []
    parse_errors = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            parse_errors.append(f"{path}:{line_no}:{exc}")
            continue
        if isinstance(payload, dict):
            records.append(payload)
        else:
            parse_errors.append(f"{path}:{line_no}:not_object")

    signed = [resign_record(record) for record in records]
    invalid_after = sum(1 for record in signed if not verify_signature(record))
    backup = path.with_suffix(path.suffix + ".pre_durable_hmac.bak")

    if not dry_run and records:
        if not backup.exists():
            shutil.copy2(path, backup)
        tmp = path.with_suffix(path.suffix + ".resign.tmp")
        tmp.write_text(
            "".join(json.dumps(record, ensure_ascii=True) + "\n" for record in signed),
            encoding="utf-8",
        )
        tmp.replace(path)

    return {
        "path": str(path),
        "records": len(records),
        "parse_errors": parse_errors[:20],
        "parse_error_count": len(parse_errors),
        "invalid_after": invalid_after,
        "backup": str(backup),
        "dry_run": dry_run,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="+", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if hmac_key_scope() != "durable":
        print(
            json.dumps(
                {
                    "error": "durable_hmac_key_required",
                    "current_signature_key_scope": hmac_key_scope(),
                },
                indent=2,
            )
        )
        return 2

    results = [
        resign_path(path, dry_run=args.dry_run) for root in args.roots for path in _iter_jsonl(root)
    ]
    summary = {
        "current_signature_key_scope": hmac_key_scope(),
        "files": len(results),
        "records": sum(r["records"] for r in results),
        "parse_error_count": sum(r["parse_error_count"] for r in results),
        "invalid_after": sum(r["invalid_after"] for r in results),
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    return 1 if summary["invalid_after"] or summary["parse_error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
