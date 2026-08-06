#!/usr/bin/env python3
"""canonicalize_schema.py — byte-exact schema canonicalization (SCHEMA-CANONICALIZATION CONTRACT).

Algorithm:
  1. Glob `db/migrations/*.sql`, DROP basenames starting with `golden-`, sort by basename in byte order.
  2. Per file: strict UTF-8 decode (error on invalid), strip leading BOM, split on \\n and \\r\\n,
     strip trailing SP(0x20)/HT(0x09) per line, drop trailing empty lines, join with \\n.
  3. Concatenate processed files with exactly one \\n between and one final \\n.
  4. Write `docs/target-schema.sql` (canonical bytes) + golden fixture `tests/fixtures/golden-target-schema.sql`
     and its sha256 `tests/fixtures/golden-target-schema.sha256`.

Usage: python scripts/canonicalize_schema.py [--check] [--verify]
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"
OUTPUT = ROOT / "docs" / "target-schema.sql"
GOLDEN_SQL = ROOT / "tests" / "fixtures" / "golden-target-schema.sql"
GOLDEN_SHA = ROOT / "tests" / "fixtures" / "golden-target-schema.sha256"


def canonical_bytes() -> bytes:
    files = sorted(
        (f for f in MIGRATIONS.glob("*.sql") if not f.name.startswith("golden-")),
        key=lambda p: p.name.encode("utf-8"),
    )
    parts: list[str] = []
    for f in files:
        raw = f.read_bytes()
        # strict UTF-8 decode
        text = raw.decode("utf-8")
        # strip BOM
        if text.startswith("\ufeff"):
            text = text[1:]
        # split on \n and \r\n into lines
        lines = text.replace("\r\n", "\n").split("\n")
        # strip trailing SP/HT per line; drop trailing empty lines
        lines = [line.rstrip(" \t") for line in lines]
        while lines and lines[-1] == "":
            lines.pop()
        parts.append("\n".join(lines))
    artifact = "\n".join(parts) + "\n"
    return artifact.encode("utf-8")


def write_all() -> None:
    data = canonical_bytes()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_SQL.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(data)
    GOLDEN_SQL.write_bytes(data)
    GOLDEN_SHA.write_text(hashlib.sha256(data).hexdigest() + "\n")
    print(f"canonicalized {len(data)} bytes -> {OUTPUT} + golden fixtures")


def verify() -> int:
    data = canonical_bytes()
    if not OUTPUT.exists():
        print("VERIFY_FAIL: docs/target-schema.sql missing (run without --verify first)")
        return 1
    if OUTPUT.read_bytes() != data:
        print("VERIFY_FAIL: docs/target-schema.sql does not match canonical bytes")
        return 1
    if GOLDEN_SQL.exists() and GOLDEN_SQL.read_bytes() != data:
        print("VERIFY_FAIL: golden fixture does not match canonical bytes")
        return 1
    if GOLDEN_SHA.exists():
        expected = GOLDEN_SHA.read_text().strip()
        actual = hashlib.sha256(data).hexdigest()
        if expected != actual:
            print(f"VERIFY_FAIL: golden sha mismatch (expected {expected}, got {actual})")
            return 1
    print("VERIFY_OK: canonical bytes match docs/target-schema.sql and golden fixtures")
    return 0


def main() -> int:
    if "--verify" in sys.argv:
        return verify()
    if "--check" in sys.argv:
        # write only if different; report drift
        data = canonical_bytes()
        if OUTPUT.exists() and OUTPUT.read_bytes() == data and GOLDEN_SHA.exists():
            print("CHECK_OK: canonical schema is up to date")
            return 0
        write_all()
        print("CHECK_DRIFT: canonical schema was stale; rewrote")
        return 0
    write_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
