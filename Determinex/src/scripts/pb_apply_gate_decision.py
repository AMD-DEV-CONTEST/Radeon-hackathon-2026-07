#!/usr/bin/env python3
"""Mechanical post-gate dispatcher for ProgramBench candidates.

Reads a `gate_result.json` produced by `scripts/pb_candidate_gate.py` and
runs the canonical accept-chain or reject-chain so a worker (LLM or human)
never has to improvise which post-gate scripts to run in which order.

Accept chain:
    1. pb_lesson_writer.py <slug> <gate_json> [--report ...]
    2. pb_register_gate_result.py <slug> <gate_json> --promote-run-root <run_root> [--refresh-board]
    3. [if --refresh-rag] pb_refresh_rag_after_accept.py --require-accepted-run

Reject chain:
    1. pb_lesson_writer.py <slug> <gate_json> [--report ...]   # emits the reject-variant
    (no registry, no RAG refresh, no board refresh)

In both cases, the script writes:
    logs/programbench_factory/<slug>/apply_gate_result.json
which records every command, its return code, stdout/stderr tails, and the
final disposition.

Exit codes:
    0 = accept chain completed successfully
    1 = clean reject path (lesson written; revert NOT performed by this script)
    2 = subprocess failure (one of the chained scripts crashed)
    3 = bad input (missing gate JSON, malformed JSON, missing slug, etc.)

Safety guarantees (enforced):
    - Never edits any file under `corpus/programbench/locked/*`.
    - Never edits any file under `corpus/programbench/per_tool_overrides/<slug>/`.
      (The candidate source change must already have been made by the worker before
      pack+eval+gate; this script is post-gate orchestration only.)
    - Never edits any file under `T:/Dev/ProgramBench/` or any test/fixture.
    - Never runs `programbench_eval_runner.py` directly. (The gate has already run it.)
    - `--dry-run` prints intended commands and writes no files.

Usage:
    python scripts\\pb_apply_gate_decision.py <slug> <gate_result.json> \\
        --run-root .determinex_staging\\pb_<short>_<tag> \\
        [--report logs/programbench_factory/<slug>/REPORT.md] \\
        [--refresh-board] [--refresh-rag] [--dry-run] [--python <interpreter>]
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

SCRIPTS = {
    "lesson": ROOT / "scripts" / "pb_lesson_writer.py",
    "register": ROOT / "scripts" / "pb_register_gate_result.py",
    "refresh": ROOT / "scripts" / "pb_refresh_rag_after_accept.py",
    "audit": ROOT / "scripts" / "pb_score_audit.py",
    "verdict_corpus": ROOT / "scripts" / "pb_verdict_corpus.py",
    "hint_audit": ROOT / "scripts" / "pb_corpus_hint_audit.py",
}


def _verdict_corpus_ingest(gate_path: Path, *, dry_run: bool) -> dict[str, Any]:
    """Non-fatal apply-time hook into the labeled training corpus.

    Both Rule A and Rule B accept chains call this. The corpus eats
    compiler-verified pass/fail signal from every accept regardless of
    which door the score came in. Failures here are logged and swallowed —
    the score ledger must NEVER be blocked by a corpus write.

    The slug is read from the gate_result.json itself; no parameter needed.
    """
    rec: dict[str, Any] = {"step": "verdict_corpus_ingest", "started": _utc_now()}
    if dry_run:
        rec["dry_run"] = True
        rec["returncode"] = 0
        rec["finished"] = _utc_now()
        return rec
    try:
        # Import lazily so a missing module here can never break the rest of the chain.
        sys.path.insert(0, str(ROOT / "scripts"))
        from pb_verdict_corpus import ingest_gate_result  # type: ignore[import-not-found]

        summary = ingest_gate_result(gate_path)
        rec["returncode"] = 1 if summary.get("errors") else 0
        rec["summary"] = summary
    except Exception as e:
        # NON-FATAL by design. Swallow, log into the record, return rc=0
        # so the gate decision still completes.
        rec["returncode"] = 0
        rec["non_fatal_error"] = f"{type(e).__name__}: {e}"
    rec["finished"] = _utc_now()
    return rec


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _read_gate(gate_path: Path) -> dict[str, Any] | None:
    if not gate_path.is_file():
        return None
    try:
        return json.loads(gate_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_decision(gate: dict[str, Any]) -> str:
    return str(gate.get("decision", "")).lower()


def _safe_decision_rule(gate: dict[str, Any]) -> str | None:
    """Return 'A' (strict/ledger), 'B' (sidecar), 'C' (progress), or None.

    Older gate_result.json files written before the two-ledger split lack this
    field. For backward compat: if decision='accept' and rule field is missing,
    treat as Rule A only if runnable_delta is 0; otherwise treat as Rule B.
    """
    raw = gate.get("decision_rule")
    if raw in ("A", "B", "C"):
        return raw
    if str(gate.get("decision", "")).lower() != "accept":
        return None
    rd = (gate.get("delta") or {}).get("runnable")
    if rd == 0:
        return "A"
    if rd is None:
        return None
    return "B"


def _run(cmd: list[str], *, dry_run: bool, cwd: Path = ROOT) -> dict[str, Any]:
    """Run a subprocess (or simulate in dry-run). Returns a record dict."""
    record: dict[str, Any] = {
        "cmd": cmd,
        "cwd": str(cwd),
        "started": _utc_now(),
    }
    if dry_run:
        record["dry_run"] = True
        record["returncode"] = 0
        record["finished"] = _utc_now()
        return record
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        record["returncode"] = proc.returncode
        record["stdout_tail"] = (proc.stdout or "")[-2000:]
        record["stderr_tail"] = (proc.stderr or "")[-2000:]
    except Exception as e:
        record["returncode"] = -1
        record["error"] = f"{type(e).__name__}: {e}"
    record["finished"] = _utc_now()
    return record


def _write_apply_result(slug: str, payload: dict[str, Any], dry_run: bool) -> Path:
    out_dir = FACTORY_DIR / slug
    out_path = out_dir / "apply_gate_result.json"
    if dry_run:
        payload["_would_write"] = str(out_path)
        return out_path
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def _accept_chain(
    slug: str,
    gate_path: Path,
    run_root: Path,
    report: Path | None,
    refresh_board: bool,
    refresh_rag: bool,
    py: str,
    dry_run: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Run the Rule A accept chain (strict, official ledger). Returns (exit_code, commands_run).

    This only runs when gate_result.json carries decision_rule='A'. Rule B
    accepts route through `_rule_b_sidecar_chain` instead and never touch
    `accepted_runs.jsonl` or the lock board.
    """
    cmds: list[dict[str, Any]] = []

    # 1) lesson writer
    lesson_cmd = [py, str(SCRIPTS["lesson"]), slug, str(gate_path)]
    if report:
        lesson_cmd += ["--report", str(report)]
    r = _run(lesson_cmd, dry_run=dry_run)
    cmds.append({"step": "lesson", **r})
    if r["returncode"] != 0:
        return 2, cmds

    # 2) register accepted gate
    register_cmd = [
        py,
        str(SCRIPTS["register"]),
        slug,
        str(gate_path),
        "--promote-run-root",
        str(run_root),
    ]
    if refresh_board:
        register_cmd.append("--refresh-board")
    register_cmd += ["--python", py]
    r = _run(register_cmd, dry_run=dry_run)
    cmds.append({"step": "register", **r})
    if r["returncode"] != 0:
        return 2, cmds

    # 3) optional RAG refresh
    if refresh_rag:
        refresh_cmd = [py, str(SCRIPTS["refresh"]), "--require-accepted-run", "--python", py]
        r = _run(refresh_cmd, dry_run=dry_run)
        cmds.append({"step": "refresh_rag", **r})
        if r["returncode"] != 0:
            return 2, cmds

    # 4) verdict-corpus ingest (non-fatal). Compiler-verified pass/fail rows
    # land in pb_verdict_corpus.jsonl. A failure here MUST NOT abort the gate
    # decision — the score ledger is the source of truth, the corpus is downstream.
    cmds.append(_verdict_corpus_ingest(gate_path, dry_run=dry_run))

    return 0, cmds


def _rule_b_sidecar_chain(
    slug: str,
    gate_path: Path,
    gate: dict[str, Any],
    report: Path | None,
    py: str,
    dry_run: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Sidecar chain for Rule B (pure-improvement on shifted runnable surface).

    Writes:
      - logs/programbench_factory/rule_b_promotions.jsonl  (one line per Rule B accept)
      - lock board annotation under info['rule_b_discovery']
      - the lesson (same as Rule A — Rule B work is still real work)

    Does NOT write:
      - accepted_runs.jsonl  (those are Rule A only)
      - lock board best_passed / best_runnable_total / best_eval_path  (those are Rule A only)

    A Rule B promotion becomes eligible for official ledger only after a clean
    Rule A re-gate against the new runnable baseline.
    """
    cmds: list[dict[str, Any]] = []
    import datetime as _dt

    # 1) lesson writer (Rule B work still earns a lesson)
    lesson_cmd = [py, str(SCRIPTS["lesson"]), slug, str(gate_path)]
    if report:
        lesson_cmd += ["--report", str(report)]
    r = _run(lesson_cmd, dry_run=dry_run)
    cmds.append({"step": "lesson", **r})
    if r["returncode"] != 0:
        return 2, cmds

    # 2) write the Rule B promotion line to the sidecar ledger
    sidecar_path = FACTORY_DIR / "rule_b_promotions.jsonl"
    delta = gate.get("delta") or {}
    record = {
        "slug": slug,
        "timestamp": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "decision_rule": "B",
        "baseline_path": gate.get("baseline_path"),
        "candidate_run_root": gate.get("candidate_run_root"),
        "baseline_passed": ((gate.get("baseline") or {}).get("passed")),
        "baseline_runnable": ((gate.get("baseline") or {}).get("runnable")),
        "candidate_passed": ((gate.get("candidate") or {}).get("passed")),
        "candidate_runnable": ((gate.get("candidate") or {}).get("runnable")),
        "delta_passed": delta.get("passed"),
        "delta_runnable": delta.get("runnable"),
        "newly_passing_count": len(delta.get("newly_passing") or []),
        "newly_failing_count": len(delta.get("newly_failing") or []),
        "regression_class_counts": delta.get("regression_class_counts", {}),
        "regression_classes": delta.get("regression_classes", {}),
        "gate_result_path": str(gate_path),
        "audit_note": (
            "Rule B sidecar: pure-improvement on a shifted runnable surface. NOT in the "
            "official ledger. Needs a clean Rule A re-gate against the new baseline before "
            "promotion to accepted_runs.jsonl / lock board best_*."
        ),
    }
    sidecar_record = {"path": str(sidecar_path), "record": record}
    if dry_run:
        cmds.append({"step": "rule_b_sidecar_write", "dry_run": True, **sidecar_record})
    else:
        try:
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            with sidecar_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            cmds.append({"step": "rule_b_sidecar_write", "returncode": 0, **sidecar_record})
        except OSError as e:
            cmds.append(
                {
                    "step": "rule_b_sidecar_write",
                    "returncode": -1,
                    "error": f"{type(e).__name__}: {e}",
                    **sidecar_record,
                }
            )
            return 2, cmds

    # 3) annotate the lock board with rule_b_discovery (preserves the high-water
    # mark for cortex-pull's view, never touches best_* fields).
    board_path = ROOT / "logs" / "programbench_lock_board.json"
    base_slug = slug.rsplit(".", 1)[0]  # strip the .hash suffix
    if dry_run:
        cmds.append(
            {
                "step": "rule_b_board_annotate",
                "dry_run": True,
                "board_path": str(board_path),
                "base_slug": base_slug,
            }
        )
    else:
        try:
            board = json.loads(board_path.read_text(encoding="utf-8"))
            patched = False
            cand_eval = ""
            run_root_str = gate.get("candidate_run_root", "")
            if run_root_str:
                from pathlib import Path as _P

                rr = _P(run_root_str) / slug
                for p in rr.glob("*.eval.json"):
                    cand_eval = str(p)
                    break
            for info in board:
                if info.get("base_slug") == base_slug:
                    info["rule_b_discovery"] = {
                        "passed": record["candidate_passed"],
                        "runnable_total": record["candidate_runnable"],
                        "eval_path": cand_eval,
                        "captured_at": record["timestamp"],
                        "note": (
                            "Pure-improvement (+passing, 0 regressions) but runnable changed; "
                            "awaits clean Rule A baseline rerun before entering official ledger."
                        ),
                    }
                    patched = True
                    break
            if patched:
                board_path.write_text(
                    json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                cmds.append(
                    {
                        "step": "rule_b_board_annotate",
                        "returncode": 0,
                        "board_path": str(board_path),
                        "base_slug": base_slug,
                    }
                )
            else:
                cmds.append(
                    {
                        "step": "rule_b_board_annotate",
                        "returncode": 0,
                        "board_path": str(board_path),
                        "base_slug": base_slug,
                        "note": "no matching board entry — discovery recorded in sidecar only",
                    }
                )
        except (OSError, json.JSONDecodeError) as e:
            cmds.append(
                {
                    "step": "rule_b_board_annotate",
                    "returncode": -1,
                    "error": f"{type(e).__name__}: {e}",
                    "board_path": str(board_path),
                }
            )
            # Don't fail the chain — sidecar is the source of truth, board annotation is helper.

    # 4) verdict-corpus ingest (non-fatal). Rule B passes/fails are compiler-verified
    # ground truth and feed the LoRA training corpus immediately. The score
    # remains Rule A only; the corpus eats both rules.
    cmds.append(_verdict_corpus_ingest(gate_path, dry_run=dry_run))

    return 0, cmds


def _rule_c_progress_chain(
    slug: str,
    gate_path: Path,
    gate: dict[str, Any],
    report: Path | None,
    py: str,
    dry_run: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Progress chain for Rule C (net-positive improvement with regressions to fix).

    Writes:
      - logs/programbench_factory/rule_c_progress.jsonl  (one line per Rule C accept)
      - lock board annotation under info['rule_c_progress'] with the regression list
      - the lesson (real work, real training signal)

    Does NOT write:
      - accepted_runs.jsonl  (Rule A only)
      - lock board best_passed / best_runnable_total  (Rule A only)
      - rule_b_promotions.jsonl  (Rule B only)

    To promote Rule C to the official ledger: fix the listed regressions then run
    a clean Rule A re-gate. The regression list in rule_c_progress board annotation
    is the exact fix target.
    """
    cmds: list[dict[str, Any]] = []
    import datetime as _dt

    # 1) lesson writer
    lesson_cmd = [py, str(SCRIPTS["lesson"]), slug, str(gate_path)]
    if report:
        lesson_cmd += ["--report", str(report)]
    r = _run(lesson_cmd, dry_run=dry_run)
    cmds.append({"step": "lesson", **r})
    if r["returncode"] != 0:
        return 2, cmds

    # 2) write Rule C progress line to sidecar ledger
    sidecar_path = FACTORY_DIR / "rule_c_progress.jsonl"
    delta = gate.get("delta") or {}
    newly_failing = delta.get("newly_failing") or []
    record = {
        "slug": slug,
        "timestamp": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "decision_rule": "C",
        "baseline_path": gate.get("baseline_path"),
        "candidate_run_root": gate.get("candidate_run_root"),
        "baseline_passed": ((gate.get("baseline") or {}).get("passed")),
        "baseline_runnable": ((gate.get("baseline") or {}).get("runnable")),
        "candidate_passed": ((gate.get("candidate") or {}).get("passed")),
        "candidate_runnable": ((gate.get("candidate") or {}).get("runnable")),
        "delta_passed": delta.get("passed"),
        "delta_runnable": delta.get("runnable"),
        "newly_passing_count": len(delta.get("newly_passing") or []),
        "newly_failing_count": len(newly_failing),
        "newly_failing": newly_failing,
        "regression_class_counts": delta.get("regression_class_counts", {}),
        "regression_classes": delta.get("regression_classes", {}),
        "gate_result_path": str(gate_path),
        "audit_note": (
            "Rule C progress: net-positive improvement with regressions. NOT in the "
            "official ledger. Fix the newly_failing list then run a clean Rule A gate."
        ),
    }
    sidecar_record = {"path": str(sidecar_path), "record": record}
    if dry_run:
        cmds.append({"step": "rule_c_sidecar_write", "dry_run": True, **sidecar_record})
    else:
        try:
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            with sidecar_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            cmds.append({"step": "rule_c_sidecar_write", "returncode": 0, **sidecar_record})
        except OSError as e:
            cmds.append(
                {
                    "step": "rule_c_sidecar_write",
                    "returncode": -1,
                    "error": f"{type(e).__name__}: {e}",
                    **sidecar_record,
                }
            )
            return 2, cmds

    # 3) annotate the lock board with rule_c_progress — includes regression list as fix target
    board_path = ROOT / "logs" / "programbench_lock_board.json"
    base_slug = slug.rsplit(".", 1)[0]
    if dry_run:
        cmds.append(
            {
                "step": "rule_c_board_annotate",
                "dry_run": True,
                "board_path": str(board_path),
                "base_slug": base_slug,
            }
        )
    else:
        try:
            board = json.loads(board_path.read_text(encoding="utf-8"))
            patched = False
            cand_eval = ""
            run_root_str = gate.get("candidate_run_root", "")
            if run_root_str:
                from pathlib import Path as _P

                rr = _P(run_root_str) / slug
                for p in rr.glob("*.eval.json"):
                    cand_eval = str(p)
                    break
            for info in board:
                if info.get("base_slug") == base_slug:
                    info["rule_c_progress"] = {
                        "passed": record["candidate_passed"],
                        "runnable_total": record["candidate_runnable"],
                        "eval_path": cand_eval,
                        "newly_failing": newly_failing,
                        "newly_failing_count": len(newly_failing),
                        "captured_at": record["timestamp"],
                        "note": (
                            f"Progress: +{record['delta_passed']} passed, "
                            f"{len(newly_failing)} regressions to fix before rule A eligibility."
                        ),
                    }
                    patched = True
                    break
            if patched:
                board_path.write_text(
                    json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                cmds.append(
                    {
                        "step": "rule_c_board_annotate",
                        "returncode": 0,
                        "board_path": str(board_path),
                        "base_slug": base_slug,
                    }
                )
            else:
                cmds.append(
                    {
                        "step": "rule_c_board_annotate",
                        "returncode": 0,
                        "board_path": str(board_path),
                        "base_slug": base_slug,
                        "note": "no matching board entry — progress recorded in sidecar only",
                    }
                )
        except (OSError, json.JSONDecodeError) as e:
            cmds.append(
                {
                    "step": "rule_c_board_annotate",
                    "returncode": -1,
                    "error": f"{type(e).__name__}: {e}",
                    "board_path": str(board_path),
                }
            )

    # 4) verdict-corpus ingest (non-fatal)
    cmds.append(_verdict_corpus_ingest(gate_path, dry_run=dry_run))

    return 0, cmds


def _reject_chain(
    slug: str,
    gate_path: Path,
    report: Path | None,
    py: str,
    dry_run: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Run the reject chain. Returns (exit_code, commands_run).

    NOTE: this script does NOT auto-revert the worker's source changes. That is
    a separate, scope-sensitive action - the worker / Codex must run
    `git checkout -- corpus/programbench/per_tool_overrides/<slug>/` manually
    after reviewing the diff. The reject lesson written here cites the rule.
    """
    cmds: list[dict[str, Any]] = []
    lesson_cmd = [py, str(SCRIPTS["lesson"]), slug, str(gate_path)]
    if report:
        lesson_cmd += ["--report", str(report)]
    r = _run(lesson_cmd, dry_run=dry_run)
    cmds.append({"step": "lesson", **r})
    if r["returncode"] != 0:
        return 2, cmds
    hint_cmd = [
        py,
        str(SCRIPTS["hint_audit"]),
        "--slug",
        slug,
        "--input",
        str(gate_path),
        "--write-note",
    ]
    r = _run(hint_cmd, dry_run=dry_run)
    cmds.append({"step": "hint_audit", **r})
    if r["returncode"] != 0:
        return 2, cmds
    return 1, cmds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument("gate_result", type=Path, help="path to gate_result.json")
    ap.add_argument(
        "--run-root",
        type=Path,
        default=None,
        help="candidate run root (required for accept; passed to register as --promote-run-root)",
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=None,
        help="optional REPORT.md to embed verbatim in the lesson",
    )
    ap.add_argument(
        "--refresh-board",
        action="store_true",
        help="on accept, also invoke pb_score_audit.py (via register --refresh-board)",
    )
    ap.add_argument(
        "--refresh-rag",
        action="store_true",
        help="on accept, also invoke pb_refresh_rag_after_accept.py --require-accepted-run",
    )
    ap.add_argument(
        "--python", default=sys.executable, help="Python interpreter for sub-script invocations"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="print intended commands and write no files"
    )
    args = ap.parse_args()

    # ----- validation -----
    if not args.slug or "__" not in args.slug:
        sys.stderr.write(f"ERROR: bad slug {args.slug!r} (expected owner__repo.hash)\n")
        return 3

    gate = _read_gate(args.gate_result)
    if gate is None:
        sys.stderr.write(f"ERROR: could not read gate_result.json: {args.gate_result}\n")
        return 3

    decision = _safe_decision(gate)
    if decision not in ("accept", "reject"):
        sys.stderr.write(f"ERROR: gate decision must be 'accept' or 'reject'; got {decision!r}\n")
        return 3

    # Validation specific to accept chain
    if decision == "accept":
        if args.run_root is None:
            # Fall back to the gate's recorded candidate_run_root
            recorded = gate.get("candidate_run_root")
            if not recorded:
                sys.stderr.write(
                    "ERROR: accept requires --run-root (gate_result.json had no "
                    "candidate_run_root either)\n"
                )
                return 3
            args.run_root = Path(recorded)

    # ----- run chain -----
    started = _utc_now()
    decision_rule = _safe_decision_rule(gate)
    if decision == "accept":
        if decision_rule == "A":
            rc, cmds = _accept_chain(
                slug=args.slug,
                gate_path=args.gate_result,
                run_root=args.run_root,
                report=args.report,
                refresh_board=args.refresh_board,
                refresh_rag=args.refresh_rag,
                py=args.python,
                dry_run=args.dry_run,
            )
        elif decision_rule == "B":
            rc, cmds = _rule_b_sidecar_chain(
                slug=args.slug,
                gate_path=args.gate_result,
                gate=gate,
                report=args.report,
                py=args.python,
                dry_run=args.dry_run,
            )
        elif decision_rule == "C":
            rc, cmds = _rule_c_progress_chain(
                slug=args.slug,
                gate_path=args.gate_result,
                gate=gate,
                report=args.report,
                py=args.python,
                dry_run=args.dry_run,
            )
        else:
            sys.stderr.write(
                "ERROR: gate decision='accept' but decision_rule is missing or unrecognized. "
                "Refusing to apply to avoid contaminating the official ledger.\n"
            )
            return 3
    else:
        rc, cmds = _reject_chain(
            slug=args.slug,
            gate_path=args.gate_result,
            report=args.report,
            py=args.python,
            dry_run=args.dry_run,
        )
    finished = _utc_now()

    payload = {
        "slug": args.slug,
        "gate_result_path": str(args.gate_result),
        "decision": decision,
        "decision_rule": decision_rule,
        "exit_code": rc,
        "started": started,
        "finished": finished,
        "flags": {
            "refresh_board": bool(args.refresh_board),
            "refresh_rag": bool(args.refresh_rag),
            "report": str(args.report) if args.report else None,
            "run_root": str(args.run_root) if args.run_root else None,
            "dry_run": bool(args.dry_run),
        },
        "commands": cmds,
        "note": (
            "Reject chain wrote the rejected lesson; it does NOT auto-revert the "
            "worker's source changes. Run `git checkout -- "
            "corpus/programbench/per_tool_overrides/<slug>/` manually after reviewing the diff."
            if decision == "reject"
            else (
                "Rule B sidecar accept: pure-improvement on shifted runnable surface. "
                "NOT in accepted_runs.jsonl. Recorded in rule_b_promotions.jsonl + "
                "lock_board['rule_b_discovery']. Needs clean Rule A re-gate before official."
                if decision_rule == "B"
                else (
                    "Rule C progress accept: net-positive improvement with regressions. "
                    "NOT in accepted_runs.jsonl. Recorded in rule_c_progress.jsonl + "
                    "lock_board['rule_c_progress']. Fix regressions before Rule A/B eligibility."
                    if decision_rule == "C"
                    else None
                )
            )
        ),
    }

    out_path = _write_apply_result(args.slug, payload, dry_run=args.dry_run)

    # Console summary
    def _cmd_summary(c: dict[str, Any]) -> str:
        if "cmd" in c:
            return " ".join(str(x) for x in c["cmd"])
        if "path" in c:
            return f"write -> {c['path']}"
        if "board_path" in c:
            return f"annotate -> {c['board_path']}"
        return c.get("step", "")

    print(
        json.dumps(
            {
                "slug": args.slug,
                "decision": decision,
                "decision_rule": decision_rule,
                "exit_code": rc,
                "dry_run": bool(args.dry_run),
                "apply_gate_result_path": str(out_path),
                "commands_run": [
                    {"step": c["step"], "rc": c.get("returncode"), "cmd": _cmd_summary(c)}
                    for c in cmds
                ],
            },
            indent=2,
        )
    )

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
