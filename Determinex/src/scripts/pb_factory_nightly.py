#!/usr/bin/env python3
"""Nightly orchestrator for the ProgramBench factory.

Chains the existing pieces into one pass:

    [execute only]  pb_score_audit.py                 # refresh board
                    pb_factory_dispatch.py --top N    # write DISPATCH_QUEUE.json + packets
    for each slug in queue:
                    pb_factory_worker_loop.py <slug> [--execute|--dry-run]

Outputs two artifacts:
    logs/programbench_factory/nightly/nightly_<utc-ts>_result.json
    logs/programbench_factory/nightly/nightly_<utc-ts>_report.md

Default mode is dry-run. Dry-run:
    - SKIPS pb_score_audit.py (state-modifying - board JSON would be rewritten).
    - Runs pb_factory_dispatch.py with --dry-run (writes queue, no packets).
    - Runs pb_factory_worker_loop.py with --dry-run for each queued slug
      (writes prompt + result + report logs, no source/registry changes).

Execute mode (--execute):
    - Refuses if `git status` shows ANY dirty file, unless --allow-dirty.
    - Runs pb_score_audit.py, then pb_factory_dispatch.py (writes packets),
      then pb_factory_worker_loop.py --execute for each queued slug.
    - Worker loop calls model-cmd, applies diff, runs official eval + gate,
      and chains through pb_apply_gate_decision.py on accept.

Stop controls:
    --stop-on-accept   stop the nightly after first worker that exited 0
    --stop-on-error    stop after first subprocess exit 2 or 3
    --slug <slug>      bypass dispatch; run only one slug

Exit codes:
    0 = dry-run complete, OR all workers ran without infra failure
    1 = at least one worker rejected its candidate (no infra failure)
    2 = subprocess infra failure (pack/eval/gate/apply crashed somewhere)
    3 = bad input / unsafe state (dirty tree refused, missing args, etc.)

Hard rules enforced:
    - Never directly edits tests, fixtures, locked archives, override sources,
      or shared scripts. Every state change is delegated to a sub-script.
    - Never runs the official eval directly - only via pb_candidate_gate.py
      inside the worker loop (and only in --execute).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTORY_DIR = ROOT / "logs" / "programbench_factory"
NIGHTLY_DIR = FACTORY_DIR / "nightly"
DISPATCH_QUEUE_JSON = FACTORY_DIR / "DISPATCH_QUEUE.json"
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
REGISTRY_JSONL = FACTORY_DIR / "accepted_runs.jsonl"

SCRIPTS = {
    "audit": ROOT / "scripts" / "pb_score_audit.py",
    "dispatch": ROOT / "scripts" / "pb_factory_dispatch.py",
    "worker": ROOT / "scripts" / "pb_factory_worker_loop.py",
}


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _utc_tag() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def _git_head() -> str:
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if p.returncode == 0:
            return p.stdout.strip()
    except Exception:
        pass
    return ""


def _git_dirty() -> list[str]:
    """Return all dirty path entries from `git status --porcelain` (modified + untracked)."""
    try:
        p = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except Exception:
        return []
    if p.returncode != 0:
        return []
    out: list[str] = []
    for line in (p.stdout or "").splitlines():
        if len(line) < 4:
            continue
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        out.append(path_part.strip('"').replace("\\", "/"))
    return out


def _registry_row_count() -> int:
    if not REGISTRY_JSONL.is_file():
        return 0
    try:
        with REGISTRY_JSONL.open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _run(cmd: list[str], timeout: int = 600) -> dict[str, Any]:
    started = _utc_now()
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        p = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        return {
            "cmd": cmd,
            "started": started,
            "finished": _utc_now(),
            "returncode": p.returncode,
            "stdout_tail": (p.stdout or "")[-3000:],
            "stderr_tail": (p.stderr or "")[-3000:],
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": cmd,
            "started": started,
            "finished": _utc_now(),
            "returncode": -1,
            "error": f"timeout after {timeout}s",
        }
    except Exception as e:
        return {
            "cmd": cmd,
            "started": started,
            "finished": _utc_now(),
            "returncode": -1,
            "error": f"{type(e).__name__}: {e}",
        }


def _read_queue() -> list[dict[str, Any]]:
    if not DISPATCH_QUEUE_JSON.is_file():
        return []
    try:
        d = json.loads(DISPATCH_QUEUE_JSON.read_text(encoding="utf-8"))
        return d.get("queue", []) if isinstance(d, dict) else []
    except Exception:
        return []


def _read_worker_result(slug: str) -> dict[str, Any] | None:
    p = FACTORY_DIR / slug / "worker_loop_result.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _board_row(slug: str) -> dict[str, Any] | None:
    if not BOARD_JSON.is_file():
        return None
    try:
        board = json.loads(BOARD_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None
    for r in board:
        if r.get("slug") == slug:
            return r
    return None


def write_nightly_artifacts(tag: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    NIGHTLY_DIR.mkdir(parents=True, exist_ok=True)
    json_path = NIGHTLY_DIR / f"nightly_{tag}_result.json"
    md_path = NIGHTLY_DIR / f"nightly_{tag}_report.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown report
    lines: list[str] = []
    lines.append("# Nightly factory run report")
    lines.append("")
    lines.append(f"- Timestamp: `{payload.get('timestamp')}`")
    lines.append(f"- Mode: **{'dry-run' if payload.get('dry_run') else 'execute'}**")
    lines.append(f"- git HEAD: `{payload.get('git_head', '')}`")
    lines.append(f"- Dirty files at start: {len(payload.get('git_dirty_before') or [])}")
    lines.append(f"- Registry rows before: {payload.get('registry_rows_before')}")
    lines.append(f"- Registry rows after:  {payload.get('registry_rows_after')}")
    lines.append(f"- Exit code: **{payload.get('exit_code')}**")
    lines.append("")
    lines.append("## Args")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload.get("args") or {}, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Pre-flight subprocesses")
    lines.append("")
    if not payload.get("preflight"):
        lines.append("(none)")
    else:
        for c in payload["preflight"]:
            lines.append(f"- step `{c.get('step')}`: rc={c.get('returncode')}")
            lines.append(f"    cmd: `{' '.join(str(x) for x in c.get('cmd', []))}`")
    lines.append("")
    lines.append("## Queue")
    lines.append("")
    if not payload.get("queue"):
        lines.append("(empty)")
    else:
        lines.append("| # | slug | next_action | best_score | best_passed/runnable |")
        lines.append("|---:|---|---|---:|---:|")
        for i, q in enumerate(payload["queue"], 1):
            bp = q.get("best_passed")
            brt = q.get("best_runnable_total")
            bs = q.get("best_score")
            bs_disp = f"{bs:.2f}" if isinstance(bs, (int, float)) else "n/a"
            lines.append(
                f"| {i} | `{q.get('slug')}` | {q.get('next_action')} | {bs_disp} | {bp}/{brt} |"
            )
    lines.append("")
    lines.append("## Per-slug results")
    lines.append("")
    for r in payload.get("per_slug") or []:
        lines.append(f"### `{r.get('slug')}` -- {r.get('disposition') or 'n/a'}")
        lines.append("")
        lines.append(f"- worker exit code: `{r.get('returncode')}`")
        wr = r.get("worker_result") or {}
        if wr:
            lines.append(f"- worker final_disposition: `{wr.get('final_disposition')}`")
            lines.append(f"- worker attempts: {len(wr.get('attempts') or [])}")
            if wr.get("baseline_eval"):
                lines.append(f"- baseline eval: `{wr.get('baseline_eval')}`")
        if r.get("stderr_tail"):
            lines.append("- stderr_tail (truncated):")
            lines.append("    ```")
            lines.append("    " + r["stderr_tail"][-600:].replace("\n", "\n    "))
            lines.append("    ```")
        lines.append("")
    lines.append("## Next safe action")
    lines.append("")
    lines.append(payload.get("next_safe_action", "(none)"))
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--top", type=int, default=3, help="how many queue slots to process (default 3)"
    )
    ap.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="per-slug worker loop attempt budget (default 2)",
    )
    ap.add_argument(
        "--model-cmd", default=None, help="shell command for the model. Required for --execute."
    )
    ap.add_argument(
        "--execute", action="store_true", help="actually invoke the chain. Default is dry-run."
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="explicit dry-run (default if --execute is absent)",
    )
    ap.add_argument(
        "--allow-dirty", action="store_true", help="permit --execute even when git has dirty files"
    )
    ap.add_argument(
        "--stop-on-accept",
        action="store_true",
        help="stop the nightly after first worker that exits 0",
    )
    ap.add_argument(
        "--stop-on-error",
        action="store_true",
        help="stop after first worker exits 2 or 3 (infra failure)",
    )
    ap.add_argument("--slug", default=None, help="bypass dispatch; run a single slug")
    ap.add_argument(
        "--include-recovery", action="store_true", help="pass --include-recovery to the dispatcher"
    )
    ap.add_argument(
        "--refresh-board",
        action="store_true",
        help="pass --refresh-board to each worker invocation",
    )
    ap.add_argument(
        "--refresh-rag", action="store_true", help="pass --refresh-rag to each worker invocation"
    )
    ap.add_argument(
        "--python", default=sys.executable, help="Python interpreter for sub-script invocations"
    )
    args = ap.parse_args()

    dry_run = (not args.execute) or args.dry_run
    tag = _utc_tag()
    rows_before = _registry_row_count()
    dirty_before = _git_dirty()

    payload: dict[str, Any] = {
        "timestamp": _utc_now(),
        "tag": tag,
        "dry_run": dry_run,
        "git_head": _git_head(),
        "git_dirty_before": dirty_before,
        "registry_rows_before": rows_before,
        "args": {
            "top": args.top,
            "max_attempts": args.max_attempts,
            "model_cmd": args.model_cmd,
            "execute": bool(args.execute),
            "dry_run_flag": bool(args.dry_run),
            "allow_dirty": bool(args.allow_dirty),
            "stop_on_accept": bool(args.stop_on_accept),
            "stop_on_error": bool(args.stop_on_error),
            "slug": args.slug,
            "include_recovery": bool(args.include_recovery),
            "refresh_board": bool(args.refresh_board),
            "refresh_rag": bool(args.refresh_rag),
            "python": args.python,
        },
        "preflight": [],
        "queue": [],
        "per_slug": [],
    }

    # ----- input validation -----
    if args.top < 1:
        payload["exit_code"] = 3
        payload["error"] = "--top must be >= 1"
        payload["next_safe_action"] = "Pass --top with a value >= 1."
        write_nightly_artifacts(tag, payload)
        sys.stderr.write("ERROR: --top must be >= 1\n")
        return 3
    if args.max_attempts < 1:
        payload["exit_code"] = 3
        payload["error"] = "--max-attempts must be >= 1"
        payload["next_safe_action"] = "Pass --max-attempts with a value >= 1."
        write_nightly_artifacts(tag, payload)
        return 3
    if args.execute and not args.model_cmd:
        payload["exit_code"] = 3
        payload["error"] = "--execute requires --model-cmd"
        payload["next_safe_action"] = 'Pass --model-cmd "<shell command>" or remove --execute.'
        write_nightly_artifacts(tag, payload)
        sys.stderr.write("ERROR: --execute requires --model-cmd\n")
        return 3

    # ----- dirty-tree guard (execute only) -----
    if args.execute and dirty_before and not args.allow_dirty:
        payload["exit_code"] = 3
        payload["error"] = (
            f"git has {len(dirty_before)} dirty path(s). Refusing to --execute without --allow-dirty."
        )
        payload["next_safe_action"] = (
            "Either commit/stash the dirty changes, or pass --allow-dirty if they are intentional."
        )
        write_nightly_artifacts(tag, payload)
        sys.stderr.write(payload["error"] + "\n")
        return 3

    # ===== Pre-flight subprocesses =====

    # Step 1: board refresh (execute only; dry-run leaves the board untouched)
    if not dry_run:
        rec = _run([args.python, str(SCRIPTS["audit"])], timeout=300)
        payload["preflight"].append({"step": "score_audit", **rec})
        if rec.get("returncode") != 0:
            payload["exit_code"] = 2
            payload["error"] = "pb_score_audit.py failed"
            payload["next_safe_action"] = "Inspect the audit stderr_tail in this report."
            write_nightly_artifacts(tag, payload)
            return 2
    else:
        payload["preflight"].append(
            {
                "step": "score_audit",
                "skipped": True,
                "reason": "dry-run: would rewrite logs/programbench_lock_board.json",
            }
        )

    # Step 2: dispatch (or skip if --slug)
    if args.slug:
        # Bypass dispatch and synthesize a one-row queue from the board.
        row = _board_row(args.slug)
        if row is None:
            payload["exit_code"] = 3
            payload["error"] = f"slug not found in board: {args.slug}"
            payload["next_safe_action"] = (
                "Run scripts\\pb_score_audit.py to refresh the board first."
            )
            write_nightly_artifacts(tag, payload)
            return 3
        queue = [
            {
                "slug": row.get("slug"),
                "base_slug": row.get("base_slug"),
                "next_action": row.get("next_action"),
                "best_score": row.get("best_score"),
                "best_passed": row.get("best_passed"),
                "best_runnable_total": row.get("best_runnable_total"),
                "best_eval_path": row.get("best_eval_path"),
            }
        ]
        payload["preflight"].append(
            {
                "step": "dispatch",
                "skipped": True,
                "reason": f"--slug={args.slug} bypassed dispatch",
            }
        )
    else:
        dispatch_cmd = [
            args.python,
            str(SCRIPTS["dispatch"]),
            "--top",
            str(args.top),
            "--python",
            args.python,
        ]
        if args.include_recovery:
            dispatch_cmd.append("--include-recovery")
        if dry_run:
            dispatch_cmd.append("--dry-run")
        rec = _run(dispatch_cmd, timeout=600)
        payload["preflight"].append({"step": "dispatch", **rec})
        if rec.get("returncode") != 0:
            payload["exit_code"] = 2
            payload["error"] = "pb_factory_dispatch.py failed"
            payload["next_safe_action"] = "Inspect dispatch stderr_tail in this report."
            write_nightly_artifacts(tag, payload)
            return 2
        queue = _read_queue()

    payload["queue"] = queue
    if not queue:
        payload["exit_code"] = 0
        payload["disposition"] = "empty queue - nothing to process"
        payload["next_safe_action"] = (
            "Verify the board has actionable rows by running scripts\\pb_score_audit.py."
        )
        write_nightly_artifacts(tag, payload)
        return 0

    # ===== Per-slug worker loops =====

    final_exit = 0  # 0/1/2 - promoted as we go
    accepted_count = 0
    rejected_count = 0
    error_count = 0
    stopped_reason: str | None = None

    for q in queue:
        slug = q.get("slug")
        if not slug:
            continue

        worker_cmd = [
            args.python,
            str(SCRIPTS["worker"]),
            slug,
            "--max-attempts",
            str(args.max_attempts),
            "--python",
            args.python,
        ]
        if args.model_cmd:
            worker_cmd += ["--model-cmd", args.model_cmd]
        if args.refresh_board:
            worker_cmd.append("--refresh-board")
        if args.refresh_rag:
            worker_cmd.append("--refresh-rag")
        if dry_run:
            worker_cmd.append("--dry-run")
        else:
            worker_cmd.append("--execute")
        if args.allow_dirty:
            worker_cmd.append("--allow-dirty")

        # Worker loops may take a while in execute mode (model call + Docker eval).
        # Give a generous timeout but cap so we don't hang the nightly forever.
        timeout = 7200 if (not dry_run) else 120
        rec = _run(worker_cmd, timeout=timeout)
        worker_result = _read_worker_result(slug)

        rc = rec.get("returncode")
        if rc == 0:
            disposition = (
                "accepted"
                if (worker_result and worker_result.get("final_disposition") == "accepted")
                else "dry-run-complete"
                if (worker_result and worker_result.get("final_disposition") == "dry-run-complete")
                else "ok"
            )
            if disposition == "accepted":
                accepted_count += 1
        elif rc == 1:
            disposition = "rejected-all-attempts"
            rejected_count += 1
            final_exit = max(final_exit, 1)
        elif rc in (2, 3):
            disposition = f"infra-failure (rc={rc})"
            error_count += 1
            final_exit = 2
        else:
            disposition = f"unknown rc={rc}"
            error_count += 1
            final_exit = 2

        payload["per_slug"].append(
            {
                "slug": slug,
                "returncode": rc,
                "disposition": disposition,
                "worker_result": worker_result,
                "cmd": rec.get("cmd"),
                "stderr_tail": (rec.get("stderr_tail") or "")[-2000:],
            }
        )

        # Stop controls
        if args.stop_on_accept and rc == 0:
            stopped_reason = f"--stop-on-accept fired after slug `{slug}` (rc=0)"
            break
        if args.stop_on_error and rc in (2, 3):
            stopped_reason = f"--stop-on-error fired after slug `{slug}` (rc={rc})"
            break

    # ===== Wrap up =====
    rows_after = _registry_row_count()
    payload["registry_rows_after"] = rows_after
    payload["dirty_after"] = _git_dirty()
    payload["accepted_count"] = accepted_count
    payload["rejected_count"] = rejected_count
    payload["error_count"] = error_count
    payload["stopped_reason"] = stopped_reason
    payload["exit_code"] = final_exit

    # next safe action
    if dry_run:
        payload["next_safe_action"] = (
            "Dry-run complete. Inspect each slug's worker_loop_report.md to verify the planned "
            "commands. Re-run with --execute and a real --model-cmd to actually invoke the chain."
        )
    elif error_count > 0:
        payload["next_safe_action"] = (
            "One or more workers reported an infra failure (rc 2 or 3). Inspect "
            "the per_slug stderr_tail and the worker_loop_result.json for each affected slug "
            "before retrying. Do NOT loop in execute mode until the root cause is understood."
        )
    elif rejected_count > 0:
        payload["next_safe_action"] = (
            "Some workers had all attempts rejected by the gate. Their rejected lessons "
            "are in logs/programbench_factory/<slug>/lessons/. Consider narrower cluster "
            "targets or running scripts\\pb_upstream_oracle.py on disputed fixtures."
        )
    elif accepted_count > 0:
        payload["next_safe_action"] = (
            f"{accepted_count} accept(s) recorded. The accept-chain has already run "
            f"(register + lesson + optional board/RAG refresh). Codex should review the working-tree "
            f"diffs and commit when ready."
        )
    else:
        payload["next_safe_action"] = "Queue was empty or all workers were no-ops."

    json_path, md_path = write_nightly_artifacts(tag, payload)

    # Console summary
    print(
        json.dumps(
            {
                "tag": tag,
                "dry_run": dry_run,
                "queue_size": len(queue),
                "accepted": accepted_count,
                "rejected": rejected_count,
                "errors": error_count,
                "stopped_reason": stopped_reason,
                "exit_code": final_exit,
                "result_json": str(json_path),
                "report_md": str(md_path),
            },
            indent=2,
        )
    )

    return final_exit


if __name__ == "__main__":
    raise SystemExit(main())
