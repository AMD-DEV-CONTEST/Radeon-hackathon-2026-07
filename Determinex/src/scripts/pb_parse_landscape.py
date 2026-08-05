"""
pb_parse_landscape.py — Parse Hetzner eval results and build the full failure landscape.

Reads hetzner_result/ directories for all pending_unlock tools, categorizes every
failure, writes per-tool failure_landscape.json, cross-tool campaign_landscape.json,
and repair_ticket.md for each PARTIAL result.

Usage:
  python scripts/pb_parse_landscape.py
  python scripts/pb_parse_landscape.py --tool entr
  python scripts/pb_parse_landscape.py --print-summary
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
PB_DIR = ROOT / "corpus" / "programbench"
PENDING_BASE = PB_DIR / "pending_unlock"
IN_PROGRESS = PB_DIR / "in_progress"
RESULTS_BASE = PB_DIR / "results"
INDEX_FILE = PB_DIR / "eval_index.json"
LOG_DIR = ROOT / "logs"
REGRESSIONS_LOG = LOG_DIR / "regressions.jsonl"


# ──────────────────────────────────────────────────────────────────
# FAILURE CATEGORIZATION
# ──────────────────────────────────────────────────────────────────


def categorize_failure(message: str) -> str:
    if not message:
        return "OTHER"
    m = message.lower()

    if re.search(r"(assert\s+rc|assert\s+returncode|exit\s+code|exit_code|exitcode)", m):
        return "EXIT_CODE"
    if "timed out" in m or "timeout" in m:
        return "TIMEOUT"
    if re.search(r"importerror|modulenotfounderror|no module named", m):
        return "IMPORT_ERROR"
    if re.search(r"exception|error:\s+\w+error|traceback", m):
        return "EXCEPTION"
    if re.search(r"(file not found|no such file|filenotfounderror|path.*does not exist)", m):
        return "FILE_MISSING"
    if re.search(r"(file content|wrote.*file|file.*output|file.*mismatch)", m):
        return "FILE_OUTPUT"
    if re.search(
        r"(assert\s+b?'|assert\s+b?\"|stdout.*==|==.*stdout|actual.*output|expected.*output)", m
    ):
        # Check if regex vs exact
        if re.search(r"(re\.search|re\.match|re\.fullmatch|regex|pattern)", m):
            return "STDOUT_REGEX"
        elif "not in" in m or "in stdout" in m or "found in" in m:
            return "STDOUT_MISSING"
        return "STDOUT_EXACT"
    if re.search(r"(assert.*not in|not found in|missing from)", m):
        return "STDOUT_MISSING"
    if re.search(r"(regex|pattern|re\.search|re\.match)", m):
        return "STDOUT_REGEX"
    return "OTHER"


def parse_eval_report(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def classify_outcome(counts: dict) -> str:
    p, t = counts["passed"], counts["total"]
    nr, sk, fa = counts["not_run"], counts["skipped"], counts["failed"]
    if p == t and nr == 0 and fa == 0 and sk == 0:
        return "STRICT_LOCK"
    if p + sk == t and nr == 0 and fa == 0:
        return "UPSTREAM_SKIPS"
    if fa > 0 or nr == 0:
        return "PARTIAL"
    return "PARTIAL"


def extract_counts(data: dict) -> dict:
    tr = data.get("test_results", [])
    ctr = collections.Counter(r.get("status") for r in tr)
    total = len(tr)
    passed = ctr.get("passed", 0)
    not_run = ctr.get("not_run", 0)
    skipped = ctr.get("skipped", 0)
    failed = ctr.get("failure", 0) + ctr.get("failed", 0)
    pct = (passed / total * 100) if total else 0.0
    return dict(
        total=total, passed=passed, not_run=not_run, skipped=skipped, failed=failed, pct=pct
    )


def extract_failures(data: dict) -> list[dict]:
    """Extract failed tests with categorized failure messages."""
    failures = []
    for r in data.get("test_results", []):
        status = r.get("status", "")
        if status not in ("failure", "failed", "error"):
            continue
        msg = r.get("message", "") or r.get("failure_message", "") or ""
        if not msg and "extra" in r:
            extra = r["extra"]
            if isinstance(extra, dict):
                msg = extra.get("text", "") or extra.get("message", "") or ""
            elif isinstance(extra, str):
                msg = extra
        msg_short = str(msg)[:500]
        category = categorize_failure(msg_short)
        failures.append(
            {
                "test": r.get("name", "") or r.get("test_id", "") or r.get("nodeid", ""),
                "branch": r.get("branch_id", "") or r.get("branch", ""),
                "category": category,
                "message": msg_short,
            }
        )
    return failures


# ──────────────────────────────────────────────────────────────────
# PER-TOOL LANDSCAPE
# ──────────────────────────────────────────────────────────────────


def find_eval_json(tool_dir: Path) -> Path | None:
    """Find PB eval JSON in hetzner_result/ or tool_dir root.

    PB writes {canonical}.eval.json inside the task dir inside the eval dir.
    pb_promote.py writes eval_report.json when archiving a lock.
    """
    hetzner = tool_dir / "hetzner_result"
    if hetzner.exists():
        # {canonical}.eval.json is ProgramBench's canonical output
        jsons = sorted(hetzner.rglob("*.eval.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if jsons:
            return jsons[0]
        # eval_report.json may have been placed here by pb_promote
        p = hetzner / "eval_report.json"
        if p.exists():
            return p
    # Fall back: eval_report.json at tool_dir root (written by pb_promote after lock)
    p = tool_dir / "eval_report.json"
    if p.exists():
        return p
    p = tool_dir / "latest_eval_result.json"
    if p.exists():
        return p
    return None


def find_tool_dir(slug: str) -> Path | None:
    for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300"):
        d = PENDING_BASE / pri / slug
        if d.exists():
            return d
    return None


def process_tool(slug: str) -> dict | None:
    tool_dir = find_tool_dir(slug)
    if tool_dir is None:
        return None

    eval_path = find_eval_json(tool_dir)
    if eval_path is None:
        return {"slug": slug, "outcome": "ERROR", "error": "no eval JSON found"}

    data = parse_eval_report(eval_path)
    if data is None:
        return {"slug": slug, "outcome": "ERROR", "error": "eval JSON parse failed"}

    counts = extract_counts(data)
    outcome = classify_outcome(counts)
    failures = extract_failures(data)

    # Category counts
    cat_counts = collections.Counter(f["category"] for f in failures)

    # Top 10 failures (up to 3 per category, in order of category frequency)
    top_failures = []
    seen_categories: dict[str, int] = collections.defaultdict(int)
    for f in failures:
        if seen_categories[f["category"]] < 3:
            top_failures.append(f)
            seen_categories[f["category"]] += 1
        if len(top_failures) >= 10:
            break

    # Repair score: lower = cheaper
    repair_score = 0.0
    if counts["total"] > 0 and counts["failed"] > 0:
        repair_score = round(
            (counts["failed"] / counts["total"]) * math.log(max(counts["total"], 2)),
            4,
        )

    landscape = {
        "slug": slug,
        "eval_source": str(eval_path),
        "outcome": outcome,
        "passed": counts["passed"],
        "total": counts["total"],
        "not_run": counts["not_run"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "score_pct": round(counts["pct"], 4),
        "repair_score": repair_score,
        "failure_categories": dict(cat_counts),
        "top_failures": top_failures,
        "repair_hypothesis": "",
    }

    # Write per-tool landscape
    (tool_dir / "failure_landscape.json").write_text(
        json.dumps(landscape, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return landscape


# ──────────────────────────────────────────────────────────────────
# CROSS-TOOL LANDSCAPE
# ──────────────────────────────────────────────────────────────────


def build_campaign_landscape(landscapes: list[dict]) -> dict:
    locks = [l for l in landscapes if l["outcome"] in ("STRICT_LOCK", "UPSTREAM_SKIPS")]
    partials = [l for l in landscapes if l["outcome"] == "PARTIAL"]
    regressions = [l for l in landscapes if l.get("outcome") == "REGRESSION"]
    errors = [l for l in landscapes if l.get("outcome") == "ERROR"]

    # Cross-tool failure patterns
    # For each category, which tools and how many tests
    cat_tools: dict[str, list[str]] = collections.defaultdict(list)
    cat_test_counts: dict[str, int] = collections.defaultdict(int)
    cat_examples: dict[str, str] = {}

    for l in partials:
        for cat, count in l.get("failure_categories", {}).items():
            cat_tools[cat].append(l["slug"])
            cat_test_counts[cat] += count
            if cat not in cat_examples and l.get("top_failures"):
                for f in l["top_failures"]:
                    if f["category"] == cat:
                        cat_examples[cat] = f["message"][:200]
                        break

    cross_patterns = []
    for cat, tools in sorted(cat_tools.items(), key=lambda x: -len(x[1])):
        if len(tools) < 2:
            continue
        cross_patterns.append(
            {
                "pattern": cat,
                "affected_tools": tools,
                "tool_count": len(tools),
                "test_count_total": cat_test_counts[cat],
                "example_failure": cat_examples.get(cat, ""),
                "repair_priority": "HIGH"
                if len(tools) >= 5
                else "MEDIUM"
                if len(tools) >= 3
                else "LOW",
            }
        )
    cross_patterns.sort(key=lambda x: -x["test_count_total"])

    # Per-tool repair cost ranking
    repair_queue = sorted(partials, key=lambda l: l.get("repair_score", 999))

    # Dominant cluster per tool
    tool_clusters: dict[str, str] = {}
    for l in partials:
        cats = l.get("failure_categories", {})
        if cats:
            dominant = max(cats, key=cats.get)
            tool_clusters[l["slug"]] = dominant

    # Cluster grouping
    clusters: dict[str, list[str]] = collections.defaultdict(list)
    for slug, dom in tool_clusters.items():
        clusters[dom].append(slug)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "strict_locks": len([l for l in locks if l["outcome"] == "STRICT_LOCK"]),
            "upstream_skips": len([l for l in locks if l["outcome"] == "UPSTREAM_SKIPS"]),
            "partial": len(partials),
            "regressions": len(regressions),
            "errors": len(errors),
            "total_tools": len(landscapes),
        },
        "new_locks": [l["slug"] for l in locks],
        "cross_tool_patterns": cross_patterns,
        "repair_queue": [
            {
                "slug": l["slug"],
                "failed": l["failed"],
                "total": l["total"],
                "score_pct": l["score_pct"],
                "repair_score": l["repair_score"],
                "dominant_category": max(l["failure_categories"], key=l["failure_categories"].get)
                if l["failure_categories"]
                else "UNKNOWN",
                "dominant_count": max(l["failure_categories"].values())
                if l["failure_categories"]
                else 0,
            }
            for l in repair_queue
        ],
        "tool_clusters": {
            cat: tools for cat, tools in sorted(clusters.items(), key=lambda x: -len(x[1]))
        },
        "regression_slugs": [l["slug"] for l in regressions],
        "error_slugs": [l["slug"] for l in errors],
    }


# ──────────────────────────────────────────────────────────────────
# REPAIR TICKETS
# ──────────────────────────────────────────────────────────────────

HYPOTHESIS_TEMPLATES = {
    "EXIT_CODE": (
        "The binary exits with a non-zero return code in some test branches. "
        "Likely causes: error handling returns 1 where tests expect 0, or the binary "
        "is called with arguments it doesn't recognize. Check the compile.sh invocation "
        "and compare against what passing branches use."
    ),
    "STDOUT_EXACT": (
        "The binary's stdout does not match the expected string character-for-character. "
        "Common causes: trailing newlines, CRLF vs LF line endings, whitespace differences, "
        "or field ordering in structured output. Compare the raw bytes of expected vs actual."
    ),
    "STDOUT_REGEX": (
        "The binary's stdout does not match the test's regex pattern. Check whether the "
        "pattern matches the actual format — often the issue is a version string, a path "
        "separator, or a numeric format that differs from what the regex expects."
    ),
    "STDOUT_MISSING": (
        "Expected content is absent from the binary's stdout. The binary may be writing "
        "to stderr instead of stdout, or the feature being tested is not implemented. "
        "Redirect stderr to stdout in compile.sh and re-run to diagnose."
    ),
    "TIMEOUT": (
        "Tests are timing out. The binary may be hanging waiting for input, running an "
        "infinite loop, or taking longer than the 30s pytest timeout on slow CI. "
        "Add --timeout flag in pytest.ini and ensure the binary doesn't block on stdin."
    ),
    "FILE_MISSING": (
        "The binary is expected to create a file but does not. Check the output path "
        "in compile.sh — the binary may write to a different location or require "
        "an explicit --output flag."
    ),
    "FILE_OUTPUT": (
        "The binary creates the expected file but its content does not match. "
        "Same class of fix as STDOUT_EXACT but for file content."
    ),
    "IMPORT_ERROR": (
        "A Python module required by the test conftest is missing. Check the compile.sh "
        "pip install section and add the missing package."
    ),
    "EXCEPTION": (
        "A Python exception occurs during test setup or execution. Read the traceback "
        "in the failure message carefully — it often points to a missing binary, wrong path, "
        "or an incompatible conftest fixture."
    ),
    "OTHER": (
        "No matching failure template. Read the top_failures verbatim and look for "
        "patterns — then write a specific hypothesis here."
    ),
}


def write_repair_ticket(landscape: dict, campaign: dict) -> None:
    slug = landscape["slug"]
    tool_dir = find_tool_dir(slug)
    if tool_dir is None:
        return

    dest = IN_PROGRESS / slug
    dest.mkdir(parents=True, exist_ok=True)

    cats = landscape.get("failure_categories", {})
    dominant_cat = max(cats, key=cats.get) if cats else "UNKNOWN"
    dominant_count = cats.get(dominant_cat, 0)
    hypothesis = HYPOTHESIS_TEMPLATES.get(dominant_cat, HYPOTHESIS_TEMPLATES["OTHER"])

    # Cross-tool pattern info
    cross_refs = []
    for p in campaign.get("cross_tool_patterns", []):
        if slug in p["affected_tools"] and len(p["affected_tools"]) > 1:
            others = [t for t in p["affected_tools"] if t != slug]
            cross_refs.append(f"{p['pattern']}: also affects {', '.join(others[:5])}")

    # Top 5 failures verbatim
    top5 = landscape.get("top_failures", [])[:5]
    evidence_lines = []
    for i, f in enumerate(top5, 1):
        evidence_lines.append(
            f"**{i}. `{f['test']}`** [{f['category']}]\n```\n{f['message'][:400]}\n```"
        )

    n_branches = len({f.get("branch", "") for f in landscape.get("top_failures", [])})

    evidence_block = (
        "".join(f"{e}\n\n" for e in evidence_lines)
        or "No failure data — re-run with verbose logging."
    )
    cross_refs_block = (
        "".join(f"- {ref}\n" for ref in cross_refs) or "No cross-tool pattern identified."
    )
    ticket = f"""# Repair Ticket: {slug}

## Current State
- Score: {landscape["passed"]}/{landscape["total"]} ({landscape["score_pct"]:.1f}%)
- Failures: {landscape["failed"]} tests across ~{n_branches} branches
- Dominant failure category: {dominant_cat} ({dominant_count} tests)
- Repair priority score: {landscape["repair_score"]} (lower = cheaper to fix)

## Failure Evidence
{evidence_block}

## Repair Hypothesis
{hypothesis}

## Suggested Fix
Based on `{dominant_cat}` failures in `{slug}`:
- Open `corpus/programbench/pending_unlock/*/{slug}/source/compile.sh`
- Focus on the dominant failure class first ({dominant_count} of {landscape["failed"]} failures)
- Test with: `cd T:/Dev/ProgramBench && uv run programbench eval T:/determinex-programbench/test_{slug}/ --filter <author> --force`

## Cross-Tool Pattern
{cross_refs_block}

## Repair Priority Score
{landscape["repair_score"]} (lower = cheaper to fix, higher = more tests unlocked)

_Generated: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}_
"""
    (dest / "repair_ticket.md").write_text(ticket, encoding="utf-8")


# ──────────────────────────────────────────────────────────────────
# PRINT SUMMARY
# ──────────────────────────────────────────────────────────────────


def print_summary(campaign: dict) -> None:
    s = campaign["summary"]
    print()
    print("╔" + "═" * 66 + "╗")
    print("║" + "  HETZNER BATCH RESULTS — FULL LANDSCAPE".center(66) + "║")
    print("╠" + "═" * 66 + "╣")
    print(f"║  NEW STRICT LOCKS:   {s['strict_locks']:3d} tools  → promote immediately{' ' * 19}║")
    print(f"║  NEW UPSTREAM SKIPS: {s['upstream_skips']:3d} tools  → promote to T2{' ' * 24}║")
    print(f"║  PARTIAL (fixable):  {s['partial']:3d} tools  → ranked repair queue below{' ' * 14}║")
    print(
        f"║  REGRESSIONS:        {s['regressions']:3d} tools  → investigate before touching{' ' * 11}║"
    )
    print(f"║  ERRORS:             {s['errors']:3d} tools  → check eval.log for cause{' ' * 16}║")
    print("╠" + "═" * 66 + "╣")

    patterns = campaign.get("cross_tool_patterns", [])[:5]
    if patterns:
        print("║  TOP CROSS-TOOL PATTERNS (fix once, unlock many):" + " " * 16 + "║")
        for i, p in enumerate(patterns, 1):
            line = (
                f"    {i}. {p['pattern']} — {p['tool_count']} tools, {p['test_count_total']} tests"
            )
            print(f"║  {line:<64}║")
    print("╠" + "═" * 66 + "╣")

    queue = campaign.get("repair_queue", [])[:10]
    if queue:
        print("║  REPAIR QUEUE (cheapest first):" + " " * 34 + "║")
        for i, q in enumerate(queue, 1):
            line = (
                f"    {i:2d}. {q['slug']:20s} {q['failed']:4d} fail "
                f"dom:{q['dominant_category'][:15]}"
            )
            print(f"║  {line:<64}║")
    print("╚" + "═" * 66 + "╝")


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse PB eval results and build failure landscape"
    )
    parser.add_argument("--tool", help="Process a single tool slug")
    parser.add_argument(
        "--print-summary", action="store_true", help="Load existing campaign and print summary"
    )
    args = parser.parse_args()

    campaign_path = RESULTS_BASE / "campaign_landscape.json"

    if args.print_summary:
        if campaign_path.exists():
            campaign = json.loads(campaign_path.read_text())
            print_summary(campaign)
        else:
            print("No campaign_landscape.json found. Run without --print-summary first.")
        return 0

    # Discover tools to process
    tools_to_process: list[str] = []
    if args.tool:
        tools_to_process = [args.tool]
    else:
        for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300"):
            pri_dir = PENDING_BASE / pri
            if pri_dir.exists():
                tools_to_process.extend(d.name for d in sorted(pri_dir.iterdir()) if d.is_dir())

    print(f"Processing {len(tools_to_process)} tools...")
    landscapes: list[dict] = []
    locks = []
    prev_bests = {}
    if INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        prev_bests = {e["slug"]: e.get("official_passed", 0) for e in index}

    for slug in tools_to_process:
        result = process_tool(slug)
        if result is None:
            print(f"  SKIP {slug}: no tool dir")
            continue

        outcome = result.get("outcome", "ERROR")
        prev = prev_bests.get(slug, 0)
        if result.get("passed", 0) < prev:
            result["outcome"] = "REGRESSION"

        icon = {
            "STRICT_LOCK": "🔒",
            "UPSTREAM_SKIPS": "⚡",
            "PARTIAL": "🔸",
            "REGRESSION": "⚠️",
            "ERROR": "✗",
        }.get(outcome, "?")
        nr = result.get("not_run", 0)
        print(
            f"  {icon} {slug:30s} {result.get('passed', 0)}/{result.get('total', 0)} "
            f"({'NR:' + str(nr) if nr else 'nr=0':8s}) {outcome}"
        )

        landscapes.append(result)
        if outcome in ("STRICT_LOCK", "UPSTREAM_SKIPS"):
            locks.append(slug)

    # Build campaign landscape
    campaign = build_campaign_landscape(landscapes)
    RESULTS_BASE.mkdir(parents=True, exist_ok=True)
    campaign_path.write_text(json.dumps(campaign, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCampaign landscape written to: {campaign_path}")

    # Write repair tickets for partial results
    partial_landscapes = [l for l in landscapes if l.get("outcome") == "PARTIAL"]
    print(f"Writing {len(partial_landscapes)} repair tickets...")
    for l in partial_landscapes:
        write_repair_ticket(l, campaign)

    # Log regressions
    regression_landscapes = [l for l in landscapes if l.get("outcome") == "REGRESSION"]
    if regression_landscapes:
        LOG_DIR.mkdir(exist_ok=True)
        with open(REGRESSIONS_LOG, "a", encoding="utf-8") as f:
            for l in regression_landscapes:
                f.write(
                    json.dumps(
                        {
                            "slug": l["slug"],
                            "timestamp": datetime.now(UTC).isoformat(),
                            "new_passed": l.get("passed", 0),
                            "new_total": l.get("total", 0),
                        }
                    )
                    + "\n"
                )
        print(f"\nWARNING: {len(regression_landscapes)} REGRESSIONS logged to {REGRESSIONS_LOG}")
        for l in regression_landscapes:
            prev = prev_bests.get(l["slug"], 0)
            print(f"  ⚠️  {l['slug']}: {prev} → {l.get('passed', 0)}")

    print_summary(campaign)
    return 0


if __name__ == "__main__":
    sys.exit(main())
