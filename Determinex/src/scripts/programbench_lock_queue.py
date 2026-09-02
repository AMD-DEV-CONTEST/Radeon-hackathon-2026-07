"""scripts/programbench_lock_queue.py — rank ProgramBench tools by P(lock).

To get 100/200, you don't grind tools in alphabetical order — you grind the
ones one universal patch away from a lock first. This module computes a
heuristic P(lock) score per tool and emits a ranked queue with reasons.

Signals used (each contributes a per-tool score in [0, 1]):

  score_band        current score normalized into a band:
                      [99, 100]  -> 1.00  (already locked or near-locked)
                      [80, 99)   -> 0.80
                      [60, 80)   -> 0.55
                      [40, 60)   -> 0.30
                      [20, 40)   -> 0.15
                      [0, 20)    -> 0.05

  family_concentration  share of failures concentrated in the single top
                        family. High concentration means one fix covers most
                        of the gap; diffuse failure means per-tool work.

  test_count_inv    fewer tests = cheaper to lock. Mapped log-inverse so a
                    300-test tool scores meaningfully higher than a 6000-test
                    tool.

  language_transfer if the tool's upstream language matches a language with
                    at least one verified lock (zoxide/ripgrep -> Rust;
                    htmlq -> Rust/HTML; ripsecrets -> Rust), apply a bonus.

  fixable_top_family bonus when the top failure family has a known universal
                     patch in the advisor's profile (tier-1 + tier-2 are real
                     candidates; "other" and "hash_executable_fail" are not).

The final P(lock) is a weighted sum. Weights are intentionally simple — the
advisor uses this as INPUT to ranking, not as a fully calibrated probability.
Rerunning after iter1 will re-rank based on the new score distribution.

CLI:
    python scripts/programbench_lock_queue.py \\
        [--run-id mass_run_v2_base] \\
        [--top 25]                              \\
        [--out logs/mass_run_v2/]               \\
        [--audit corpus/programbench/_strategy/_residual_audit.json]

Output:
    {out}/{run_id}_lock_queue.{json,md}
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
import run_ledger as _rl  # type: ignore[import-not-found]
from determinex_pb_taxonomy import tier_of  # type: ignore[import-not-found]
from run_ledger import _open_db, rebuild_index  # type: ignore[import-not-found]

_DEFAULT_OUT = Path(
    os.environ.get(
        "DETERMINEX_PB_LOCK_QUEUE_OUT",
        str(_SCRIPTS.parent / "logs" / "mass_run_v2"),
    )
)

_DEFAULT_AUDIT = _SCRIPTS.parent / "corpus" / "programbench" / "_strategy" / "_residual_audit.json"

# Languages where Determinex has at least one verified 100% lock today
# (zoxide=rust, ripgrep=rust, htmlq=rust, ripsecrets=rust, yj=go — though yj
# is currently "needs rebuild" per the README).
LANGUAGES_WITH_LOCKS: frozenset[str] = frozenset({"rs", "rust", "go"})

# Weights for the linear combination — intentionally simple
W_SCORE_BAND = 0.35
W_CONCENTRATION = 0.25
W_TEST_COUNT_INV = 0.15
W_LANGUAGE_TRANSFER = 0.10
W_FIXABLE_FAMILY = 0.15


# ---------------------------------------------------------------------------
# Signal computations
# ---------------------------------------------------------------------------


def _score_band(score: float) -> float:
    if score >= 99.0:
        return 1.00
    if score >= 80.0:
        return 0.80
    if score >= 60.0:
        return 0.55
    if score >= 40.0:
        return 0.30
    if score >= 20.0:
        return 0.15
    return 0.05


def _concentration(families: dict[str, int]) -> tuple[float, str]:
    """Return (top-family-share, top-family-name). Share in [0, 1]."""
    if not families:
        return 0.0, ""
    total = sum(families.values()) or 1
    top_fam, top_count = max(families.items(), key=lambda kv: kv[1])
    return top_count / total, top_fam


def _test_count_inv(total_tests: int) -> float:
    """log-inverse: 300 tests -> ~0.83; 1500 -> ~0.5; 6000 -> ~0.25."""
    if total_tests <= 0:
        return 0.5
    # log10(300) = 2.48, log10(6000) = 3.78
    x = math.log10(max(total_tests, 1))
    # Map [log10(100)=2 .. log10(10000)=4] -> [1 .. 0]
    return max(0.0, min(1.0, (4.0 - x) / 2.0))


def _language_transfer(lang: str) -> float:
    """Bonus if tool's upstream language matches a language where Determinex has
    at least one verified lock today."""
    if not lang:
        return 0.0
    lang_lc = lang.lower()
    return 1.0 if lang_lc in LANGUAGES_WITH_LOCKS else 0.0


def _fixable_family(top_family: str) -> float:
    """The advisor has universal patches for tier-1 + tier-2 families. 'other'
    or unmatched -> 0 (per-tool work)."""
    if not top_family:
        return 0.0
    tier = tier_of(top_family)
    if tier == "tier-1":
        return 1.0
    if tier == "tier-2":
        return 0.6
    return 0.0


# ---------------------------------------------------------------------------
# Per-tool record + ranking
# ---------------------------------------------------------------------------


def _per_tool_records(run_id: str, sqlite_path: Path | None = None) -> list[dict]:
    """Latest eval event per task for the given run_id."""
    if sqlite_path is None:
        sqlite_path = _rl.SQLITE_PATH
    if not sqlite_path.exists():
        rebuild_index(sqlite_path)
    conn = _open_db(sqlite_path)
    try:
        rows = conn.execute(
            """SELECT task_id, score, failures_json, extra_json, timestamp
               FROM events
               WHERE run_id = ? AND phase = 'eval' AND status = 'completed'
               ORDER BY timestamp""",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    by_task: dict[str, dict] = {}
    for task_id, score, failures_json, extra_json, ts in rows:
        if not task_id:
            continue
        extra = json.loads(extra_json) if extra_json else {}
        families = json.loads(failures_json) if failures_json else {}
        by_task[task_id] = {
            "task_id": task_id,
            "score": score if score is not None else 0.0,
            "total": extra.get("total", 0),
            "passed": extra.get("passed", 0),
            "failed": extra.get("failed", 0),
            "families": families,
        }
    return list(by_task.values())


def _lang_for(task_id: str, audit: dict) -> str:
    """Look up upstream language from the residual audit by instance_id."""
    for r in audit.get("residual", []):
        if r.get("instance_id") == task_id:
            return r.get("lang", "")
    return ""


def rank(run_id: str, audit_path: Path = _DEFAULT_AUDIT, top: int = 25) -> dict:
    audit: dict = {}
    if audit_path.is_file():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            audit = {}

    tools = _per_tool_records(run_id)
    ranked: list[dict] = []
    for t in tools:
        score = t["score"]
        families: dict = t["families"]
        total = t["total"]
        lang = _lang_for(t["task_id"], audit)

        sb = _score_band(score)
        conc, top_fam = _concentration(families)
        tci = _test_count_inv(total)
        lt = _language_transfer(lang)
        ff = _fixable_family(top_fam)

        p_lock = round(
            W_SCORE_BAND * sb
            + W_CONCENTRATION * conc
            + W_TEST_COUNT_INV * tci
            + W_LANGUAGE_TRANSFER * lt
            + W_FIXABLE_FAMILY * ff,
            3,
        )

        # Human-readable reason summary
        reasons = []
        if score >= 99.0:
            reasons.append("ALREADY LOCKED")
        elif score >= 80.0:
            reasons.append(f"near-lock at {score}/100")
        elif score >= 40.0:
            reasons.append(f"mid-band {score}/100")
        else:
            reasons.append(f"low score {score}/100")
        if top_fam and conc >= 0.5:
            reasons.append(f"{int(conc * 100)}% concentrated in {top_fam}")
        if ff > 0.5:
            reasons.append(f"top family is patch-fixable ({tier_of(top_fam)})")
        if lt > 0:
            reasons.append(f"{lang} (lang transfer)")
        if total > 0:
            reasons.append(f"{total:,} tests")

        ranked.append(
            {
                "task_id": t["task_id"],
                "score": score,
                "total_tests": total,
                "top_family": top_fam,
                "top_family_share": round(conc, 3),
                "language": lang,
                "p_lock": p_lock,
                "signals": {
                    "score_band": sb,
                    "concentration": round(conc, 3),
                    "test_count_inv": round(tci, 3),
                    "language_transfer": lt,
                    "fixable_family": ff,
                },
                "reasons": reasons,
            }
        )

    ranked.sort(key=lambda r: -r["p_lock"])
    return {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "weights": {
            "score_band": W_SCORE_BAND,
            "concentration": W_CONCENTRATION,
            "test_count_inv": W_TEST_COUNT_INV,
            "language_transfer": W_LANGUAGE_TRANSFER,
            "fixable_family": W_FIXABLE_FAMILY,
        },
        "tools_total": len(ranked),
        "top_n": top,
        "queue": ranked[:top],
        "all": ranked,
    }


def render_md(report: dict) -> str:
    lines = []
    lines.append(f"# Lock queue for {report['run_id']}\n")
    lines.append(f"_generated {report['generated_at']}_\n")
    lines.append(f"- tools ranked: **{report['tools_total']}**")
    lines.append(f"- top N shown: **{report['top_n']}**")
    lines.append("")
    lines.append("Weights: " + "  ".join(f"{k}={v}" for k, v in report["weights"].items()))
    lines.append("")
    lines.append(f"## Top {report['top_n']} lock candidates")
    lines.append("")
    lines.append("| Rank | P(lock) | Score | Tests | Top family | Lang | Reasons |")
    lines.append("|---:|---:|---:|---:|---|---|---|")
    for i, t in enumerate(report["queue"], 1):
        reasons = "; ".join(t["reasons"])
        lines.append(
            f"| {i} | {t['p_lock']:.3f} | {t['score']:.1f} | {t['total_tests']:,} | "
            f"{t['top_family'] or '—'} | {t['language'] or '?'} | {reasons} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    ap = argparse.ArgumentParser(description="ProgramBench tool lock-probability queue")
    ap.add_argument(
        "--run-id",
        default="mass_run_v2_base",
        help="ledger run_id to rank (default: mass_run_v2_base)",
    )
    ap.add_argument(
        "--top",
        type=int,
        default=25,
        help="how many tools to show in the queue (full ranking is in all[])",
    )
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="output directory")
    ap.add_argument(
        "--audit",
        type=Path,
        default=_DEFAULT_AUDIT,
        help="path to corpus/.../_residual_audit.json (drives language lookup)",
    )
    ap.add_argument("--print", action="store_true", help="also print the markdown to stdout")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    report = rank(args.run_id, audit_path=args.audit, top=args.top)
    out_json = args.out / f"{args.run_id}_lock_queue.json"
    out_md = args.out / f"{args.run_id}_lock_queue.md"
    out_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    out_md.write_text(render_md(report), encoding="utf-8")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    if args.print:
        print()
        print(render_md(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
