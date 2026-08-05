"""Tiny SQL smoke validator used as a profile placeholder.

Benchmark SQL adapters should usually provide real database provisioning and
result comparison. This module gives generic SQL tasks a deterministic local
SQLite syntax/execute check without adding dependencies.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]] or sorted(Path.cwd().glob("*.sql"))
    if not paths:
        print("no sql files found", file=sys.stderr)
        return 1
    conn = sqlite3.connect(":memory:")
    try:
        for path in paths:
            conn.executescript(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"sql smoke failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
