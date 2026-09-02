#!/usr/bin/env python3
"""Classify and optionally intake ProgramBench tools not in the native eval pool."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from determinex_atomic_io import write_json_atomic, write_text_atomic  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "logs" / "programbench_lock_board.json"
QUEUE = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_QUEUE.json"
AUDIT = ROOT / "logs" / "programbench_factory" / "LANGUAGE_AUDIT.json"
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
UPSTREAM = Path("T:/determinex-programbench/_extracted_tests")
OUT_JSON = ROOT / "logs" / "programbench_factory" / "MISSING_INTAKE.json"
OUT_MD = ROOT / "logs" / "programbench_factory" / "MISSING_INTAKE.md"
PY = Path(sys.executable)


def load(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def run(cmd: list[Any], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(str(x) for x in cmd))
    return subprocess.run([str(x) for x in cmd], cwd=str(ROOT), text=True, check=check)


def has_upstream(slug: str) -> bool:
    base = UPSTREAM / slug
    if base.is_dir():
        return True
    # Some historical directories may be by base slug only.
    return bool(list(UPSTREAM.glob(slug.split(".", 1)[0] + ".*")))


def override_slug_for(base_slug: str) -> str | None:
    matches = sorted(OVERRIDES.glob(base_slug + ".*"))
    return matches[0].name if matches else None


def classify(
    board_row: dict[str, Any], queue_bases: set[str], audit_by_base: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    base = board_row["base_slug"]
    slug = board_row.get("slug") or override_slug_for(base) or base
    audit = audit_by_base.get(base, {})
    action = audit.get("action") or ""
    lang = audit.get("source_language") or ""
    upstream = has_upstream(slug)
    override_slug = override_slug_for(base)
    if float(board_row.get("best_score") or 0) >= 100:
        bucket = "locked"
    elif base in queue_bases:
        bucket = "already-pooled"
    elif action in ("keep-python", "keep-thin") and override_slug:
        bucket = "pack-existing"
    elif upstream and override_slug:
        bucket = "convert-native"
    elif upstream:
        bucket = "source-exists-no-override"
    else:
        bucket = "manual-source-recovery"
    return {
        "base_slug": base,
        "slug": slug,
        "override_slug": override_slug,
        "score": float(board_row.get("best_score") or 0),
        "passed": int(board_row.get("best_passed") or 0),
        "total": int(board_row.get("best_runnable_total") or 0),
        "audit_action": action,
        "source_language": lang,
        "has_upstream_extracted": upstream,
        "bucket": bucket,
    }


def build_rows() -> list[dict[str, Any]]:
    board = load(BOARD, [])
    queue = load(QUEUE, [])
    audit = load(AUDIT, [])
    queue_bases = {r["base_slug"] for r in queue}
    audit_by_base = {r["base_slug"]: r for r in audit if r.get("base_slug")}
    rows = [classify(r, queue_bases, audit_by_base) for r in board]
    return sorted(rows, key=lambda r: (r["bucket"], -r["score"], r["base_slug"]))


def write_reports(rows: list[dict[str, Any]]) -> None:
    write_json_atomic(OUT_JSON, rows)
    lines = ["# ProgramBench Missing/Special Intake", ""]
    buckets = sorted({r["bucket"] for r in rows})
    for b in buckets:
        group = [r for r in rows if r["bucket"] == b]
        lines.append(f"## {b} ({len(group)})")
        lines.append("")
        lines.append("| score | passed/total | lang | action | upstream | tool |")
        lines.append("|---:|---:|---|---|---|---|")
        for r in group:
            lines.append(
                f"| {r['score']:.2f} | {r['passed']}/{r['total']} | "
                f"{r['source_language'] or '?'} | {r['audit_action'] or '?'} | "
                f"{'yes' if r['has_upstream_extracted'] else 'no'} | {r['base_slug']} |"
            )
        lines.append("")
    write_text_atomic(OUT_MD, "\n".join(lines) + "\n")


def pack_existing(rows: list[dict[str, Any]], limit: int) -> None:
    count = 0
    for r in rows:
        if r["bucket"] != "pack-existing" or not r["override_slug"]:
            continue
        run_root = (
            ROOT / ".determinex_staging" / f"pb_{r['base_slug'].replace('__', '_')}_native_v1"
        )
        run(
            [
                PY,
                ROOT / "scripts" / "pb_pack_candidate.py",
                r["override_slug"],
                "--run-root",
                run_root,
            ],
            check=False,
        )
        count += 1
        if count >= limit:
            break


def convert_native(rows: list[dict[str, Any]], limit: int) -> None:
    count = 0
    for r in rows:
        if r["bucket"] not in ("convert-native", "source-exists-no-override"):
            continue
        slug = r["override_slug"] or r["slug"]
        cmd = [PY, ROOT / "scripts" / "pb_convert_to_native.py", slug]
        if not r["override_slug"]:
            cmd.append("--create-missing")
        run(cmd, check=False)
        run_root = (
            ROOT / ".determinex_staging" / f"pb_{r['base_slug'].replace('__', '_')}_native_v1"
        )
        run(
            [PY, ROOT / "scripts" / "pb_pack_candidate.py", slug, "--run-root", run_root],
            check=False,
        )
        count += 1
        if count >= limit:
            break


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pack-existing", type=int, default=0)
    ap.add_argument("--convert-native", type=int, default=0)
    args = ap.parse_args()

    run([PY, ROOT / "scripts" / "pb_native_eval_queue.py", "--top", "1"], check=False)
    rows = build_rows()
    write_reports(rows)
    print(OUT_MD)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["bucket"]] = counts.get(r["bucket"], 0) + 1
    print(json.dumps(counts, indent=2, sort_keys=True))
    if args.pack_existing:
        pack_existing(rows, args.pack_existing)
    if args.convert_native:
        convert_native(rows, args.convert_native)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
