#!/usr/bin/env python3
"""
determinex_pb_router.py -- generalizing matcher + capture-back + compounding dashboard (priority B)
================================================================================================
Closes the loop on the fingerprinter (A). Instead of "autofix knows tool X needs bidir", a
never-seen tool is FINGERPRINTED, and routed to the technique that matches its SIGNATURE -- so
the second occurrence of any mechanism is free. Every bespoke fix that works writes itself back
into the signature library (capture-back), so coverage only grows.

Compounding metrics (the dashboard):
  match-rate   = % of residual tests that fingerprint to a mechanism with a KNOWN technique
  capture-rate = % of mechanisms seen that have a technique in the library
  free-fix-rate= residuals routed automatically without new engineering
These three ARE the S-curve. They belong on a board; rising match×capture = the curve flattening.

Signature library lives at corpus/programbench/signature_library.json (capture-back target).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "corpus" / "programbench" / "signature_library.json"
sys.path.insert(0, str(ROOT / "scripts"))
import determinex_pb_fingerprint as FP  # noqa: E402

# techniques we can actually apply automatically today (vs need-build/need-solve)
AUTO_TECHNIQUES = {
    "bidir-mirror",
    "crlf-normalize",
    "build-fail-routing",
    "drop-privileges",
    "pty-allocate",
    "hermetic-clock",
    "hermetic-locale",
    "hermetic-path-canon",
    "hermetic-seed",
    "canonical-sort-compare",
    "ansi-normalize",
    "whitespace-normalize",
    "version-pin",
    "exit-code-route",
}


def load_lib() -> dict:
    if LIB.exists():
        return json.loads(LIB.read_text(encoding="utf-8"))
    return {
        "schema": "determinex-pb-signature-library-v1",
        "note": "mechanism -> technique that resolved it + tools it worked on (capture-back). "
        "Routing matches a NEW tool's fingerprint to a known technique here.",
        "signatures": {},
    }


def capture_back(mechanism: str, technique: str, tool: str) -> None:
    """Record that `technique` resolved `mechanism` on `tool`. Second occurrence is then free."""
    lib = load_lib()
    s = lib["signatures"].setdefault(mechanism, {"technique": technique, "tools": [], "hits": 0})
    if tool not in s["tools"]:
        s["tools"].append(tool)
    s["hits"] += 1
    s["technique"] = technique
    LIB.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")


def route_tool(report_path: Path) -> dict:
    """Fingerprint a tool's residuals -> ranked techniques to apply (signature-driven)."""
    try:
        tr = json.loads(report_path.read_text(encoding="utf-8")).get("test_results", [])
    except Exception:
        return {}

    def _ident(n):
        return n.split("::")[-1] if "::" in n else n.split(".")[-1]

    passed = {_ident(x.get("name", "")) for x in tr if x.get("status") == "passed"}
    by_tech = Counter()
    by_mech = Counter()
    for x in tr:
        if x.get("status") == "passed":
            continue
        fp = FP.fingerprint_test(x, passed)
        by_mech[fp.mechanism] += 1
        by_tech[fp.technique] += 1
    auto = {t: n for t, n in by_tech.items() if t in AUTO_TECHNIQUES}
    return {
        "mechanisms": dict(by_mech),
        "techniques": dict(by_tech),
        "auto_routable": auto,
        "auto_count": sum(auto.values()),
        "total_residual": sum(by_tech.values()),
    }


def dashboard(roots: list[str]) -> dict:
    """Compute match-rate / capture-rate / auto-routable across all reports."""
    lib = load_lib()
    captured = set(lib["signatures"].keys())
    total = 0
    matched = 0
    auto = 0
    mech_seen = Counter()
    for root in roots:
        for jf in Path(root).glob("*.eval.json"):
            r = route_tool(jf)
            total += r.get("total_residual", 0)
            auto += r.get("auto_count", 0)
            for m, n in r.get("mechanisms", {}).items():
                mech_seen[m] += n
                tech = FP.MECHANISMS.get(m, ("", ""))[0]
                if tech and tech != "triage" and tech != "solve-loop":
                    matched += n
    mechs = set(mech_seen)
    return {
        "residual_tests": total,
        "match_rate": round(matched / total, 3) if total else 0,  # have a technique mapping
        "auto_routable_rate": round(auto / total, 3)
        if total
        else 0,  # technique we can apply today
        "capture_rate": round(len(captured & mechs) / len(mechs), 3) if mechs else 0,  # in library
        "mechanisms_seen": dict(mech_seen.most_common()),
        "captured_in_library": sorted(captured),
    }


def main() -> int:
    roots = sys.argv[2:] or ["C:/tmp/streamrun_jsons"]
    if len(sys.argv) > 1 and sys.argv[1] == "dashboard":
        d = dashboard(roots)
        print("=== COMPOUNDING DASHBOARD (the S-curve metrics) ===")
        print(f"  residual tests:      {d['residual_tests']}")
        print(
            f"  match-rate:          {d['match_rate']:.1%}  (fingerprint -> known technique mapping)"
        )
        print(f"  auto-routable-rate:  {d['auto_routable_rate']:.1%}  (technique applicable TODAY)")
        print(
            f"  capture-rate:        {d['capture_rate']:.1%}  (mechanisms with a captured-back signature)"
        )
        print(f"  captured in library: {d['captured_in_library'] or '(none yet)'}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
