"""
Generate GROUND_TRUTH.md from eval_index.json — the single source of truth.
Run this script every time a lock is certified (it's the Driver's write step).
Never edit GROUND_TRUTH.md by hand.
"""

import datetime
import json
import pathlib
from collections import Counter

BASE = pathlib.Path(__file__).resolve().parent.parent
INDEX_PATH = BASE / "corpus" / "programbench" / "eval_index.json"
OUT_PATH = BASE / "corpus" / "programbench" / "GROUND_TRUTH.md"

with open(INDEX_PATH, encoding="utf-8", errors="replace") as f:
    tools = json.load(f)

canonical = [t for t in tools if not t.get("alias_of") and not t.get("canonical_slug")]
aliases = [t for t in tools if t.get("alias_of") or t.get("canonical_slug")]

strict = [t for t in canonical if t.get("official_full_suite_resolved") is True]
strict.sort(key=lambda t: t.get("slug", t.get("id", "")))

# Tier counts from the tier field (set by pb_tier_classify.py)
tier_counter: Counter[str] = Counter()
bucket_counter: Counter[str] = Counter()
for t in canonical:
    tier = t.get("tier", "open")
    bucket = t.get("sub_bucket")
    tier_counter[tier] += 1
    if bucket:
        bucket_counter[bucket] += 1

total_strict = len(strict)
total_canonical = len(canonical)
total_tools = 200  # canonical PB task count

# Guard: canonical count must equal 200
assert total_canonical == total_tools, (
    f"eval_index has {total_canonical} non-alias rows, expected {total_tools}. "
    "Demote or merge stray rows."
)

# Guard: tier totals must equal 200
tier_total = sum(tier_counter.values())
assert tier_total == total_tools, (
    f"Tier totals sum to {tier_total}, expected {total_tools}. "
    "Run pb_tier_classify.py to reclassify."
)

now_utc = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

lines = [
    "# ProgramBench Ground Truth",
    "> **GENERATED** from `eval_index.json` — never edit by hand.",
    f"> Last updated: {now_utc} (UTC)",
    "> Run `python3 scripts/gen_ground_truth.py` after every lock certification.",
    "",
    "## Official Score",
    "",
    f"**{total_strict} / {total_tools} = {total_strict / total_tools * 100:.1f}% resolved (strict)**",
    "",
    "- Strict lock (T1) definition: `passed == total`, `not_run == 0`, `skipped == 0`, `failed == 0`",
    "- Source of truth: `corpus/programbench/eval_index.json` (Section 5 certified only)",
    f"- Aliases ({len(aliases)} rows demoted, not counted) — see Appendix",
    "",
    "## Three-Tier Ledger",
    "",
    "Completion = T3 reaches zero unclassified. Total must always equal 200.",
    "",
    "| Tier | Sub-bucket | Definition | Count |",
    "|------|-----------|-----------|-------|",
    f"| **T1 strict_lock** | — | passed==total, 0 fail, 0 nr, 0 sk | **{tier_counter['strict_lock']}** |",
    f"| **T2 ceiling_certified** | — | fail=0, nr=0, sk>0, CEILING_CERT.md present | **{tier_counter['ceiling_certified']}** |",
    f"| T3 open | near_miss | ≥98% or T2 candidate (cert pending) | {bucket_counter['near_miss']} |",
    f"| T3 open | impossible_ceiling | proven structural ceiling < 100% | {bucket_counter['impossible_ceiling']} |",
    f"| T3 open | tui_wall | TUI/tmux is the primary remaining blocker | {bucket_counter['tui_wall']} |",
    f"| T3 open | rebaseline_needed | stale/low data; needs fresh mechanical pass | {bucket_counter['rebaseline_needed']} |",
    f"| T3 open | behavioral_deep | <50% or complex behavioral failures | {bucket_counter['behavioral_deep']} |",
    f"| **TOTAL** | | | **{tier_total}** |",
    "",
    "> **Naming rule (absolute):** T2 ceiling_certified is NEVER called a lock in any artifact.",
    "> Headline = strict count only. Publish format: T1 and T2 as separate numbers, never summed.",
    "",
    f"**Distance-to-completion:** T3 total = {tier_counter['open']} rows remaining.",
    f"- Near-term (T2 sweep): {bucket_counter['near_miss']} near_miss + {bucket_counter['impossible_ceiling']} impossible_ceiling candidates",
    f"- Mechanical (A4 rebaseline): {bucket_counter['rebaseline_needed']} rebaseline_needed",
    f"- Research: {bucket_counter['tui_wall']} tui_wall + {bucket_counter['behavioral_deep']} behavioral_deep",
    "",
    f"## Confirmed Strict Locks ({total_strict})",
    "",
    "| Slug | Passed | Total | Archive |",
    "|------|--------|-------|---------|",
]

for t in strict:
    slug = t.get("slug", t.get("id", "?"))
    passed = t.get("official_passed", t.get("passed", "?"))
    total = t.get("official_total", t.get("total", "?"))
    archive = t.get("archive_path", t.get("locked_archive", ""))
    archive_str = f"`{archive}`" if archive else "—"
    lines.append(f"| `{slug}` | {passed} | {total} | {archive_str} |")

lines += [
    "",
    "## Appendix — Alias Rows (not counted)",
    "",
    "These eval_index rows are duplicates of the above (same PB task, different branch/method).",
    "",
    "| Alias Slug | Alias Of |",
    "|-----------|---------|",
]
for t in sorted(aliases, key=lambda x: x.get("slug", "")):
    slug = t.get("slug", t.get("id", "?"))
    canonical_slug = t.get("alias_of", t.get("canonical_slug", "?"))
    lines.append(f"| `{slug}` | `{canonical_slug}` |")

lines += [
    "",
    "---",
    "*Determinex · Ryan Gurganious · auto-generated from eval_index.json*",
    "",
]

content = "\n".join(lines)
with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)

print(f"Written: {OUT_PATH} ({len(content):,} bytes)")
print(f"Strict locks (T1): {total_strict}/200 = {total_strict / 200 * 100:.1f}%")
print(f"Ceiling certified (T2): {tier_counter['ceiling_certified']}")
print(
    f"T3 open: {tier_counter['open']} "
    f"(near_miss={bucket_counter['near_miss']}, "
    f"impossible_ceiling={bucket_counter['impossible_ceiling']}, "
    f"tui_wall={bucket_counter['tui_wall']}, "
    f"rebaseline_needed={bucket_counter['rebaseline_needed']}, "
    f"behavioral_deep={bucket_counter['behavioral_deep']})"
)
print(f"Aliases demoted: {len(aliases)}")
