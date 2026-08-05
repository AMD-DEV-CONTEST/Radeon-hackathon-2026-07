"""Rank Lock-Factory v2 candidates from sprint ledger events.

The normal ProgramBench lock queue ranks broad first-pass targets from eval
JSONs. After a per-tool sprint, the better question is narrower: which v1
scaffolds proved movable enough to justify a v2 refinement loop?

This script reads logs/ledger/lockfactory_*_v1.jsonl and emits a compact
v2 queue based on current score, v1 lift, remaining headroom, and known
structural blockers.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "logs" / "ledger"
DEFAULT_OUT = ROOT / "logs" / "mass_run_v2"


STRUCTURAL_BLOCKERS = {
    "hyperfine": "quarantined: Docker/resource-sensitive timing suite",
    "genact": "structural: deterministic animation output required",
    "cheat": "partial blocker: real EDITOR subprocess behavior required",
    "svd2rust": "partial blocker: byte-level Rust codegen/harvest output required",
}


@dataclass
class Candidate:
    tool: str
    instance_id: str
    base_score: float
    v1_score: float
    delta: float
    passed: int | None
    total: int | None
    output_root: str
    remaining_top_families: dict[str, int]
    blocker: str


def _tool_name(run_id: str, extra: dict[str, Any]) -> str:
    if extra.get("tool"):
        return str(extra["tool"])
    stem = run_id.removeprefix("lockfactory_").removesuffix("_v1")
    return stem


def _read_latest_event(path: Path) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            latest = json.loads(raw)
        except json.JSONDecodeError:
            continue
    return latest


def load_candidates(ledger_dir: Path = DEFAULT_LEDGER) -> list[Candidate]:
    candidates: list[Candidate] = []
    for path in sorted(ledger_dir.glob("lockfactory_*_v1.jsonl")):
        event = _read_latest_event(path)
        if not event:
            continue
        extra = event.get("extra") or {}
        run_id = str(event.get("run_id", path.stem))
        tool = _tool_name(run_id, extra)
        base = float(extra.get("base_score", 0.0) or 0.0)
        v1 = float(extra.get("v1_score", event.get("score", 0.0)) or 0.0)
        delta = float(extra.get("delta_vs_base", v1 - base) or 0.0)
        candidates.append(
            Candidate(
                tool=tool,
                instance_id=str(extra.get("instance_id", "")),
                base_score=base,
                v1_score=v1,
                delta=delta,
                passed=extra.get("passed"),
                total=extra.get("total"),
                output_root=str(extra.get("output_root", "")),
                remaining_top_families=dict(extra.get("remaining_top_families") or {}),
                blocker=STRUCTURAL_BLOCKERS.get(tool, ""),
            )
        )
    return candidates


def _norm(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _family_focus(families: dict[str, int]) -> tuple[float, str]:
    if not families:
        return 0.45, ""
    total = sum(families.values()) or 1
    name, count = max(families.items(), key=lambda item: item[1])
    return count / total, name


def score_candidate(c: Candidate) -> tuple[float, dict[str, float], list[str]]:
    """Return p_v2, component signals, and reasons."""
    headroom = max(0.0, 100.0 - c.v1_score)
    lift_signal = _norm(c.delta, 0.0, 40.0)
    score_signal = _norm(c.v1_score, 20.0, 80.0)
    headroom_signal = _norm(headroom, 20.0, 80.0)
    focus_signal, top_family = _family_focus(c.remaining_top_families)
    blocker_penalty = 0.0
    if c.tool in {"hyperfine", "genact"}:
        blocker_penalty = 0.75
    elif c.tool in {"cheat", "svd2rust"}:
        blocker_penalty = 0.35

    p_v2 = (
        0.35 * lift_signal
        + 0.25 * score_signal
        + 0.20 * headroom_signal
        + 0.15 * focus_signal
        + 0.05 * (1.0 if c.delta >= 10.0 else 0.0)
        - blocker_penalty
    )
    p_v2 = round(max(0.0, min(1.0, p_v2)), 3)

    reasons: list[str] = []
    if c.delta >= 25:
        reasons.append(f"large v1 lift +{c.delta:.2f}pp")
    elif c.delta >= 10:
        reasons.append(f"solid v1 lift +{c.delta:.2f}pp")
    elif c.delta > 0:
        reasons.append(f"small v1 lift +{c.delta:.2f}pp")
    else:
        reasons.append("no v1 lift")
    reasons.append(f"{headroom:.1f}pp headroom")
    if top_family:
        reasons.append(f"top remaining family {top_family} ({int(focus_signal * 100)}%)")
    if c.blocker:
        reasons.append(c.blocker)

    return (
        p_v2,
        {
            "lift_signal": round(lift_signal, 3),
            "score_signal": round(score_signal, 3),
            "headroom_signal": round(headroom_signal, 3),
            "family_focus": round(focus_signal, 3),
            "blocker_penalty": round(blocker_penalty, 3),
        },
        reasons,
    )


def build_report(candidates: list[Candidate], top: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for c in candidates:
        p_v2, signals, reasons = score_candidate(c)
        rows.append(
            {
                "tool": c.tool,
                "instance_id": c.instance_id,
                "base_score": c.base_score,
                "v1_score": c.v1_score,
                "delta_vs_base": c.delta,
                "p_v2": p_v2,
                "signals": signals,
                "remaining_top_families": c.remaining_top_families,
                "blocker": c.blocker,
                "output_root": c.output_root,
                "reasons": reasons,
            }
        )
    rows.sort(key=lambda row: (-row["p_v2"], -row["delta_vs_base"], -row["v1_score"]))
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "candidates_total": len(rows),
        "top_n": top,
        "queue": rows[:top],
        "all": rows,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Lock-Factory v2 Queue",
        "",
        f"_generated {report['generated_at']}_",
        "",
        "| Rank | P(v2) | Tool | Base | v1 | Delta | Reasons |",
        "|---:|---:|---|---:|---:|---:|---|",
    ]
    for i, row in enumerate(report["queue"], 1):
        reasons = "; ".join(row["reasons"])
        lines.append(
            f"| {i} | {row['p_v2']:.3f} | {row['tool']} | "
            f"{row['base_score']:.2f} | {row['v1_score']:.2f} | "
            f"+{row['delta_vs_base']:.2f} | {reasons} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Rank Lock-Factory v2 candidates")
    ap.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--print", action="store_true")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    report = build_report(load_candidates(args.ledger_dir), top=args.top)
    json_path = args.out / "lockfactory_v2_queue.json"
    md_path = args.out / "lockfactory_v2_queue.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_md(report)
    md_path.write_text(md, encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    if args.print:
        print()
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
