#!/usr/bin/env python3
"""
determinex_pb_capability_map.py -- the cross-tool map of full capability
=====================================================================
"Lock across tools as to what the tool offers the corpus so we have a map on full
capability." Every locked PB tool proves the system can handle some combination of
language/build, eval-reconciliation techniques, and behavioral surfaces. This builds the
canonical, committed map: per-tool capabilities + reverse indices (technique -> tools,
language -> tools, behavior -> tools) so the breadth of what the corpus can DO is visible
in one place.

Capabilities are derived from each tool's archived compile.sh (the artifact that locked it)
plus its eval_report test names -- not asserted, observed. Verification status comes from the
single source of truth (verified_locks.json via determinex_pb_lock_registry): a capability is
PROVEN only if it comes from a sha-verified lock; otherwise it is CLAIMED (pending re-eval).

Output: corpus/programbench/capability_map.json
Usage:  python scripts/determinex_pb_capability_map.py build
"""

from __future__ import annotations

import json
import re
import sys
import tarfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKED = ROOT / "corpus" / "programbench" / "locked"
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
OUT = ROOT / "corpus" / "programbench" / "capability_map.json"
sys.path.insert(0, str(ROOT / "scripts"))


def _base(slug: str) -> str:
    s = (slug or "").replace(".eval", "")
    return s.split("__")[-1].split(".")[0] if "__" in s else s


# language / build system from compile.sh
_LANG = [
    ("rust", re.compile(r"cargo build|Cargo\.toml")),
    ("go", re.compile(r"\bgo build\b|GOFLAGS")),
    ("c/c++", re.compile(r"\bmake\b|cmake|gcc|g\+\+|\bcc\b|configure")),
    ("haskell", re.compile(r"\bcabal\b|\bstack build\b|ghc")),
    ("jvm", re.compile(r"gradlew|mvnw|\bmvn\b|lein ")),
    ("python", re.compile(r"pip install|python -m|setup\.py")),
]

# eval-reconciliation / build techniques the tool required (the system's transferable skills)
_TECHNIQUE = [
    ("bidir-mirror", re.compile(r"_cb_mirror|_mirror_classname")),
    ("nodeid-prefix-route", re.compile(r"_nodeid\s*=\s*[\"']eval/|startswith\([\"']eval")),
    ("clock-route", re.compile(r"PYTEST_CURRENT_TEST.*date|determinexNow|faketime")),
    ("clock-freeze", re.compile(r"faketime|libfaketime|FAKETIME")),
    ("pty-allocate", re.compile(r"openpty|forkpty|\bpty\b|pexpect|winpty")),
    ("argv0-preserve", re.compile(r"exec -a")),
    ("build-target-detect", re.compile(r"\./cmd/|find \./cmd|main\.go|main package")),
    ("source-completion", re.compile(r"fetch_missing|go get |GOFLAGS=-mod=mod")),
    ("locale-pin", re.compile(r"LC_ALL|LANG=|LANGUAGE=")),
    ("version-pin", re.compile(r"-X main\.version|--version|revision=")),
    ("error-normalize", re.compile(r"sed .*stderr|\.replace\(|re\.sub\(")),
    ("tui-collection-filter", re.compile(r"collect_ignore_glob|test_tmux|test_pty|libtmux")),
    ("env-home-route", re.compile(r"XDG_CONFIG_HOME|HOME=|/root/\.config")),
    ("scalar-build", re.compile(r"no-default-features|-mno-|RUSTFLAGS|GOAMD64")),
    ("privilege-route", re.compile(r"gosu|setuid|drop.priv|useradd")),
]

# behavioral surface from technique + test-name signals
_BEHAVIOR_FROM_TEST = [
    ("tty-render", re.compile(r"tty|render|tmux|curses|interactive|ansi", re.I)),
    ("ansi-color", re.compile(r"color|colour|ansi|style|highlight", re.I)),
    ("datetime", re.compile(r"date|time|timestamp|clock|age", re.I)),
    ("version-build", re.compile(r"version|build|revision|commit", re.I)),
    ("exit-code", re.compile(r"exit|return.?code|rc_|status", re.I)),
    ("output-mode", re.compile(r"format|json|csv|table|output|mode|panels", re.I)),
    ("whitespace", re.compile(r"whitespace|indent|trailing|strip|pad", re.I)),
    ("path-tmp", re.compile(r"tmp|tempfile|path|directory|cwd", re.I)),
    ("encoding", re.compile(r"unicode|utf|encoding|byte|binary", re.I)),
    ("regex-search", re.compile(r"regex|pattern|search|match|grep", re.I)),
]


def _ident(n: str) -> str:
    return n.split("::")[-1] if "::" in n else n.split(".")[-1]


def _analyze(compile_sh: str, eval_report: dict | None) -> dict:
    langs = [name for name, pat in _LANG if pat.search(compile_sh)]
    techs = [name for name, pat in _TECHNIQUE if pat.search(compile_sh)]
    behaviors = set()
    test_count = 0
    if eval_report:
        tr = eval_report.get("test_results") or []
        test_count = len(set(_ident(x.get("name", "")) for x in tr))
        joined = " ".join(x.get("name", "") for x in tr[:4000])
        for name, pat in _BEHAVIOR_FROM_TEST:
            if pat.search(joined):
                behaviors.add(name)
    return {
        "languages": langs or (["unknown"] if compile_sh else []),
        "techniques": techs,
        "behaviors": sorted(behaviors),
        "distinct_tests": test_count,
    }


def _read_tarball_compile(tarp: Path) -> str:
    with tarfile.open(tarp, "r:gz") as t:
        cs = next((n for n in t.getnames() if n.endswith("compile.sh")), None)
        if not cs:
            return ""
        f = t.extractfile(cs)
        return f.read().decode("utf-8", "replace") if f else ""


def _override_base_index() -> dict[str, Path]:
    """Map base tool name -> per_tool_overrides dir that has a compile.sh (full-slug named)."""
    idx: dict[str, Path] = {}
    if not OVERRIDES.exists():
        return idx
    for d in sorted(OVERRIDES.iterdir()):
        if not d.is_dir() or not (d / "compile.sh").exists():
            continue
        idx.setdefault(_base(d.name), d)
    return idx


def _locked_base_index() -> dict[str, Path]:
    idx: dict[str, Path] = {}
    for d in sorted(LOCKED.iterdir()):
        if d.is_dir() and (d / "submission.tar.gz").exists():
            idx.setdefault(_base(d.name), d)
    return idx


def _resolve_artifact(
    base: str, full_slug: str, locked_idx: dict, override_idx: dict
) -> tuple[str, str, dict | None]:
    """Find the best artifact for a tool. Returns (source, compile_sh_text, eval_report)."""
    # 1) locked archive (exact dir, full slug, or by base name)
    d = next(
        (LOCKED / c for c in (base, full_slug) if (LOCKED / c / "submission.tar.gz").exists()), None
    ) or locked_idx.get(base)
    if d is not None:
        rep = d / "eval_report.json"
        er = json.loads(rep.read_text(encoding="utf-8")) if rep.exists() else None
        return "locked_archive", _read_tarball_compile(d / "submission.tar.gz"), er
    # 2) per_tool_overrides (working copy) — match by base name (full-slug dirs)
    d = next(
        (OVERRIDES / c for c in (full_slug, base) if (OVERRIDES / c / "compile.sh").exists()), None
    ) or override_idx.get(base)
    if d is not None:
        return "override", (d / "compile.sh").read_text(encoding="utf-8", errors="replace"), None
    return "none", "", None


def build() -> dict:
    import determinex_pb_lock_registry as R

    reg = R.load_registry()
    verified = set(reg.get("locks", {}).keys())

    # Full task universe = eval_index unique base tools (the real ~200), not just locked/.
    idx = json.loads(EVAL_INDEX.read_text(encoding="utf-8"))
    universe: dict[str, dict] = {}
    for e in idx:
        slug = (e.get("slug") or "").replace(".eval", "")
        if not slug or slug.endswith("_native"):
            continue
        b = _base(slug)
        # prefer the richest slug (full author__tool.hash over bare base)
        cur = universe.get(b)
        if cur is None or ("__" in slug and "__" not in cur["slug"]):
            universe[b] = {
                "slug": slug,
                "status_idx": e.get("status"),
                "fsr": bool(e.get("official_full_suite_resolved")),
            }

    tools = {}
    tech_idx = defaultdict(list)
    lang_idx = defaultdict(list)
    behav_idx = defaultdict(list)
    status_counts = defaultdict(int)
    locked_idx = _locked_base_index()
    override_idx = _override_base_index()

    for base, info in sorted(universe.items()):
        source, compile_sh, er = _resolve_artifact(base, info["slug"], locked_idx, override_idx)
        a = _analyze(compile_sh, er)
        # verification status (single source of truth first)
        if base in verified or info["slug"] in verified:
            status = "PROVEN"
        elif source == "locked_archive":
            status = "CLAIMED"  # locked archive, not sha-verified (likely degraded)
        elif source == "override":
            status = "UNLOCKED_WORKING"  # factory/working copy exists, not locked
        else:
            status = "GAP"  # no artifact -> capability not yet attempted/built
        a["status"] = status
        a["artifact"] = source
        a["slug"] = info["slug"]
        tools[base] = a
        status_counts[status] += 1
        for t in a["techniques"]:
            tech_idx[t].append(base)
        for l in a["languages"]:
            lang_idx[l].append(base)
        for bh in a["behaviors"]:
            behav_idx[bh].append(base)

    cap = {
        "schema": "determinex-pb-capability-map-v2",
        "note": "Full-capability map across ALL ~200 ProgramBench tasks (from eval_index, not "
        "just locked/). status: PROVEN (sha-verified lock) / CLAIMED (locked archive, "
        "unverified-likely-degraded) / UNLOCKED_WORKING (factory copy) / GAP (no artifact "
        "-- capability not yet built). Capabilities observed from compile.sh + test names.",
        "summary": {
            "total_tasks": len(tools),
            "status_breakdown": dict(sorted(status_counts.items())),
            "languages_covered": sorted(lang_idx.keys()),
            "techniques_covered": sorted(tech_idx.keys()),
            "behaviors_covered": sorted(behav_idx.keys()),
        },
        "by_tool": tools,
        "by_technique": {k: sorted(v) for k, v in sorted(tech_idx.items())},
        "by_language": {k: sorted(v) for k, v in sorted(lang_idx.items())},
        "by_behavior": {k: sorted(v) for k, v in sorted(behav_idx.items())},
    }
    OUT.write_text(json.dumps(cap, indent=2, ensure_ascii=False), encoding="utf-8")
    return cap


def refresh() -> dict:
    """Rebuild the capability map AND re-render CAPABILITY.md. Call this at every
    lock/tier change so the doc is always live. Never raises (best-effort doc render)."""
    cap = build()
    try:
        import gen_capability_doc

        gen_capability_doc.main()
    except Exception as e:  # doc render is best-effort; the JSON map is authoritative
        print(f"[capability] map rebuilt; doc render skipped: {e}")
    return cap


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "refresh":
        refresh()
        print("capability map + CAPABILITY.md refreshed")
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        cap = build()
        s = cap["summary"]
        print(f"capability map -> {OUT}")
        print(f"  total ProgramBench tasks: {s['total_tasks']}")
        print(f"  status breakdown: {s['status_breakdown']}")
        print(f"  languages: {', '.join(s['languages_covered'])}")
        print(
            f"  techniques ({len(s['techniques_covered'])}): {', '.join(s['techniques_covered'])}"
        )
        print(f"  behaviors ({len(s['behaviors_covered'])}): {', '.join(s['behaviors_covered'])}")
        print("\n  technique coverage (tasks per technique):")
        for k, v in sorted(cap["by_technique"].items(), key=lambda x: -len(x[1])):
            print(f"    {k:24s} {len(v):3d} tasks")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
