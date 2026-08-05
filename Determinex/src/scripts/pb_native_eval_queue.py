#!/usr/bin/env python3
"""Build/optionally launch the native ProgramBench eval queue.

This script is intentionally mechanical:

- discovers packed `.determinex_staging/pb_*_native_v*` run roots
- infers the single `<slug>/submission.tar.gz` inside each run root
- marks status as queued / evaluated / gated
- joins current board score and language-audit action
- writes a JSON queue and prints the next highest-priority work

It does not gate or apply results. Launch mode only starts official ProgramBench
eval lanes using the existing PowerShell launcher.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from determinex_atomic_io import write_json_atomic as _write_json_atomic
from pb_native_source_guard import check_path

ROOT = Path(__file__).resolve().parents[1]
PB_STAGING_ROOT = Path(os.environ.get("DETERMINEX_PB_STAGING_ROOT", "T:/determinex-staging"))
STAGING_ROOTS = [PB_STAGING_ROOT, ROOT / ".determinex_staging"]
BOARD = ROOT / "logs" / "programbench_lock_board.json"
AUDIT = ROOT / "logs" / "programbench_factory" / "LANGUAGE_AUDIT.json"
OUT_JSON = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_QUEUE.json"
RESERVATIONS = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_RESERVATIONS.json"
LAUNCHER = ROOT / "scripts" / "pb_launch_eval_lane.ps1"


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _short_name(slug: str) -> str:
    return slug.replace("__", "_").split(".")[0].replace("-", "")


def _status(run_root: Path, slug: str) -> tuple[str, str | None]:
    gate = run_root / "gate_result.json"
    if gate.is_file():
        try:
            g = _load_json(gate, {})
            return f"gated:{g.get('decision', 'unknown')}", str(gate)
        except Exception:
            return "gated:unreadable", str(gate)
    eval_path = run_root / slug / f"{slug}.eval.json"
    if eval_path.is_file():
        return "evaluated", str(eval_path)
    return "queued", None


def discover() -> list[dict[str, Any]]:
    board = {r.get("slug") or r.get("base_slug"): r for r in _load_json(BOARD, [])}
    by_base = {r.get("base_slug"): r for r in _load_json(BOARD, [])}
    audit = {r.get("slug"): r for r in _load_json(AUDIT, [])}
    reservations = _load_json(RESERVATIONS, {})
    rows_by_slug: dict[str, dict[str, Any]] = {}

    status_rank = {
        "queued": 0,
        "evaluated": 1,
        "gated:accept": 2,
        "gated:reject": 3,
        "locked": 4,
    }

    seen_roots: set[str] = set()
    for staging in STAGING_ROOTS:
        if not staging.is_dir():
            continue
        for run_root in sorted(staging.glob("pb_*_native_v*")):
            key = str(run_root.resolve())
            if key in seen_roots:
                continue
            seen_roots.add(key)
            if not run_root.is_dir():
                continue
            candidates = [
                d for d in run_root.iterdir() if d.is_dir() and (d / "submission.tar.gz").is_file()
            ]
            if len(candidates) != 1:
                continue
            slug = candidates[0].name
            if ";" in slug:
                # Stale malformed staging roots can survive after board cleanup
                # (for example `kyoh86__richgo.313114f;c`). They must not reenter
                # the drain pool once the canonical 200-row board is clean.
                continue
            base_slug = slug.split(".", 1)[0]
            board_row = board.get(slug) or by_base.get(base_slug) or {}
            audit_row = audit.get(slug) or {}
            st, artifact = _status(run_root, slug)
            best_passed = int(board_row.get("best_passed") or audit_row.get("passed") or 0)
            best_runnable = int(
                board_row.get("best_runnable_total") or audit_row.get("runnable") or 0
            )
            if best_runnable > 0 and best_passed == best_runnable:
                st = "locked"
                artifact = board_row.get("best_eval_path") or artifact
            reservation = reservations.get(slug) or reservations.get(base_slug)
            if st == "queued" and reservation:
                st = f"reserved:{reservation}"
            guard = check_path(candidates[0], slug=slug, strict=True)
            if st == "queued" and not guard.get("ok"):
                st = "blocked:native-source"
            row = {
                "slug": slug,
                "base_slug": base_slug,
                "run_root": str(run_root),
                "status": st,
                "artifact": artifact,
                "score": float(board_row.get("best_score") or audit_row.get("score") or 0),
                "passed": best_passed,
                "runnable": best_runnable,
                "next_action": board_row.get("next_action") or "",
                "audit_action": audit_row.get("action") or "",
                "source_language": audit_row.get("source_language") or "",
                "native_source_ok": bool(guard.get("ok")),
                "native_source_reason": guard.get("reason") or "",
                "detected_language": guard.get("detected_language"),
                "main_py_lines": guard.get("main_py_lines", 0),
            }
            row_key = base_slug
            old = rows_by_slug.get(row_key)
            if old is None:
                rows_by_slug[row_key] = row
            else:
                old_rank = status_rank.get(old["status"], 9)
                new_rank = status_rank.get(row["status"], 9)
                old_mtime = Path(old["run_root"]).stat().st_mtime
                new_mtime = run_root.stat().st_mtime
                # Prefer the newest packed candidate for a slug. Older queued
                # roots should not resurrect after a newer eval/gate/lock exists.
                if (new_mtime, -new_rank) > (old_mtime, -old_rank):
                    rows_by_slug[row_key] = row
    rows = list(rows_by_slug.values())
    rows.sort(
        key=lambda r: (
            0 if r["status"] == "queued" else 1,
            -r["score"],
            -r["runnable"],
            r["slug"],
        )
    )
    return rows


def launch(rows: list[dict[str, Any]], count: int, dry_run: bool) -> int:
    launched = 0
    reservations = _load_json(RESERVATIONS, {})
    for r in rows:
        if launched >= count:
            break
        if r["status"] != "queued":
            continue
        run_root = (
            ROOT / r["run_root"] if not Path(r["run_root"]).is_absolute() else Path(r["run_root"])
        )
        if not r.get("native_source_ok"):
            print(f"SKIP {r['slug']}: {r.get('native_source_reason')}")
            continue
        name = f"{_short_name(r['slug'])}_native_v1"
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LAUNCHER),
            "-Slug",
            r["slug"],
            "-RunRoot",
            str(run_root.resolve()),
            "-Name",
            name,
        ]
        print("LAUNCH", r["score"], r["slug"], r["run_root"])
        if not dry_run:
            subprocess.run(cmd, cwd=str(ROOT), check=True)
            reservations[r["slug"]] = f"local:{name}"
            reservations[r["base_slug"]] = f"local:{name}"
            _write_json_atomic(RESERVATIONS, reservations)
        launched += 1
    return launched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=25, help="rows to print")
    ap.add_argument("--launch", type=int, default=0, help="launch next N queued evals")
    ap.add_argument("--dry-run", action="store_true", help="with --launch, print only")
    args = ap.parse_args()

    rows = discover()
    _write_json_atomic(OUT_JSON, rows)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"wrote {OUT_JSON}")
    print("status:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print()
    print("next queued:")
    printed = 0
    for r in rows:
        if r["status"] != "queued":
            continue
        print(
            f"{r['score']:6.2f} {r['passed']}/{r['runnable']} "
            f"{r['source_language'] or '?':7s} {r['slug']} {r['run_root']}"
        )
        printed += 1
        if printed >= args.top:
            break

    if args.launch:
        print()
        n = launch(rows, args.launch, args.dry_run)
        print(f"launched={0 if args.dry_run else n} planned={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
