#!/usr/bin/env python3
"""Compatibility entry point for the 20-request c1/c2/c4 benchmark."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.amd_concurrency import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
