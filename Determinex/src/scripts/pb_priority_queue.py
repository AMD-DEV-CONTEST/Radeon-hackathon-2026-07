#!/usr/bin/env python3
"""ProgramBench Priority Queue — ranked action list for all 200 tools.

Reads corpus/programbench/eval_index.json and outputs:
- Terminal ranked table (color-coded)
- docs/programs/programbench/PB_PRIORITY_QUEUE.md (markdown)

Priority order:
  P0  T1/T2 done (skip in active queue, shown at bottom)
  P1  T2 cert candidates (f=0, nr=0, sk>0, open) → write CEILING_CERT
  P2  Hard lock (f=0, nr=0, sk=0, official_full_suite not yet true) → verify+lock
  P3  Near-lock f=1-3, nr=0 → fix trivial failures
  P4  Near-lock f=4-10, nr=0 → small patch
  P5  Near-lock f=11-30, nr=0 → moderate patch
  P6  Near-lock f=31-100, nr=0 → bigger effort
  P7  rebaseline_needed (nr>0) → remove cap + Hetzner eval
  P8  behavioral_deep
  P9  tui_wall
  P10 impossible_ceiling
  P11 unknown/unclassified

Regressions (best_known_passed > official_passed) are flagged with ⚠
"""

import io
import json
import sys

# Force UTF-8 output on Windows to handle → ✓ ⚠ ⛔ characters
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

REPO = Path(__file__).parent.parent
INDEX = REPO / "corpus/programbench/eval_index.json"
OUT_MD = REPO / "docs/programs/programbench/PB_PRIORITY_QUEUE.md"

# ANSI colours for terminal
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
GREY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_index() -> list[dict]:
    with open(INDEX, encoding="utf-8") as f:
        return json.load(f)


def is_alias(e: dict) -> bool:
    """Return True for duplicate/alias rows that should not appear in the queue."""
    if e.get("alias_of"):
        return True
    # tier_1_perfect and tier_5_ceiling_confirmed are legacy alias tiers
    if e.get("tier") in ("tier_1_perfect", "tier_5_ceiling_confirmed"):
        return True
    # eval-copy slugs (e.g. bore.8e059cd.eval)
    if e.get("slug", "").endswith(".eval"):
        return True
    return False


def canonical_tier(e: dict) -> str:
    t = e.get("tier", "")
    if t in ("strict_lock", "ceiling_certified", "open"):
        return t
    if t in ("tier_1_perfect",):
        return "strict_lock"
    return "open"  # unknown → treat as open


def score_pct(passed, total) -> str:
    if total and total > 0:
        return f"{100 * passed / total:.1f}%"
    return "?"


def effective_failed(e: dict) -> int:
    """Compute failures from total-passed if official_failed is missing/stale."""
    f = e.get("official_failed", 0) or 0
    p = e.get("official_passed", 0) or 0
    t = e.get("official_total", 0) or 0
    nr = e.get("official_not_run", 0) or 0
    sk = e.get("official_skipped", 0) or 0
    computed = max(0, t - p - nr - sk)
    return max(f, computed)


def priority_key(e: dict) -> tuple:
    """Return (priority_int, sort_key) — lower = higher priority."""
    t = canonical_tier(e)
    f = effective_failed(e)
    nr = e.get("official_not_run", 0) or 0
    sk = e.get("official_skipped", 0) or 0
    sub = e.get("sub_bucket", "") or ""
    full = e.get("official_full_suite_resolved", False)

    if t == "strict_lock":
        return (100, 0)
    if t == "ceiling_certified":
        return (101, 0)

    # acquisition_needed or 0/0 denominator — cannot be classified, queue last
    total = e.get("official_total", 0) or 0
    if sub == "acquisition_needed" or total == 0:
        return (60, 0)

    # impossible ceiling — lowest useful priority
    if sub == "impossible_ceiling" or e.get("ceiling_confirmed"):
        return (50, f)

    # T2 cert candidate: f=0, nr=0, sk>0
    if f == 0 and nr == 0 and sk > 0:
        return (1, sk)

    # phantom-100: display 100% but Section 5 unresolved — NOT a lock candidate
    # Route after T2 certs, before near-locks, with explicit label
    status = e.get("status", "") or ""
    if (total > 0 and e.get("official_passed", 0) == total) or (
        e.get("official_score_pct", 0) or 0
    ) >= 100:
        if not full or status == "submetric_claim":
            return (2, 0)  # P2 slot — but next_action will label as PHANTOM

    # hard lock: f=0, nr=0, sk=0, official_full_suite_resolved
    if f == 0 and nr == 0 and sk == 0 and full:
        return (2, 0)

    # tui_wall and behavioral_deep must be checked before nr==0 near-lock block
    # (tools with f>0 due to TUI behavioral failures should NOT appear as near-locks)
    if sub == "tui_wall":
        return (35, f)
    if sub == "behavioral_deep":
        return (30, f)

    # near-lock tiers by failure count (nr=0 required, no tui/behavioral sub_bucket)
    if nr == 0:
        if f <= 3:
            return (3, f)
        elif f <= 10:
            return (4, f)
        elif f <= 30:
            return (5, f)
        elif f <= 100:
            return (6, f)
        else:
            return (7, f)

    # rebaseline (nr > 0)
    if sub == "rebaseline_needed" or nr > 0:
        # rank by not_run count (fewer = closer to done)
        return (20, nr)

    return (40, f)


def next_action(e: dict) -> str:
    t = canonical_tier(e)
    f = effective_failed(e)
    nr = e.get("official_not_run", 0) or 0
    sk = e.get("official_skipped", 0) or 0
    sub = e.get("sub_bucket", "") or ""
    full = e.get("official_full_suite_resolved", False)
    total = e.get("official_total", 0) or 0

    if t == "strict_lock":
        return "✓ T1 LOCKED"
    if t == "ceiling_certified":
        return "✓ T2 CEILING CERT"

    if sub == "acquisition_needed" or total == 0:
        return "Build override + run Hetzner eval — no fixtures loaded"

    if sub == "impossible_ceiling" or e.get("ceiling_confirmed"):
        note = (e.get("ceiling_note") or e.get("ceiling_reason") or "structural blocker")[:60]
        return f"⛔ IMPOSSIBLE — {note}"

    if f == 0 and nr == 0 and sk > 0:
        return f"Write CEILING_CERT.md ({sk} sk) → T2"

    # phantom-100: 100% display but not officially resolved
    status = e.get("status", "") or ""
    if (total > 0 and e.get("official_passed", 0) == total) or (
        e.get("official_score_pct", 0) or 0
    ) >= 100:
        if status == "submetric_claim":
            return "⚠PHANTOM(submetric) — bidir conftest must clear before lock"
        if not full:
            return "⚠PHANTOM(unresolved) — Section 5 raw parse required"

    if f == 0 and nr == 0 and sk == 0 and not full:
        return "Verify eval integrity → archive → T1"

    # tui_wall and behavioral_deep before generic near-lock (must match priority_key order)
    if sub == "tui_wall":
        if nr > 0:
            return f"Add tmux support → eval ({nr} not_run)"
        return f"TUI behavioral (not code-patchable): {f} failures — tmux keyboard handling"
    if sub == "behavioral_deep":
        return f"Deep behavioral analysis needed ({f} failures — quarantined, no one-shot patches)"

    if nr == 0 and f > 0:
        pct_fail = 100 * f / total if total else 0
        # sk>0 means T2 ceiling even if failures clear — never route to T1
        target = "T1 lock" if sk == 0 else "T2 cert (sk>0 blocks T1)"
        if f <= 3:
            return f"Fix {f} failure{'s' if f > 1 else ''} → {target}"
        elif f <= 10:
            return f"Fix {f} failures ({pct_fail:.1f}% fail) → {target}"
        elif f <= 30:
            return f"Fix {f} failures ({pct_fail:.1f}% fail) → near {target}"
        else:
            return f"Fix {f} failures ({pct_fail:.1f}% fail) — significant work"

    if nr > 0:
        return f"Remove collection cap + Hetzner eval ({nr} not_run)"

    return f"Investigate (f={f}, nr={nr}, sk={sk})"


def regression_flag(e: dict) -> str:
    bk = e.get("best_known_passed")
    op = e.get("official_passed", 0)
    if bk and bk > op:
        return f"⚠ REGRESSED (best={bk}, now={op})"
    return ""


def format_score(e: dict) -> str:
    p = e.get("official_passed", "?")
    t = e.get("official_total", "?")
    f = effective_failed(e)
    nr = e.get("official_not_run", 0) or 0
    sk = e.get("official_skipped", 0) or 0
    if p == "?" or t == "?":
        return "?/?  "
    pct = f"{100 * p / t:.1f}" if t else "?"
    detail = []
    if f:
        detail.append(f"f={f}")
    if nr:
        detail.append(f"nr={nr}")
    if sk:
        detail.append(f"sk={sk}")
    detail_str = " " + " ".join(detail) if detail else ""
    return f"{p}/{t} ({pct}%){detail_str}"


def priority_label(p: int) -> str:
    labels = {
        1: "P1 T2-cert",
        2: "P2 verify+lock",
        3: "P3 f≤3",
        4: "P4 f≤10",
        5: "P5 f≤30",
        6: "P6 f≤100",
        7: "P7 f>100",
        20: "P7 rebaseline",
        30: "P8 behavioral",
        35: "P9 tui_wall",
        40: "P10 unclear",
        50: "P10 impossible",
        100: "-- T1 locked",
        101: "-- T2 cert'd",
    }
    return labels.get(p, f"P{p}")


def color_for_priority(p: int) -> str:
    if p in (100, 101):
        return GREY
    if p == 1:
        return GREEN + BOLD
    if p == 2:
        return GREEN
    if p in (3, 4):
        return CYAN
    if p in (5, 6, 7):
        return YELLOW
    if p == 50:
        return RED
    return RESET


def build_rows(data: list[dict]) -> list[dict]:
    rows = []
    for e in data:
        if is_alias(e):
            continue
        pk, sk2 = priority_key(e)
        rows.append(
            {
                "entry": e,
                "slug": e.get("slug", "?"),
                "priority": pk,
                "sort_key": (pk, sk2),
                "tier": canonical_tier(e),
                "score": format_score(e),
                "action": next_action(e),
                "regression": regression_flag(e),
                "sub_bucket": e.get("sub_bucket", "") or "",
            }
        )
    rows.sort(key=lambda r: r["sort_key"])
    return rows


def render_terminal(rows: list[dict]) -> None:
    # Group by priority label
    last_p = None
    print()
    print(f"{BOLD}{'===' * 25}{RESET}")
    print(f"{BOLD}  ProgramBench Priority Queue  —  {len(rows)} canonical tools{RESET}")
    print(f"{BOLD}{'===' * 25}{RESET}")
    print()

    for r in rows:
        p = r["priority"]
        label = priority_label(p)
        if label != last_p:
            if last_p is not None:
                print()
            print(f"{BOLD}{label:12s}  {'─' * 60}{RESET}")
            last_p = label

        col = color_for_priority(p)
        reg = f"  {YELLOW}[{r['regression']}]{RESET}" if r["regression"] else ""
        print(f"  {col}{r['slug']:45s}{RESET}  {r['score']:35s}  {r['action']}{reg}")

    print()
    # Summary
    t1 = sum(1 for r in rows if r["priority"] == 100)
    t2 = sum(1 for r in rows if r["priority"] == 101)
    active = sum(1 for r in rows if r["priority"] < 100)
    regressions = sum(1 for r in rows if r["regression"])
    print(
        f"{GREY}T1 locked: {t1}  T2 cert'd: {t2}  Active: {active}  Regressions: {regressions}{RESET}"
    )
    print()


def render_markdown(rows: list[dict]) -> str:
    from datetime import date

    today = date.today().isoformat()

    lines = [
        "# ProgramBench Priority Queue",
        "",
        f"**Generated:** {today}  ",
        "**Source:** `corpus/programbench/eval_index.json`  ",
        "",
        "Priority order: P1 (T2-cert) → P2 (verify+lock) → P3-P6 (fix failures) → P7 (rebaseline) → P8-P10 (hard/impossible)",
        "",
        "⚠ = best_known_passed > official_passed (regression detected)",
        "",
    ]

    # Summary block
    t1 = sum(1 for r in rows if r["priority"] == 100)
    t2 = sum(1 for r in rows if r["priority"] == 101)
    active = sum(1 for r in rows if r["priority"] < 100)
    regressions = sum(1 for r in rows if r["regression"])
    lines += [
        "## Summary",
        "",
        "| Bucket | Count |",
        "|--------|-------|",
        f"| T1 strict_lock (done) | {t1} |",
        f"| T2 ceiling_cert (done) | {t2} |",
        f"| Active (needs work) | {active} |",
        f"| Regressions flagged | {regressions} |",
        "",
        "## Ranked Queue",
        "",
        "| # | Priority | Tool | Score | f | nr | sk | Next Action | Reg? |",
        "|---|----------|------|-------|---|----|----|-------------|------|",
    ]

    for i, r in enumerate(rows, 1):
        e = r["entry"]
        f = e.get("official_failed", 0) or 0
        nr = e.get("official_not_run", 0) or 0
        sk = e.get("official_skipped", 0) or 0
        op = e.get("official_passed", "?")
        t = e.get("official_total", "?")
        pct = f"{100 * op / t:.1f}%" if isinstance(op, int) and isinstance(t, int) and t else "?"
        score_md = f"{op}/{t} ({pct})"
        reg_md = "⚠" if r["regression"] else ""
        action_short = r["action"][:80]
        lines.append(
            f"| {i} | {priority_label(r['priority'])} | `{r['slug']}` | {score_md} | {f} | {nr} | {sk} | {action_short} | {reg_md} |"
        )

    lines += [
        "",
        "---",
        f"*Auto-generated by `scripts/pb_priority_queue.py` on {today}*",
    ]
    return "\n".join(lines) + "\n"


def main():
    data = load_index()
    rows = build_rows(data)

    no_color = "--no-color" in sys.argv or not sys.stdout.isatty()

    if no_color:
        # Simple print without ANSI
        last_p = None
        for r in rows:
            label = priority_label(r["priority"])
            if label != last_p:
                print(f"\n{label}  {'-' * 50}")
                last_p = label
            reg = f"  [REGRESSED: {r['regression']}]" if r["regression"] else ""
            print(f"  {r['slug']:45s}  {r['score']:35s}  {r['action']}{reg}")
    else:
        render_terminal(rows)

    # Always write markdown
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    md = render_markdown(rows)
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"Markdown written → {OUT_MD}")

    # Quick regression summary
    reg_rows = [r for r in rows if r["regression"]]
    if reg_rows:
        print(f"\n{'⚠' * 3} REGRESSIONS DETECTED {'⚠' * 3}")
        for r in reg_rows:
            e = r["entry"]
            bk = e.get("best_known_passed")
            op = e.get("official_passed")
            print(f"  {r['slug']:40s}  best_known={bk}  official={op}  → {r['action']}")


if __name__ == "__main__":
    main()
