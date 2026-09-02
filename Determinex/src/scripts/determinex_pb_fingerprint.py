#!/usr/bin/env python3
"""determinex_pb_fingerprint.py -- DEPRECATED shim. The mechanism taxonomy now lives in
determinex_pb_taxonomy.py (single source of truth, alongside the CLI-feature families).
This re-exports so existing callers keep working. Do NOT add classification logic here.
"""

import sys
from pathlib import Path

from determinex_pb_taxonomy import (  # noqa: F401
    _NAME_SIG,
    _SIG,
    MECHANISMS,
    Fingerprint,
    fingerprint_test,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))


def fingerprint_report(report_path):
    import json
    from collections import Counter

    try:
        tr = json.loads(Path(report_path).read_text(encoding="utf-8")).get("test_results", [])
    except Exception:
        return {}

    def _ident(n):
        return n.split("::")[-1] if "::" in n else n.split(".")[-1]

    passed = {_ident(x.get("name", "")) for x in tr if x.get("status") == "passed"}
    hist = Counter()
    for x in tr:
        if x.get("status") == "passed":
            continue
        hist[fingerprint_test(x, passed).mechanism] += 1
    return dict(hist)
