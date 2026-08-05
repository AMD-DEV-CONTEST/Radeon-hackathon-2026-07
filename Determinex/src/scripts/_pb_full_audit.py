#!/usr/bin/env python3
"""Comprehensive ProgramBench audit. Scans every tool, every recent eval,
classifies failures, identifies patterns, and groups by fixability.

Writes:
  docs/PROGRAMBENCH_AUDIT.md  (the human-readable report)
  logs/programbench_factory/audit_data.json  (raw data for downstream tools)
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "logs" / "programbench_lock_board.json"
STAGING = ROOT / ".determinex_staging"
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
LOCKED = ROOT / "corpus" / "programbench" / "locked"
AUDIT_MD = ROOT / "docs" / "PROGRAMBENCH_AUDIT.md"
AUDIT_JSON = ROOT / "logs" / "programbench_factory" / "audit_data.json"


# Patterns classify failure messages
PATTERNS = {
    "argv0_path": re.compile(r"(Usage:|usage:).*executable", re.I),
    "build_date": re.compile(r"\d{8}\d{6}|build.*date|VERGEN_BUILD_DATE", re.I),
    "version_string": re.compile(r"Version:|version \d+\.\d+|tag:|commit:", re.I),
    "address_in_use": re.compile(r"Address already in use|Errno 98"),
    "timeout": re.compile(r"TimeoutExpired|timed out after"),
    "serve_signal": re.compile(r"serve.*sigterm|255 is None|signal.*server", re.I),
    "mime_xdg": re.compile(
        r"could not figure out.*mime|xdg-open|desktop entry|No such file or directory"
    ),
    "dns_lookup": re.compile(
        r"(Name or service not known|no such host|getaddrinfo|associated with hostname)"
    ),
    "go_env": re.compile(r"GOROOT not set|GOPATH|no required module"),
    "py_nameerror": re.compile(r"NameError: name|undefined"),
    "py_typeerror_none": re.compile(r"'NoneType' object is not iterable|NoneType.*subscriptable"),
    "tui_screen_diff": re.compile(r"┌|│|└|─|TUI|terminal_size", re.I),
    "stdout_mismatch": re.compile(r"stdout.*mismatch|Stdout mismatch"),
    "golden_diff": re.compile(r"golden|Golden|fixture.*read"),
    "exit_code": re.compile(r"returncode=\d+", re.I),
    "compile_failed": re.compile(r"compile.*failed|build.*failed|cargo build|go build"),
    "missing_file": re.compile(r"FileNotFoundError|No such file"),
}


def load_board() -> dict[str, dict]:
    rows = json.loads(BOARD.read_text(encoding="utf-8"))
    return {r["base_slug"]: r for r in rows if r.get("base_slug")}


def latest_eval_for(base_slug: str) -> tuple[Path | None, dict | None]:
    """Find the most recent eval.json for a given base_slug across staging."""
    candidates = []
    for f in STAGING.glob(f"**/{base_slug}.*.eval.json"):
        candidates.append((f.stat().st_mtime, f))
    if not candidates:
        return None, None
    candidates.sort(reverse=True)
    best = None
    best_passed = -1
    # Among top-10 most recent, return the one with HIGHEST passed (best result)
    for _, f in candidates[:15]:
        try:
            d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            tr = d.get("test_results", [])
            passed = sum(1 for t in tr if t.get("status") == "passed")
            if passed > best_passed:
                best_passed = passed
                best = (f, d)
        except Exception:
            continue
    return best if best else (None, None)


def classify_failures(eval_data: dict) -> tuple[dict[str, list], int, int, int]:
    """Classify all failures by pattern. Return (pattern -> [test_names], passed, runnable, total)."""
    tr = eval_data.get("test_results", [])
    passed = sum(1 for t in tr if t.get("status") == "passed")
    fail = sum(1 for t in tr if t.get("status") == "failure")
    err = sum(1 for t in tr if t.get("status") == "error")
    not_run = sum(1 for t in tr if t.get("status") == "not_run")
    skipped = sum(1 for t in tr if t.get("status") == "skipped")
    runnable = passed + fail + err
    total = len(tr)

    bucket = defaultdict(list)
    for t in tr:
        if t.get("status") != "failure":
            continue
        msg = str(t.get("extra", {}).get("message", "") or "")
        text = str(t.get("extra", {}).get("text", "") or "")
        haystack = (msg + " " + text)[:1500]
        matched = False
        for pname, pat in PATTERNS.items():
            if pat.search(haystack):
                bucket[pname].append(
                    {
                        "name": t.get("name", ""),
                        "msg_excerpt": msg[:300],
                    }
                )
                matched = True
                break
        if not matched:
            bucket["other"].append(
                {
                    "name": t.get("name", ""),
                    "msg_excerpt": msg[:300],
                }
            )
    return dict(bucket), passed, runnable, not_run + skipped


def is_locked(base_slug: str) -> bool:
    if not LOCKED.is_dir():
        return False
    repo = base_slug.split("__", 1)[1] if "__" in base_slug else base_slug
    return (LOCKED / repo).is_dir()


def has_override(base_slug: str) -> Path | None:
    """Find override dir for slug. Slug may have .hash suffix."""
    # base_slug doesn't have .hash, but override dir does
    if not OVERRIDES.is_dir():
        return None
    for d in OVERRIDES.iterdir():
        if d.is_dir() and d.name.startswith(base_slug + "."):
            return d
    # Also try without hash
    direct = OVERRIDES / base_slug
    if direct.is_dir():
        return direct
    return None


def detect_language(override_dir: Path) -> str:
    """Detect primary source language from override dir contents."""
    if not override_dir or not override_dir.is_dir():
        return "unknown"
    counts = Counter()
    for f in override_dir.rglob("*"):
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if suffix in {".rs"}:
            counts["rust"] += 1
        elif suffix in {".go"}:
            counts["go"] += 1
        elif suffix in {".c", ".h"}:
            counts["c"] += 1
        elif suffix in {".cpp", ".cc", ".cxx", ".hpp"}:
            counts["cpp"] += 1
        elif suffix in {".py"}:
            counts["python"] += 1
        elif suffix in {".java"}:
            counts["java"] += 1
        elif suffix in {".clj", ".cljs"}:
            counts["clojure"] += 1
        elif suffix in {".js", ".mjs"}:
            counts["javascript"] += 1
        elif suffix in {".php"}:
            counts["php"] += 1
        elif suffix in {".rb"}:
            counts["ruby"] += 1
    if not counts:
        return "unknown"
    return counts.most_common(1)[0][0]


def build_audit():
    board = load_board()
    audit_rows = []
    for base, info in board.items():
        slug = info.get("slug", "")
        locked = is_locked(base)
        override_dir = has_override(base)
        language = detect_language(override_dir) if override_dir else "unknown"
        eval_path, eval_data = latest_eval_for(base)
        if eval_data:
            patterns, passed, runnable, skipped = classify_failures(eval_data)
            total = passed + sum(len(v) for v in patterns.values())
            score = 100.0 * passed / runnable if runnable > 0 else 0
            pattern_summary = {p: len(v) for p, v in patterns.items()}
        else:
            patterns = {}
            passed = info.get("best_passed") or 0
            runnable = info.get("best_runnable_total") or 0
            score = info.get("best_score") or 0
            pattern_summary = {}

        gap = runnable - passed
        audit_rows.append(
            {
                "base_slug": base,
                "slug": slug,
                "locked": locked,
                "score": round(score, 2),
                "passed": passed,
                "runnable": runnable,
                "gap": gap,
                "language": language,
                "pattern_summary": pattern_summary,
                "patterns": patterns,
                "eval_path": str(eval_path) if eval_path else None,
                "has_override": override_dir is not None,
            }
        )
    return audit_rows


def write_audit_md(rows: list[dict]):
    AUDIT_MD.parent.mkdir(parents=True, exist_ok=True)

    locked = [r for r in rows if r["locked"]]
    unlocked = [r for r in rows if not r["locked"]]

    # Group unlocked by score bands
    bands = [
        ("99-100%  (gap 1-5)", lambda r: r["score"] >= 99 and r["gap"] > 0 and r["gap"] <= 5),
        ("95-99%   (gap 6-50)", lambda r: r["score"] >= 95 and r["score"] < 99),
        ("80-95%", lambda r: r["score"] >= 80 and r["score"] < 95),
        ("50-80%", lambda r: r["score"] >= 50 and r["score"] < 80),
        ("20-50%", lambda r: r["score"] >= 20 and r["score"] < 50),
        ("1-20%", lambda r: r["score"] >= 1 and r["score"] < 20),
        ("0% (build broken / no signal)", lambda r: r["score"] == 0),
    ]

    # Pattern aggregation across unlocked
    pattern_totals = Counter()
    pattern_tools = defaultdict(set)
    for r in unlocked:
        for p, count in r["pattern_summary"].items():
            pattern_totals[p] += count
            pattern_tools[p].add(r["base_slug"])

    md = [
        "# ProgramBench Full Corpus Audit",
        f"_Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}_\n",
        "## Summary",
        f"- Total tools: **{len(rows)}**",
        f"- LOCKED 100%: **{len(locked)}**",
        f"- Remaining: **{len(unlocked)}**",
        "",
    ]

    md.append("## Pattern Distribution (failures across unlocked tools)")
    md.append("| Pattern | Total failures | # tools affected |")
    md.append("|---|---:|---:|")
    for p, count in pattern_totals.most_common():
        md.append(f"| {p} | {count} | {len(pattern_tools[p])} |")
    md.append("")

    md.append("## Tools by score band (unlocked)")
    for name, predicate in bands:
        tools = [r for r in unlocked if predicate(r)]
        if not tools:
            continue
        tools.sort(key=lambda r: (r["gap"] if r["gap"] > 0 else 999999, -r["score"]))
        md.append(f"### {name}  ({len(tools)} tools)")
        md.append("| Tool | Score | Passed/Runnable | Gap | Lang | Top failure patterns |")
        md.append("|---|---:|---:|---:|---|---|")
        for r in tools:
            ps = ", ".join(
                f"{p}={c}" for p, c in sorted(r["pattern_summary"].items(), key=lambda x: -x[1])[:3]
            )
            md.append(
                f"| {r['base_slug']} | {r['score']:.2f}% | {r['passed']}/{r['runnable']} | {r['gap']} | {r['language']} | {ps} |"
            )
        md.append("")

    md.append("## Tools grouped by dominant failure pattern (unlocked, top 5 per pattern)")
    for p in pattern_totals:
        tools = [r for r in unlocked if r["pattern_summary"].get(p, 0) > 0]
        tools.sort(key=lambda r: -r["pattern_summary"].get(p, 0))
        if not tools:
            continue
        md.append(f"### Pattern: {p}")
        md.append("| Tool | Score | Failures in this pattern |")
        md.append("|---|---:|---:|")
        for r in tools[:10]:
            md.append(f"| {r['base_slug']} | {r['score']:.2f}% | {r['pattern_summary'][p]} |")
        md.append("")

    AUDIT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {AUDIT_MD}")


def main():
    rows = build_audit()
    AUDIT_JSON.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_JSON.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {AUDIT_JSON} with {len(rows)} rows")
    write_audit_md(rows)


if __name__ == "__main__":
    main()
