#!/usr/bin/env python3
"""determinex_xray.py -- the PreLook. X-ray a ProgramBench tool in one look.

Given a tool's eval report (+ its slug -> upstream repo@commit), produce the
complete prelook diagnosis WITHOUT guessing:
  - failure-mode class (NO_BINARY / BROKEN_STUB / BEHAVIORAL / NOT_RUN / NEAR_LOCK)
  - the upstream source pointer (github.com/<author>/<tool>@<sha>, from the slug)
  - every failing test FUNCTION grouped by cause + counts + an expected snippet
  - a to-fix list keyed by category

The local triage (default) is cheap, no Docker. `--battery` adds the real-binary
scenario sweep (build upstream + observe exact I/O) used when reimplementing.

Codifies corpus/programbench/REIMPL_PLAYBOOK.md prelook. Composes determinex_autofix's
failure classification when present; otherwise uses built-in categorization.

Usage:
  python scripts/determinex_xray.py --report <eval.json>
  python scripts/determinex_xray.py --all <dir-of-*.eval.json> [--json out.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

PREFIX = re.compile(r"^(eval\.tests\.|tests\.)")


def slug_to_upstream(slug: str) -> tuple[str, str]:
    """`author__tool.sha` -> (github url, commit). Empty commit if absent."""
    base = slug
    commit = ""
    m = re.match(r"^(.*?)\.([0-9a-f]{6,40})(?:_.*)?$", slug)
    if m:
        base, commit = m.group(1), m.group(2)
    if "__" in base:
        author, tool = base.split("__", 1)
        return f"https://github.com/{author}/{tool}", commit
    return base, commit


def strip(n: str) -> str:
    return PREFIX.sub("", n)


# Failure categories — the cause buckets the prelook recognizes.
_CATS = [
    (
        "no_binary",
        re.compile(r"returncode=127|: not found|no such file or directory.*executable", re.I),
    ),
    ("broken_stub", re.compile(r"errno 2|failed to process|interactive tui|driven by tmux", re.I)),
    (
        "arg_validation",
        re.compile(r"a value is required|unexpected argument|usage:|error: unrecognized", re.I),
    ),
    ("byte_format", re.compile(r"\b\d+(\.\d+)?\s*(B|KiB|MiB|GiB|b)\b", re.I)),
    ("version", re.compile(r"version|\bv?\d+\.\d+\.\d+\b", re.I)),
    ("tui_ceiling", re.compile(r"tmux|pexpect|libtmux|tui|interactive|curses", re.I)),
    ("regex_edge", re.compile(r"AssertionError.*(extract|match|portion)", re.I)),
    ("golden_exact", re.compile(r"\.golden|stdout ==|read_text\(\)", re.I)),
]


def categorize(text: str) -> str:
    t = text or ""
    for name, pat in _CATS:
        if pat.search(t):
            return name
    if "assertionerror" in t.lower() or "assert " in t.lower():
        return "behavioral"
    return "other"


def failure_mode(tr: list) -> str:
    c = Counter(x.get("status", "?") for x in tr)
    total = len(tr)
    nr = c.get("not_run", 0)
    fail = c.get("failure", 0) + c.get("failed", 0) + c.get("error", 0)
    passed = c.get("passed", 0)
    pct = passed / total if total else 0
    # sample failing text
    blob = " ".join(
        ((x.get("extra", {}) or {}).get("text", "") if isinstance(x.get("extra"), dict) else "")
        for x in tr
        if x.get("status") in ("failure", "failed", "error")
    )[:4000].lower()
    if "returncode=127" in blob or (": not found" in blob):
        return "NO_BINARY"
    if "errno 2" in blob or "failed to process" in blob or "driven by tmux" in blob:
        return "BROKEN_STUB"
    if pct >= 0.95:
        return "NEAR_LOCK"
    if nr > fail and nr > 20:
        return "NOT_RUN"
    if pct < 0.5:
        return "LOW_BUILD_SUSPECT"
    return "BEHAVIORAL"


def load_spec(slug: str, tasks_dir: str) -> dict | None:
    """Read the canonical PB tests.json for a slug: {branch_sha: {ignored,
    ignore_reason, tests:[ids]}}. This is the ground-truth denominator."""
    p = Path(tasks_dir) / slug / "tests.json"
    if not p.exists():
        # tolerate short-slug dirs vs full-slug report names
        cands = list(Path(tasks_dir).glob(f"{slug.split('.')[0]}*/tests.json"))
        if not cands:
            return None
        p = cands[0]
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("branches", {})
    except Exception:
        return None


_EXEC = ("passed", "failure", "failed", "error")


def cross_check(tr: list, branches: dict) -> dict:
    """Diff what the eval EMITTED against what tests.json EXPECTS, then name the
    ONE primary cause so the next move is unambiguous — no guessing, no lazy flag.

    The trap this avoids (proven on melody): a bidir-prefix difference makes it
    *look* like a harness suppression, but the binary actually fails most tests.
    So we separate two orthogonal axes and report both honestly:
      - BEHAVIORAL pass rate = passed / executed (prefix-stripped, not_run excluded)
        => does the binary actually do the task? This is ground truth.
      - SUPPRESSION = not_run constructs + emitted-under-a-prefix-not-in-spec
        => tests that never got a fair verdict (collection cap / prefix / build cut).
    Primary cause = whichever dominates; behavioral gap always wins when present,
    because fixing the harness can't pass a construct the binary gets wrong."""
    expected: set[str] = set()
    ignored_tests: set[str] = set()
    ignored_branches: dict[str, str] = {}
    for sha, b in branches.items():
        ts = set(b.get("tests", []))
        if b.get("ignored"):
            ignored_branches[sha[:12]] = b.get("ignore_reason", "") or "(no reason given)"
            ignored_tests |= ts
        else:
            expected |= ts
    emitted = {x.get("name", "") for x in tr}
    extra = emitted - expected - ignored_tests  # emitted but not in spec -> prefix/mismatch

    # Per-construct status buckets (prefix-stripped). skipped, not_run, and executed
    # are THREE different worlds and must never be conflated:
    #   executed  = produced pass/fail/error  -> the binary's real behavior
    #   skipped   = test emitted a skip       -> upstream ceiling OR env-MATCH to un-skip
    #   not_run   = no result at all          -> harness suppression (cap/prefix/build cut)
    by: dict[str, list[str]] = defaultdict(list)
    for x in tr:
        by[strip(x.get("name", ""))].append(x.get("status", "?"))
    executed = [k for k, v in by.items() if any(s in _EXEC for s in v)]
    passed_u = [k for k in executed if all(s == "passed" for s in by[k] if s in _EXEC)]
    beh_pct = round(100 * len(passed_u) / len(executed), 1) if executed else 0.0

    # NOT_RUN analysis at ROW level — the official metric scores rows, and the only way
    # to tell a recoverable prefix-double from a genuinely-uncollected test is to ask:
    # does this not_run row have a PASSING twin under the other prefix?
    #   YES -> the pass was emitted under the wrong prefix; its expected twin reads
    #          not_run. Emitting only the expected prefix recovers it -> PREFIX_MISMATCH.
    #   NO  -> the test simply never ran (env/cap/build cut) -> NOT_RUN_SUPPRESSION,
    #          which needs env-MATCH or cap removal, not a prefix tweak.
    passed_bases = {strip(x.get("name", "")) for x in tr if x.get("status") == "passed"}
    nr_rows = [x.get("name", "") for x in tr if x.get("status") == "not_run"]
    sk_rows = [x.get("name", "") for x in tr if x.get("status") == "skipped"]
    nr_mirror = sum(1 for n in nr_rows if strip(n) in passed_bases)
    nr_genuine = len(nr_rows) - nr_mirror

    # name the single primary cause -> the next action. ORDER: behavioral truth first,
    # then genuine uncollected, then prefix-doubles, then skips, then done.
    thr = 0.02 * max(1, len(tr))
    if not executed:
        primary = "NO_EXECUTION (build/collection failed — fix mode first)"
    elif beh_pct < 90:
        primary = f"BEHAVIORAL_GAP (binary fails {len(executed) - len(passed_u)}/{len(executed)} executed → reimpl work, NOT a harness fix)"
    elif nr_genuine > thr:
        primary = f"NOT_RUN_SUPPRESSION ({nr_genuine} tests never ran, no passing twin — env-MATCH / cap removal / build fixture, NOT reimpl or prefix)"
    elif nr_mirror > thr:
        primary = f"PREFIX_MISMATCH ({nr_mirror} not_run rows mirror a PASSING twin under the other prefix — emit only the expected prefix in bidir/conftest)"
    elif len(sk_rows) > thr:
        primary = f"SKIP_CEILING_OR_MATCH ({len(sk_rows)} skipped rows — verify vs upstream: unprovisionable skip = ceiling; provisionable = MATCH the env to un-skip)"
    else:
        primary = (
            "NEAR_LOCK (behavioral≈100%, ~0 not_run/skip → official ~100%; residual = finicky tail)"
        )

    return {
        "expected_non_ignored": len(expected),
        "ignored_branches": ignored_branches,
        "ignored_test_count": len(ignored_tests),
        "behavioral_pass": f"{len(passed_u)}/{len(executed)} = {beh_pct}%",
        "skipped_rows": len(sk_rows),
        "not_run_genuine": nr_genuine,
        "not_run_prefix_mirror": nr_mirror,
        "emitted_not_in_spec": len(extra),
        "primary_cause": primary,
        "harness_flag": primary.split(" ", 1)[0],
    }


def xray(report_path: str, tasks_dir: str | None = None) -> dict:
    d = json.load(open(report_path, encoding="utf-8"))
    tr = d.get("test_results") or []
    slug = (
        os.path.basename(report_path)[: -len(".eval.json")]
        if report_path.endswith(".eval.json")
        else os.path.basename(os.path.dirname(report_path))
    )
    url, commit = slug_to_upstream(slug)
    # unique pass/total
    by = defaultdict(list)
    for x in tr:
        by[strip(x.get("name", ""))].append(x.get("status", "?"))
    up = sum(1 for n, s in by.items() if all(z == "passed" for z in s))
    ut = len(by)
    # failing functions grouped + categorized
    funcs: defaultdict[str, list] = defaultdict(lambda: [0, "", "other"])
    for x in tr:
        if x.get("status") not in ("failure", "failed", "error"):
            continue
        fn = strip(x.get("name", "")).split("[")[0].split(".")[-1]
        funcs[fn][0] += 1
        if not funcs[fn][1]:
            t = (
                (x.get("extra", {}) or {}).get("text", "")
                if isinstance(x.get("extra"), dict)
                else ""
            )
            ls = [l for l in t.splitlines() if l.strip()]
            funcs[fn][1] = ls[-1][:80] if ls else ""
            funcs[fn][2] = categorize(t)
    cat_counts = Counter(v[2] for v in funcs.values())
    out: dict[str, object] = {
        "slug": slug,
        "upstream": url,
        "commit": commit,
        "mode": failure_mode(tr),
        "unique": f"{up}/{ut}",
        "pct": round(100 * up / ut, 1) if ut else 0,
        "n_fail_funcs": len(funcs),
        "to_fix_by_category": dict(cat_counts.most_common()),
        "fail_funcs": [
            {"fn": fn, "count": n, "cat": cat, "expected": snip}
            for fn, (n, snip, cat) in sorted(funcs.items(), key=lambda x: -x[1][0])
        ],
    }
    # canonical spec cross-check (the ground-truth denominator + harness-issue detection)
    if tasks_dir:
        branches = load_spec(slug, tasks_dir)
        if branches is not None:
            out["spec_crosscheck"] = cross_check(tr, branches)
        else:
            out["spec_crosscheck"] = {"harness_flag": "NO_tests.json_FOUND"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=str)
    ap.add_argument("--all", type=str, help="dir of *.eval.json")
    ap.add_argument(
        "--tasks-dir",
        type=str,
        default=os.environ.get("PB_TASKS_DIR", ""),
        help="dir of <slug>/tests.json canonical specs (enables spec cross-check)",
    )
    ap.add_argument("--json", type=str)
    args = ap.parse_args()
    td = args.tasks_dir or None

    if args.report:
        out = xray(args.report, td)
        print(json.dumps(out, indent=2))
        if args.json:
            Path(args.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
        return 0

    if args.all:
        reports = glob.glob(os.path.join(args.all, "*.eval.json"))
        index = []
        for rp in reports:
            try:
                index.append(xray(rp, td))
            except Exception as e:
                index.append({"slug": os.path.basename(rp), "error": str(e)})
        index.sort(key=lambda r: r.get("pct", 0))
        modes = Counter(r.get("mode") for r in index if "mode" in r)
        flags = Counter(
            (r.get("spec_crosscheck") or {}).get("harness_flag", "no-spec")
            for r in index
            if "mode" in r
        )
        print(f"X-RAYED {len(index)} tools.  modes: {dict(modes)}")
        if td:
            print(f"  harness flags (from tests.json cross-check): {dict(flags)}")
        for r in index:
            if "error" in r:
                continue
            xc = r.get("spec_crosscheck") or {}
            hf = xc.get("harness_flag", "")
            tag = f"  <<{hf}>>" if hf and hf != "ok" else ""
            print(
                f"  {r['pct']:5}%  {r['mode']:18} {r['slug'][:40]:40} "
                f"fix:{r['to_fix_by_category']}{tag}"
            )
        if args.json:
            Path(args.json).write_text(json.dumps(index, indent=2), encoding="utf-8")
            print(f"\nfull diagnosis -> {args.json}")
        return 0

    ap.error("need --report or --all")


if __name__ == "__main__":
    raise SystemExit(main())
