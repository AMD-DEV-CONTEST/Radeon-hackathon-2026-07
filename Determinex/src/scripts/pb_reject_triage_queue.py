#!/usr/bin/env python3
"""Build a ranked ProgramBench fix queue from gated native rejects.

The drain pool answers "what has been evaluated?" This script answers
"what should be fixed next?" It reads gate_result.json files, clusters the
reject reason, scores closeness to lock, and writes a human/agent-readable
queue. It does not mutate overrides or launch evals.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pb_native_source_guard import check_path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / ".determinex_staging"
OUT_JSON = ROOT / "logs" / "programbench_factory" / "NATIVE_REJECT_FIX_QUEUE.json"
OUT_MD = ROOT / "logs" / "programbench_factory" / "NATIVE_REJECT_FIX_QUEUE.md"
PACKETS_DIR = ROOT / "logs" / "programbench_factory" / "fix_packets"
BOARD = ROOT / "logs" / "programbench_lock_board.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _classify(gate: dict[str, Any]) -> tuple[str, str]:
    delta = gate.get("delta") or {}
    classes = Counter()
    for v in (delta.get("regression_classes") or {}).values():
        classes[v.get("regression_class") or "unknown"] += 1
    reason = gate.get("reason") or ""
    candidate = gate.get("candidate") or {}
    passed = int(candidate.get("passed") or gate.get("candidate_passed") or 0)
    runnable = int(candidate.get("runnable") or gate.get("candidate_runnable") or 0)
    newly = len(delta.get("newly_failing") or [])

    if classes:
        top, count = classes.most_common(1)[0]
        if top == "missing_executable":
            return (
                "infra-path",
                f"{count} path/binary regressions; fix compile.sh/executable layout first",
            )
        if top == "compile_failed":
            return "build-deps", f"{count} compile/build failures; fix toolchain/deps first"
        if newly <= 3 and passed and runnable and runnable - passed <= 10:
            return "near-lock-behavior", f"{newly} regressions; targeted behavior patch likely"
        return (
            "behavioral-regression",
            f"{newly} regressions; cluster by failure messages before rerun",
        )
    if "compile" in reason.lower() or passed == 0:
        return "build-deps", "candidate produced no useful runnable/pass signal"
    if runnable and runnable - passed <= 10:
        return "near-lock-no-regression-class", "close to lock; inspect remaining failures"
    return "broad-gap", "large remaining failure surface"


def _source_file_hint(slug: str, detected: str | None) -> str:
    d = ROOT / "corpus" / "programbench" / "per_tool_overrides" / slug
    if detected == "rust":
        return str((d / "src" / "main.rs").relative_to(ROOT))
    if detected == "go":
        return str((d / "main.go").relative_to(ROOT))
    if detected == "c":
        return str((d / "main.c").relative_to(ROOT))
    if detected == "cpp":
        return str((d / "main.cpp").relative_to(ROOT))
    return str(d.relative_to(ROOT))


def build_queue() -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    board_rows = {}
    if BOARD.is_file():
        for r in load_json(BOARD):
            if r.get("base_slug"):
                board_rows[r["base_slug"]] = r
    for gate_path in STAGING.rglob("gate_result.json"):
        try:
            gate = load_json(gate_path)
        except Exception:
            continue
        if gate.get("decision") != "reject":
            continue
        slug = gate.get("slug") or gate_path.parent.name
        base_slug = slug.split(".", 1)[0]
        board_row = board_rows.get(base_slug, {})
        if float(board_row.get("best_score") or 0) >= 100.0:
            continue
        run_root = Path(gate.get("candidate_run_root") or gate_path.parent)
        candidate = gate.get("candidate") or {}
        baseline = gate.get("baseline") or {}
        delta = gate.get("delta") or {}
        passed = int(candidate.get("passed") or gate.get("candidate_passed") or 0)
        runnable = int(candidate.get("runnable") or gate.get("candidate_runnable") or 0)
        baseline_passed = int(baseline.get("passed") or gate.get("baseline_passed") or 0)
        passed_gain = passed - baseline_passed
        remaining = max(runnable - passed, 0)
        newly_failing = len(delta.get("newly_failing") or [])
        fix_class, sketch = _classify(gate)
        guard = check_path(
            ROOT / "corpus" / "programbench" / "per_tool_overrides" / slug, slug=slug
        )

        # Higher is better: near locks, positive raw gain, low regression count,
        # and native-source-ready candidates rise to the top.
        priority = 0
        if guard.get("ok"):
            priority += 500
        if remaining <= 10 and runnable:
            priority += 400
        elif remaining <= 50 and runnable:
            priority += 250
        priority += min(max(passed_gain, 0), 300)
        priority -= newly_failing * 15
        if fix_class in {"infra-path", "near-lock-behavior"}:
            priority += 150
        if fix_class == "build-deps":
            priority += 50

        row = {
            "slug": slug,
            "run_root": str(run_root),
            "gate_result": str(gate_path),
            "passed": passed,
            "runnable": runnable,
            "baseline_passed": baseline_passed,
            "passed_gain": passed_gain,
            "remaining_to_lock": remaining,
            "newly_failing": newly_failing,
            "fix_class": fix_class,
            "fix_sketch": sketch,
            "native_source_ok": bool(guard.get("ok")),
            "native_source_reason": guard.get("reason"),
            "detected_language": guard.get("detected_language"),
            "source_hint": _source_file_hint(slug, guard.get("detected_language")),
            "priority": priority,
        }
        old = rows.get(slug)
        if old is None or (row["priority"], row["passed"], -row["newly_failing"]) > (
            old["priority"],
            old["passed"],
            -old["newly_failing"],
        ):
            rows[slug] = row
    out = list(rows.values())
    out.sort(key=lambda r: (-r["priority"], r["remaining_to_lock"], -r["passed_gain"], r["slug"]))
    return out


def write_outputs(rows: list[dict[str, Any]]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# ProgramBench Native Reject Fix Queue",
        "",
        "Ranked queue of gated rejects that should become targeted fix/repack/rerun work. This is generated from `gate_result.json` files and native-source guard state.",
        "",
        f"Total rejected tools queued for fixes: {len(rows)}",
        "",
        "| rank | slug | class | pass | gain | left | regressions | native | fix sketch | source |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['slug']} | {r['fix_class']} | {r['passed']}/{r['runnable']} | "
            f"{r['passed_gain']:+d} | {r['remaining_to_lock']} | {r['newly_failing']} | "
            f"{'yes' if r['native_source_ok'] else 'no'} | {r['fix_sketch']} | `{r['source_hint']}` |"
        )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_gate(row: dict[str, Any]) -> dict[str, Any]:
    return load_json(Path(row["gate_result"]))


def write_fix_packets(rows: list[dict[str, Any]], *, limit: int) -> None:
    PACKETS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in PACKETS_DIR.glob("*.md"):
        stale.unlink()
    for i, r in enumerate(rows[:limit], 1):
        gate = _load_gate(r)
        delta = gate.get("delta") or {}
        candidate = gate.get("candidate") or {}
        fail_messages = candidate.get("fail_messages") or {}
        newly = delta.get("newly_failing") or []
        examples = newly[:12]
        path = PACKETS_DIR / f"{i:02d}_{r['slug'].replace('__', '_').replace('.', '_')}.md"
        lines = [
            f"# Fix Packet: {r['slug']}",
            "",
            f"Rank: {i}",
            f"Class: {r['fix_class']}",
            f"Score: {r['passed']}/{r['runnable']} (gain {r['passed_gain']:+d}, left {r['remaining_to_lock']})",
            f"Regressions: {r['newly_failing']}",
            f"Native source: {'yes' if r['native_source_ok'] else 'no'} ({r['native_source_reason']})",
            f"Source hint: `{r['source_hint']}`",
            f"Run root: `{r['run_root']}`",
            f"Gate: `{r['gate_result']}`",
            "",
            "## Fix Sketch",
            "",
            r["fix_sketch"],
            "",
            "## Newly Failing Tests",
            "",
        ]
        if examples:
            for name in examples:
                msg = fail_messages.get(name) or (
                    delta.get("regression_classes", {}).get(name, {}) or {}
                ).get("regression_hint", "")
                msg = str(msg).replace("\r", "\\r")
                if len(msg) > 1200:
                    msg = msg[:1200] + "..."
                lines.extend([f"### {name}", "", "```", msg, "```", ""])
        else:
            lines.append("No newly_failing list in gate. Inspect candidate remaining failures.")
            lines.append("")
        lines.extend(
            [
                "## Required Workflow",
                "",
                "1. Patch native source only. Do not add Python logic unless the upstream tool is Python.",
                "2. Repack with `scripts/pb_pack_candidate.py <slug> --run-root .determinex_staging/pb_<tool>_native_vNEXT`.",
                "3. Evaluate with `scripts/pb_launch_eval_lane.ps1` or the Hetzner shard pool.",
                "4. Gate with `scripts/pb_candidate_gate.py` against the board baseline.",
                "5. Apply accepts; ingest rejects; rerun this triage queue.",
                "",
            ]
        )
        path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument(
        "--packets", type=int, default=20, help="number of per-tool fix packets to write"
    )
    args = ap.parse_args()
    rows = build_queue()
    write_outputs(rows)
    write_fix_packets(rows, limit=args.packets)
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(f"wrote {PACKETS_DIR}")
    for i, r in enumerate(rows[: args.top], 1):
        print(
            f"{i:02d} {r['priority']:4d} {r['slug']} {r['fix_class']} "
            f"{r['passed']}/{r['runnable']} gain={r['passed_gain']:+d} "
            f"left={r['remaining_to_lock']} regressions={r['newly_failing']} "
            f"native={r['native_source_ok']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
