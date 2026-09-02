#!/usr/bin/env python3
"""ProgramBench factory dispatcher.

Reads `logs/programbench_lock_board.json`, ranks unlocked tools by where the
next worker packet is most likely to produce a real win, and (unless
`--dry-run`) generates a packet for the top candidate(s) via
`scripts/pb_make_packet.py`.

Priority order:
  1. push-to-lock         (best_score >= 70 and not locked)
  2. hand-test-iterate    (has eval + has override)
  3. create-override      (has extracted tests, no override)

Locked tools are filtered out. `create-override` rows are filtered out
unless `--include-recovery` is passed (worker packets for those need a
recovery step before patching, which is a different workflow).

Outputs:
  logs/programbench_factory/DISPATCH_QUEUE.json
  - {"generated_at": ts, "queue": [{slug, next_action, best_passed, ...}, ...]}
  console summary (table)

Does not commit, does not run eval, does not pack candidates.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
FACTORY_DIR = ROOT / "logs" / "programbench_factory"
INVENTORY_DIR = ROOT / "logs" / "programbench_failure_inventory"
QUEUE_JSON = FACTORY_DIR / "DISPATCH_QUEUE.json"

# Priority rank: lower = higher priority
PRIORITY = {
    "push-to-lock": 1,
    "lock-now": 0,  # Should normally go straight to archive, not a worker; rank highest if encountered
    "hand-test-iterate": 2,
    "create-override": 3,
    "verify/archive-lock": 4,
    "recover-tests-or-task": 5,
}


def _load_board(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        sys.stderr.write(f"board JSON missing: {path}\n")
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        sys.stderr.write(f"failed to parse {path}: {e}\n")
        return []


def _row_score(row: dict[str, Any]) -> tuple[int, float, str]:
    """Return a sort key. Lower tuple = higher priority.

    Tiebreakers:
      - within same next_action, higher best_score first
      - then alphabetical slug for stable output
    """
    action = str(row.get("next_action") or "unknown")
    p = PRIORITY.get(action, 99)
    bs = row.get("best_score")
    if not isinstance(bs, (int, float)):
        bs = 0.0
    # negate score so higher is "smaller" in the sort
    return (p, -float(bs), str(row.get("slug") or row.get("base_slug") or ""))


def _is_locked(row: dict[str, Any]) -> bool:
    return bool(row.get("locked_dir"))


def filter_and_rank(
    board: list[dict[str, Any]],
    include_recovery: bool,
) -> list[dict[str, Any]]:
    """Apply filters and produce a ranked list."""
    candidates = [r for r in board if not _is_locked(r)]
    if not include_recovery:
        candidates = [r for r in candidates if r.get("next_action") != "create-override"]
    # Also filter out rows with no usable identifier
    candidates = [r for r in candidates if r.get("slug") or r.get("base_slug")]
    candidates.sort(key=_row_score)
    return candidates


def find_row_by_slug(board: list[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    for r in board:
        if r.get("slug") == slug:
            return r
    base = slug.split(".", 1)[0]
    matches = [r for r in board if r.get("base_slug") == base]
    if len(matches) == 1:
        return matches[0]
    return None


def _load_language_classification() -> dict[str, dict[str, Any]]:
    """Load LANGUAGE_CLASSIFICATION.json into a base_slug -> entry dict.

    The classifier ranks each tool as native-required / python-sufficient /
    unknown by scanning failing-test signals (integer overflow, signal
    handling, byte-level output, timing). Native-required tools must be
    rewritten in their source language before final submission; this is
    surfaced in the dispatch queue so workers route accordingly.
    """
    path = FACTORY_DIR / "LANGUAGE_CLASSIFICATION.json"
    if not path.is_file():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        bs = r.get("base_slug")
        if bs:
            out[bs] = r
    return out


def queue_row(
    row: dict[str, Any], lang_index: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Reduce a full board row to the worker-relevant fields."""
    base = {
        "slug": row.get("slug") or row.get("base_slug"),
        "base_slug": row.get("base_slug"),
        "next_action": row.get("next_action"),
        "best_score": row.get("best_score"),
        "best_passed": row.get("best_passed"),
        "best_runnable_total": row.get("best_runnable_total"),
        "latest_score": row.get("latest_score"),
        "latest_regressed_from_best": row.get("latest_regressed_from_best"),
        "has_override": row.get("has_override"),
        "has_eval": row.get("has_eval"),
        "best_eval_path": row.get("best_eval_path"),
        "locked_dir": row.get("locked_dir"),
    }
    if lang_index is not None:
        cls = lang_index.get(row.get("base_slug") or "") or {}
        base["language_classification"] = cls.get("classification")
        base["language_confidence"] = cls.get("confidence")
        base["source_language"] = cls.get("source_language")
    return base


def cluster_report_exists(slug: str) -> bool:
    return (INVENTORY_DIR / f"{slug}.official_cluster_report.json").is_file()


def _run_cluster(slug: str, eval_path: str, py: str) -> bool:
    """Invoke pb_cluster_from_eval.py for a slug + eval path. Returns True on success."""
    cmd = [
        py,
        str(ROOT / "scripts" / "pb_cluster_from_eval.py"),
        slug,
        str(eval_path),
        "--out-dir",
        str(INVENTORY_DIR),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if proc.returncode != 0:
            sys.stderr.write(f"cluster step failed for {slug}: {proc.stderr[:400]}\n")
            return False
        return True
    except Exception as e:
        sys.stderr.write(f"cluster subprocess error for {slug}: {e}\n")
        return False


def _run_make_packet(slug: str, py: str) -> Path | None:
    """Invoke pb_make_packet.py for a slug. Returns the packet path on success."""
    cmd = [py, str(ROOT / "scripts" / "pb_make_packet.py"), slug]
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if proc.returncode != 0:
            sys.stderr.write(f"make-packet step failed for {slug}: {proc.stderr[:400]}\n")
            return None
        return FACTORY_DIR / slug / "PACKET.md"
    except Exception as e:
        sys.stderr.write(f"make-packet subprocess error for {slug}: {e}\n")
        return None


def write_queue(queue: list[dict[str, Any]], extras: dict[str, Any] | None = None) -> Path:
    FACTORY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "queue": queue,
        **(extras or {}),
    }
    QUEUE_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return QUEUE_JSON


def print_summary(queue: list[dict[str, Any]]) -> None:
    if not queue:
        print("(queue is empty)")
        return
    print(
        f"{'#':>3} {'slug':<48} {'action':<22} {'best':>10} {'lang':<18} {'override':<8} {'has_eval':<8}"
    )
    print("-" * 130)
    for i, r in enumerate(queue, 1):
        bp = r.get("best_passed") or 0
        brt = r.get("best_runnable_total") or 0
        bs = r.get("best_score")
        bs_disp = f"{bs:5.1f}" if isinstance(bs, (int, float)) else "  n/a"
        ov = "Y" if r.get("has_override") else "-"
        ev = "Y" if r.get("has_eval") else "-"
        lc = r.get("language_classification") or "?"
        lconf = r.get("language_confidence") or "?"
        lang_disp = f"{lc[:11]}/{lconf[:1]}" if lc != "?" else "?"
        print(
            f"{i:>3} {str(r.get('slug') or '?'):<48} {str(r.get('next_action') or '?'):<22} "
            f"{bs_disp}/{bp}/{brt:<5} {lang_disp:<18} {ov:<8} {ev:<8}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--top", type=int, default=5, help="how many top candidates to queue (default: 5)"
    )
    ap.add_argument(
        "--slug", default=None, help="dispatch a specific slug, ignoring priority ordering"
    )
    ap.add_argument(
        "--include-recovery",
        action="store_true",
        help="include create-override (recovery-first) rows in the queue",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="rank and write queue JSON, but do NOT run cluster or make-packet steps",
    )
    ap.add_argument(
        "--python", default=sys.executable, help="Python interpreter for sub-script invocations"
    )
    args = ap.parse_args()

    board = _load_board(BOARD_JSON)
    if not board:
        sys.stderr.write("no board rows; aborting\n")
        return 2

    if args.slug:
        row = find_row_by_slug(board, args.slug)
        if row is None:
            sys.stderr.write(f"slug not in board: {args.slug}\n")
            return 2
        if _is_locked(row):
            sys.stderr.write(f"slug is locked: {args.slug}\n")
            return 2
        ranked = [row]
    else:
        ranked = filter_and_rank(board, include_recovery=args.include_recovery)[: args.top]

    lang_index = _load_language_classification()
    queue = [queue_row(r, lang_index=lang_index) for r in ranked]
    extras: dict[str, Any] = {
        "filters": {
            "include_recovery": bool(args.include_recovery),
            "slug": args.slug,
            "top": args.top,
        },
        "ran_cluster_step": [],
        "ran_make_packet_step": [],
        "skipped": [],
        "dry_run": bool(args.dry_run),
    }

    if not args.dry_run:
        for r in queue:
            slug = r.get("slug")
            if not slug:
                extras["skipped"].append({"slug": None, "reason": "no slug"})
                continue
            ev = r.get("best_eval_path")
            if ev and not cluster_report_exists(slug):
                if _run_cluster(slug, ev, args.python):
                    extras["ran_cluster_step"].append({"slug": slug, "eval_path": ev})
                else:
                    extras["skipped"].append({"slug": slug, "reason": "cluster step failed"})
            packet = _run_make_packet(slug, args.python)
            if packet:
                extras["ran_make_packet_step"].append({"slug": slug, "packet": str(packet)})
            else:
                extras["skipped"].append({"slug": slug, "reason": "make-packet step failed"})

    out = write_queue(queue, extras=extras)
    print(f"wrote {out}")
    print()
    print_summary(queue)
    if args.dry_run:
        print()
        print("(dry-run: no clusters generated, no packets written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
