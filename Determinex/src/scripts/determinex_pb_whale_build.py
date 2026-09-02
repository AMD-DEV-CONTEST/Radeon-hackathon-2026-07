#!/usr/bin/env python3
"""
determinex_pb_whale_build.py -- apply the corpus whale_base_toolchains recipe + drop build walls
=============================================================================================
For a major whale, ensure compile.sh installs its corpus-recorded base toolchain + specific
libs BEFORE the build (the #1 reason whales fail: missing deps). Composes the corpus recipe
(build_knowledge.whale_base_toolchains_2026_06_23) -- no blind kitchen-sink. Then eval; on
build-fail, harvest build.err and report the FIRST error for the SPECIFIC next fix (the
corpus method: build_probe -> read build.err -> specific fix -> repeat, NEVER blind).

Usage:
  python scripts/determinex_pb_whale_build.py <full_slug>          # apply recipe + eval
  python scripts/determinex_pb_whale_build.py --list               # show the recipe map
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PB = ROOT / "corpus" / "programbench"
OV = PB / "per_tool_overrides"
sys.path.insert(0, str(ROOT / "scripts"))

_MARK = "# [determinex-whale-deps]"


def recipe(slug: str) -> dict | None:
    kb = json.loads((PB / "build_knowledge.json").read_text(encoding="utf-8"))
    return kb.get("whale_base_toolchains_2026_06_23", {}).get("whales", {}).get(slug)


def ensure_deps(slug: str) -> bool:
    """Prepend the recipe's apt-install (idempotent) so the whale's deps are present."""
    r = recipe(slug)
    if not r:
        return False
    cs = OV / slug / "compile.sh"
    if not cs.exists():
        return False
    txt = cs.read_text(encoding="utf-8", errors="replace")
    if _MARK in txt:
        return False
    apt = r.get("apt", "build-essential")
    block = (
        f"\n{_MARK} corpus whale_base_toolchains: {r.get('sys', '')} -> {r.get('build', '')[:60]}\n"
        f"export DEBIAN_FRONTEND=noninteractive\n"
        f"apt-get update -qq 2>/dev/null || true\n"
        f"apt-get install -y -qq {apt} 2>/dev/null || true\n"
    )
    lines = txt.splitlines(keepends=True)
    at = 1 if lines and lines[0].startswith("#!") else 0
    lines.insert(at, block)
    cs.write_text("".join(lines), encoding="utf-8", newline="\n")
    return True


def build_and_report(slug: str, local: bool | None = None) -> dict:
    from pathlib import Path as _P

    import determinex_pb_autofix as AF
    from pb_eval_unified import run_hetzner_eval, run_local_eval

    # auto-detect: when running ON the eval box, eval locally (SSHing to ourselves fails 255)
    if local is None:
        local = _P("/root/ProgramBench").is_dir()
    changed = ensure_deps(slug)
    tarball = AF.pack_submission(slug)
    # local Docker = parallel + memory-controlled (matters for OOM/timeout-sensitive tests);
    # Hetzner is a single serial box. Route per caller.
    data = (run_local_eval(slug, tarball) if local else run_hetzner_eval(slug, tarball)) or {}
    tr = data.get("test_results", [])
    c = collections.Counter(r.get("status") for r in tr)
    rc127 = sum(1 for r in tr if "127" in str((r.get("extra") or {}).get("text", ""))[:160])
    total = len(tr)
    passed = c.get("passed", 0)
    out = {
        "slug": slug,
        "deps_added": changed,
        "passed": passed,
        "total": total,
        "failed": c.get("failure", 0) + c.get("failed", 0) + c.get("error", 0),
        "not_run": c.get("not_run", 0),
        "rc127": rc127,
        "verdict": "BUILDS" if total and passed > 0.10 * total else "BUILD-FAIL",
    }
    # save fresh report
    try:
        (OV / slug / "eval_report.json").write_text(
            json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass
    return out


def main() -> int:
    if "--list" in sys.argv:
        kb = json.loads((PB / "build_knowledge.json").read_text(encoding="utf-8"))
        for s, r in kb.get("whale_base_toolchains_2026_06_23", {}).get("whales", {}).items():
            print(f"  {s.split('__')[-1]:22s} [{r['sys']:14s}] {r['build'][:60]}")
        return 0
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    res = build_and_report(args[0], local=(True if "--local" in sys.argv else None))
    print(
        f"{res['slug']}: {res['verdict']} {res['passed']}/{res['total']} "
        f"fail={res['failed']} nr={res['not_run']} rc127={res['rc127']} deps_added={res['deps_added']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
