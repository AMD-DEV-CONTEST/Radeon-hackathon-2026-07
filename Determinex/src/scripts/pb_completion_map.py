#!/usr/bin/env python3
"""Build the ProgramBench 200-tool completion map.

Reads the live lock board plus the language audit and writes a Markdown/JSON
routing table that workers can follow without guessing language or priority.
The audit is the source of truth for whether an override is already native,
needs native rewrite, is a legitimate Python tool, or is missing coverage.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
AUDIT_JSON = ROOT / "logs" / "programbench_factory" / "LANGUAGE_AUDIT.json"
OUT_MD = ROOT / "docs" / "PROGRAMBENCH_200_COMPLETION_MAP.md"
OUT_JSON = ROOT / "logs" / "programbench_factory" / "PROGRAMBENCH_200_COMPLETION_MAP.json"


def _score_band(score: float) -> str:
    if score >= 100:
        return "100"
    if score >= 90:
        return "90-99"
    if score >= 70:
        return "70-89"
    if score >= 50:
        return "50-69"
    if score >= 25:
        return "25-49"
    if score > 0:
        return "0-24"
    return "0"


def _effective_route(
    row: dict[str, Any], audit: dict[str, Any] | None
) -> tuple[str, str, str, str]:
    score = float(row.get("best_score") or 0)
    if score >= 100 or row.get("locked_dir"):
        return "locked", "locked", "done", "archive/verify only"
    if audit is None:
        return (
            "missing-override",
            "unknown",
            "create override",
            "create/restore override, then rerun language audit",
        )

    action = audit.get("action") or "unknown"
    source = audit.get("source_language") or "unknown"
    if action == "keep-python":
        return "source:python", action, source, "finish exact behavior in Python source"
    if action == "keep-thin":
        return (
            f"thin:{source}",
            action,
            source,
            "verify wrapper stays transparent over bundled binary",
        )
    if action == "already-native":
        return f"native:{source}", action, source, "push remaining failures in native source"
    if action in {"rewrite-native", "scaffold-stub"}:
        lang = source if source != "unknown" else "native-source"
        return f"native:{lang}", action, source, "replace Python/stub logic with real native source"
    if action == "investigate":
        return "investigate", action, source, "locate upstream/build system before writing code"
    return "unknown", action, source, "triage audit entry"


def _priority(row: dict[str, Any], audit: dict[str, Any] | None) -> tuple[int, float, int]:
    score = float(row.get("best_score") or 0)
    if score >= 100 or row.get("locked_dir"):
        bucket = 9
    elif audit is None:
        bucket = 8
    else:
        action = audit.get("action") or "unknown"
        if action == "already-native" and score >= 70:
            bucket = 0
        elif action in {"rewrite-native", "scaffold-stub"} and score >= 70:
            bucket = 1
        elif action == "keep-thin":
            bucket = 2
        elif action in {"rewrite-native", "scaffold-stub"}:
            bucket = 3
        elif action == "already-native":
            bucket = 4
        elif action == "investigate":
            bucket = 5
        elif action == "keep-python":
            bucket = 6
        else:
            bucket = 7
    return (bucket, -score, -(int(row.get("best_runnable_total") or 0)))


def _status_note(row: dict[str, Any], audit: dict[str, Any] | None, route: str) -> str:
    if audit is None:
        return "board row has no override directory audited"
    note = audit.get("reason") or ""
    if audit.get("action") in {"already-native", "rewrite-native", "scaffold-stub"}:
        native = audit.get("native_files") or []
        if native:
            note = f"native files: {', '.join(native[:3])}" + ("..." if len(native) > 3 else "")
    if route == "locked":
        note = row.get("next_action") or note
    return str(note)


def build_rows(
    board: list[dict[str, Any]], audit_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    audit_index = {c.get("base_slug"): c for c in audit_rows}
    rows: list[dict[str, Any]] = []
    for row in board:
        audit = audit_index.get(row.get("base_slug"))
        route, action, source, recommended = _effective_route(row, audit)
        score = float(row.get("best_score") or 0)
        rows.append(
            {
                "rank_key": _priority(row, audit),
                "base_slug": row.get("base_slug"),
                "slug": row.get("slug") or row.get("base_slug"),
                "score": score,
                "passed": int(row.get("best_passed") or 0),
                "runnable": int(row.get("best_runnable_total") or 0),
                "band": _score_band(score),
                "audit_action": action,
                "source_language": source,
                "route": route,
                "next_action": row.get("next_action") or "",
                "locked": bool(row.get("locked_dir") or score >= 100),
                "best_eval_path": row.get("best_eval_path") or "",
                "reason": _status_note(row, audit, route),
                "recommended_action": recommended,
                "override_audited": audit is not None,
            }
        )
    rows.sort(key=lambda r: r["rank_key"])
    for idx, row in enumerate(rows, 1):
        row["priority"] = idx
        row.pop("rank_key", None)
    return rows


def write_markdown(rows: list[dict[str, Any]], out: Path) -> None:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    band_counts = Counter(r["band"] for r in rows)
    route_counts = Counter(r["route"] for r in rows)
    action_counts = Counter(r["audit_action"] for r in rows)
    locked = sum(1 for r in rows if r["locked"])
    missing_override = sum(1 for r in rows if not r["override_audited"])
    total_passed = sum(r["passed"] for r in rows)
    total_runnable = sum(r["runnable"] for r in rows)

    lines: list[str] = []
    lines.append("# ProgramBench 200-Tool Completion Map\n\n")
    lines.append(f"Generated: `{now}`\n\n")
    lines.append("This is the live routing map for driving every ProgramBench tool to Rule A ")
    lines.append("without leaving Python logic in native-language tools. Routes are based on ")
    lines.append("the current lock board plus `LANGUAGE_AUDIT.json`.\n\n")

    lines.append("## Summary\n\n")
    lines.append(f"- Tools: `{len(rows)}`\n")
    lines.append(f"- Locked/100 band: `{locked}`\n")
    lines.append(f"- Missing override directories: `{missing_override}`\n")
    lines.append(f"- Aggregate runnable: `{total_passed}/{total_runnable}`\n")
    lines.append(
        "- Bands: "
        + ", ".join(
            f"`{k}={band_counts.get(k, 0)}`"
            for k in ("100", "90-99", "70-89", "50-69", "25-49", "0-24", "0")
        )
        + "\n"
    )
    lines.append(
        "- Audit actions: " + ", ".join(f"`{k}={v}`" for k, v in action_counts.most_common()) + "\n"
    )
    lines.append(
        "- Routes: " + ", ".join(f"`{k}={v}`" for k, v in route_counts.most_common()) + "\n\n"
    )

    lines.append("## Immediate Queue\n\n")
    lines.append(
        "| priority | score | passed/runnable | audit | source | route | slug | action |\n"
    )
    lines.append("|---:|---:|---:|---|---|---|---|---|\n")
    for r in rows:
        if r["locked"]:
            continue
        if r["score"] < 70:
            continue
        lines.append(
            f"| {r['priority']} | {r['score']:.1f} | {r['passed']}/{r['runnable']} | "
            f"{r['audit_action']} | {r['source_language']} | {r['route']} | `{r['base_slug']}` | {r['recommended_action']} |\n"
        )
    lines.append("\n")

    lines.append("## Full 200-Tool Map\n\n")
    lines.append(
        "| priority | band | score | passed/runnable | audit | source | route | slug | reason |\n"
    )
    lines.append("|---:|---|---:|---:|---|---|---|---|---|\n")
    for r in rows:
        reason = str(r["reason"]).replace("|", "/")
        if len(reason) > 96:
            reason = reason[:93] + "..."
        lines.append(
            f"| {r['priority']} | {r['band']} | {r['score']:.1f} | {r['passed']}/{r['runnable']} | "
            f"{r['audit_action']} | {r['source_language']} | {r['route']} | `{r['base_slug']}` | {reason} |\n"
        )
    out.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", type=Path, default=BOARD_JSON)
    ap.add_argument("--audit", type=Path, default=AUDIT_JSON)
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = ap.parse_args()

    board = json.loads(args.board.read_text(encoding="utf-8"))
    audit_rows = json.loads(args.audit.read_text(encoding="utf-8"))
    rows = build_rows(board, audit_rows)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(rows, args.out_md)
    args.out_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out_md}")
    print(f"wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
