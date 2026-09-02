#!/usr/bin/env python3
"""ProgramBench candidate gate - the single point of accept/reject for a candidate patch.

Runs the official `programbench_eval_runner.py` against a packed candidate,
parses the resulting eval JSON, compares it against a baseline eval JSON
plus a minimum-baseline floor, computes a per-test diff, and writes
`gate_result.json` next to the candidate.

This script does NOT:
- edit any source file
- create or move any submission tarball
- commit, push, or stage any change
- claim a lock (locks come from `pb_lock_archiver.py`, not from this gate)

Exit codes:
  0 = improvement and runnable stable          (accept)
      or explicit Rule-B promotion certifies a stable second eval
  1 = tie / regression / runnable unstable     (reject - revert recommended)
  2 = eval infra error (no eval JSON produced) (reject - investigate)

Usage:
    python scripts/pb_candidate_gate.py <slug> <candidate-run-root> \\
        --baseline-eval <path/to/baseline/<slug>.eval.json> \\
        --min-baseline-passed 516

The candidate-run-root is the *parent* dir holding `<slug>/submission.tar.gz`
(matches the layout produced by `pb_pack_candidate.py`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _parse_eval(eval_path: Path) -> dict[str, Any]:
    """Parse a ProgramBench eval JSON to a normalized summary dict.

    Also captures per-test failure messages so downstream signal extractors
    can mine error patterns across tools.
    """
    if not eval_path.is_file():
        return {"error": f"eval JSON not found: {eval_path}", "eval_path": str(eval_path)}
    try:
        data = json.loads(eval_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return {
            "error": f"failed to parse eval JSON: {type(e).__name__}: {e}",
            "eval_path": str(eval_path),
        }
    if data.get("error_code"):
        return {
            "error": f"eval reported error_code={data['error_code']}",
            "eval_path": str(eval_path),
            "details": str(data.get("error_details", ""))[:300],
        }

    test_results = data.get("test_results") or []
    counts: Counter[str] = Counter(str(t.get("status", "?")) for t in test_results)
    passed = counts.get("passed", 0)
    failed = counts.get("failure", 0) + counts.get("failed", 0)
    skipped = counts.get("skipped", 0)
    not_run = counts.get("not_run", 0)
    errored = counts.get("error", 0)
    runnable = passed + failed + errored

    per_test = {
        str(t.get("name", "")): str(t.get("status", "")) for t in test_results if t.get("name")
    }

    # Capture failure messages for the signal corpus.
    fail_messages: dict[str, str] = {}
    for t in test_results:
        name = str(t.get("name", ""))
        status = str(t.get("status", ""))
        if name and status in ("failure", "failed", "error"):
            msg = (t.get("extra") or {}).get("message", "")
            if msg:
                # Truncate per-message; the corpus indexer needs structure not novels.
                fail_messages[name] = str(msg)[:500]

    return {
        "eval_path": str(eval_path),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "not_run": not_run,
        "errored": errored,
        "runnable": runnable,
        "total": len(test_results),
        "executable_hash": (data.get("executable_hash") or "")[:64],
        "per_test": per_test,
        "fail_messages": fail_messages,
    }


def _write_failure_signal(
    slug: str,
    candidate: dict[str, Any],
    diff: dict[str, list[str]],
    decision: str,
) -> Path | None:
    """Append failure-signal records to the cross-tool corpus.

    Schema (one JSON line per failing test):
      {
        "slug": "<tool slug>",
        "test_name": "tests.test_x.test_y",
        "module": "tests.test_x",
        "status": "failure",
        "message_head": "first 500 chars of pytest assertion message",
        "remained_failing_after_accept": bool,
        "decision": "accept" | "reject",
        "captured_at": "2026-05-22T...",
      }

    Future scaffold generators can RAG-query this corpus to see HOW similar
    tests fail across tools and apply known fixes.
    """
    corpus_path = ROOT / "logs" / "programbench_factory" / "failure_signal_corpus.jsonl"
    corpus_path.parent.mkdir(parents=True, exist_ok=True)

    # Set of tests that were already failing on the candidate (the residual after this iteration).
    fail_msgs = candidate.get("fail_messages") or {}
    per_test = candidate.get("per_test") or {}
    residual = sorted(
        name for name, status in per_test.items() if status in ("failure", "failed", "error")
    )

    if not residual:
        return None

    newly_failing_set = set(diff.get("newly_failing") or [])
    newly_passing_set = set(diff.get("newly_passing") or [])
    # Caller passed regression_classes via the diff dict; pull it out if present.
    reg_classes = diff.get("regression_classes") or {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    written = 0
    try:
        with corpus_path.open("a", encoding="utf-8") as fh:
            for name in residual:
                is_regression = name in newly_failing_set
                # Classify on-the-fly for residuals that aren't regressions
                # (previously-failing tests still carry value: they're the
                # backlog of bugs the candidate hasn't fixed yet).
                if is_regression and name in reg_classes:
                    cls = reg_classes[name]
                else:
                    cls = _classify_regression(fail_msgs.get(name, ""))
                rec = {
                    "slug": slug,
                    "test_name": name,
                    "module": name.rsplit(".", 1)[0] if "." in name else name,
                    "status": per_test.get(name, "failure"),
                    "message_head": fail_msgs.get(name, "")[:500],
                    "regression": is_regression,
                    "previously_failing": not is_regression,
                    "regression_class": cls.get("regression_class", "unknown"),
                    "regression_hint": cls.get("regression_hint", ""),
                    "decision": decision,
                    "captured_at": now,
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                written += 1
            # Also append a per-tool summary row so the corpus knows what was won.
            summary = {
                "slug": slug,
                "kind": "summary",
                "decision": decision,
                "passed": candidate.get("passed", 0),
                "runnable": candidate.get("runnable", 0),
                "newly_passing_count": len(newly_passing_set),
                "newly_failing_count": len(newly_failing_set),
                "residual_failure_count": len(residual),
                "regression_class_counts": diff.get("regression_class_counts", {}),
                "captured_at": now,
            }
            fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return corpus_path if written else None


def _diff_per_test(
    baseline_per: dict[str, str], candidate_per: dict[str, str]
) -> dict[str, list[str]]:
    """Compute newly_passing and newly_failing relative to baseline."""
    newly_passing: list[str] = []
    newly_failing: list[str] = []
    all_names = set(baseline_per) | set(candidate_per)
    for name in all_names:
        b = baseline_per.get(name, "MISSING")
        c = candidate_per.get(name, "MISSING")
        if b == c:
            continue
        if c == "passed" and b in ("failure", "failed"):
            newly_passing.append(name)
        elif b == "passed" and c in ("failure", "failed"):
            newly_failing.append(name)
    return {"newly_passing": sorted(newly_passing), "newly_failing": sorted(newly_failing)}


# Regression class taxonomy. The classifier reads the candidate's failure
# message for each newly-failing test and bins it into one of these buckets
# so cortex-pull can prioritize: feature_gap is "accept as binary limitation",
# behavioral is "real bug worth fixing", panic is "runtime crash, urgent".
_RE_FEATURE_GAP = (
    re.compile(r"\bflag provided but not defined\b", re.IGNORECASE),
    re.compile(r"\bunknown (?:flag|option)\b", re.IGNORECASE),
    re.compile(r"\bunrecognized (?:argument|option|flag)\b", re.IGNORECASE),
    re.compile(r"\bno such option\b", re.IGNORECASE),
    re.compile(r"\binvalid option\b", re.IGNORECASE),
    re.compile(r"\bFound argument .* which wasn't expected\b", re.IGNORECASE),
    re.compile(r"\bunexpected argument\b", re.IGNORECASE),
    re.compile(r"\bcommand not found\b", re.IGNORECASE),
    re.compile(
        r"^[^:]+:\s+(?:invalid|unrecognized|unknown) (?:argument|option|flag)",
        re.IGNORECASE | re.MULTILINE,
    ),
)
_RE_PANIC = (
    re.compile(r"\bpanic:\s", re.IGNORECASE),
    re.compile(r"\bruntime error\b", re.IGNORECASE),
    re.compile(r"\bSegmentation fault\b"),
    re.compile(r"\baborted\s*\(core dumped\)", re.IGNORECASE),
    re.compile(r"\bgoroutine \d+ \[running\]", re.IGNORECASE),
    re.compile(r"\bthread '.*' panicked\b"),
    re.compile(r"\bUnicodeDecodeError\b"),
)
_RE_MISSING_BIN = (
    re.compile(r"\b/bin/bash\^M\b"),
    re.compile(r"\bbad interpreter\b"),
    re.compile(r"\bexec: .*: not found\b"),
    re.compile(r"\bNo such file or directory\b"),
)


def _classify_regression(failure_message: str) -> dict[str, str]:
    """Classify a regression message into a stable taxonomy.

    Returns: {"regression_class": <bucket>, "regression_hint": <short text>}.

    Buckets:
      - feature_gap        — test wants a flag/option the binary doesn't have.
                              The upstream binary is honestly correct; the test
                              suite expects a newer/extended build. Recoverable
                              via newer binary or thin Python wrapper.
      - runtime_panic      — binary crashed (segfault, panic, goroutine trace).
                              Real bug; investigate upstream version.
      - missing_executable — wrapper-level failure (bad interpreter, command not
                              found). Scaffold infrastructure bug, not the binary.
      - behavioral         — output mismatch; binary ran and produced something
                              that didn't match the expected golden. Real
                              divergence between upstream behavior and test
                              fixture. Worth patching when small enough.
      - unknown            — couldn't classify automatically; needs human read.
    """
    if not failure_message:
        return {"regression_class": "unknown", "regression_hint": ""}
    msg = failure_message[:1500]
    for pat in _RE_MISSING_BIN:
        m = pat.search(msg)
        if m:
            return {"regression_class": "missing_executable", "regression_hint": m.group(0)[:120]}
    for pat in _RE_PANIC:
        m = pat.search(msg)
        if m:
            return {"regression_class": "runtime_panic", "regression_hint": m.group(0)[:120]}
    for pat in _RE_FEATURE_GAP:
        m = pat.search(msg)
        if m:
            return {"regression_class": "feature_gap", "regression_hint": m.group(0)[:120]}
    if "AssertionError" in msg or "assert " in msg:
        # Try to lift the most useful one-liner: the actual mismatch.
        for line in msg.splitlines():
            line = line.strip()
            if line.startswith("AssertionError") or line.startswith("assert "):
                return {"regression_class": "behavioral", "regression_hint": line[:120]}
        return {"regression_class": "behavioral", "regression_hint": "AssertionError"}
    return {"regression_class": "unknown", "regression_hint": ""}


def _find_candidate_eval(inst_dir: Path) -> Path | None:
    """Return the candidate eval JSON path inside <inst_dir>, if present."""
    if not inst_dir.is_dir():
        return None
    for p in inst_dir.glob("*.eval.json"):
        return p
    alt = inst_dir / "eval_report.json"
    if alt.is_file():
        return alt
    return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _run_official_eval(slug: str, run_root: Path, py: Path, log_path: Path) -> int:
    """Invoke programbench_eval_runner.py for this slug. Return its exit code.

    The runner can take a long time for tmux/TUI-heavy tools. Stream output to
    both the terminal and a persistent log file so monitors are not forced to
    infer progress from Docker state alone.
    """
    runner = ROOT / "scripts" / "programbench_eval_runner.py"
    cmd = [str(py), str(runner), slug, str(run_root), "--force"]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            header = f"[gate] starting official eval: {' '.join(cmd)}\n"
            sys.stdout.write(header)
            sys.stdout.flush()
            log.write(header)
            log.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
                log.flush()
            rc = proc.wait()
            footer = f"[gate] official eval exited rc={rc}\n"
            sys.stdout.write(footer)
            sys.stdout.flush()
            log.write(footer)
            log.flush()
            return rc
    except Exception as e:
        msg = f"runner subprocess failed: {type(e).__name__}: {e}\n"
        sys.stderr.write(msg)
        try:
            with log_path.open("a", encoding="utf-8", errors="replace") as log:
                log.write(msg)
        except Exception:
            pass
        return 2


def run_gate(
    slug: str,
    run_root: Path,
    baseline_eval: Path,
    min_baseline_passed: int,
    py: Path | None = None,
    skip_eval: bool = False,
    allow_stable_certification: bool = False,
) -> dict[str, Any]:
    """Execute the gate end to end.

    Behavior summary:
      1. (optional) run official eval via programbench_eval_runner.py
      2. parse candidate eval JSON from <run_root>/<slug>/
      3. parse baseline eval JSON
      4. compute deltas + per-test diff
      5. apply accept/reject rule
      6. write gate_result.json
      7. return the same dict that was written to disk
    """
    py = py or Path(sys.executable)
    inst_dir = run_root / slug
    out_path = run_root / "gate_result.json"
    status_path = run_root / "gate_status.json"
    log_path = run_root / "gate_eval.log"

    # Avoid monitors reading a stale gate_result.json while a long official eval
    # is still in progress. Only final accept/reject decisions belong there.
    if not skip_eval and out_path.exists():
        out_path.unlink()

    baseline = _parse_eval(baseline_eval)
    if baseline.get("error"):
        result = {
            "slug": slug,
            "decision": "reject",
            "reason": f"baseline eval JSON unreadable: {baseline['error']}",
            "exit_code": 2,
            "baseline_path": str(baseline_eval),
            "candidate_run_root": str(run_root),
        }
        _write_json(out_path, result)
        return result

    if baseline["passed"] < min_baseline_passed:
        # Caller's contract: the baseline they cited must actually have that pass count.
        result = {
            "slug": slug,
            "decision": "reject",
            "reason": (
                f"baseline {baseline['passed']} < min_baseline_passed {min_baseline_passed}. "
                "Cite a higher-scoring eval JSON or lower the floor."
            ),
            "exit_code": 2,
            "baseline": baseline,
            "candidate_run_root": str(run_root),
        }
        _write_json(out_path, result)
        return result

    # Step 1 - run eval (unless caller explicitly skipped, e.g. dry-run smoke)
    if not skip_eval:
        _write_json(
            status_path,
            {
                "slug": slug,
                "status": "running",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "run_root": str(run_root),
                "baseline_eval": str(baseline_eval),
                "min_baseline_passed": min_baseline_passed,
                "log_path": str(log_path),
                "gate_result_path": str(out_path),
            },
        )
        rc_runner = _run_official_eval(slug, run_root, py, log_path)
        _write_json(
            status_path,
            {
                "slug": slug,
                "status": "eval-finished",
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "runner_exit_code": rc_runner,
                "run_root": str(run_root),
                "log_path": str(log_path),
                "gate_result_path": str(out_path),
            },
        )
        if rc_runner not in (0,):
            # The runner is somewhat tolerant - it may emit a non-zero exit but still
            # produce an eval JSON. We continue and let JSON presence decide.
            sys.stderr.write(f"[gate] runner returned exit={rc_runner}; continuing to JSON parse\n")

    cand_path = _find_candidate_eval(inst_dir)
    if cand_path is None:
        result = {
            "slug": slug,
            "decision": "reject",
            "reason": f"no candidate eval JSON found under {inst_dir}",
            "exit_code": 2,
            "baseline": baseline,
            "candidate_run_root": str(run_root),
        }
        _write_json(out_path, result)
        return result

    candidate = _parse_eval(cand_path)
    if candidate.get("error"):
        result = {
            "slug": slug,
            "decision": "reject",
            "reason": f"candidate eval JSON unreadable: {candidate['error']}",
            "exit_code": 2,
            "baseline": baseline,
            "candidate": candidate,
            "candidate_run_root": str(run_root),
        }
        _write_json(out_path, result)
        return result

    diff = _diff_per_test(baseline["per_test"], candidate["per_test"])

    # Classify each newly_failing test for cortex-pull triage. Reads the message
    # head we captured in candidate["fail_messages"].
    cand_fail_msgs = candidate.get("fail_messages") or {}
    regression_classes: dict[str, dict[str, str]] = {}
    class_counts: Counter[str] = Counter()
    for nf in diff["newly_failing"]:
        cls = _classify_regression(cand_fail_msgs.get(nf, ""))
        regression_classes[nf] = cls
        class_counts[cls["regression_class"]] += 1

    delta = {
        "passed": candidate["passed"] - baseline["passed"],
        "runnable": candidate["runnable"] - baseline["runnable"],
        "failed": candidate["failed"] - baseline["failed"],
        "newly_passing": diff["newly_passing"],
        "newly_failing": diff["newly_failing"],
        "regression_classes": regression_classes,
        "regression_class_counts": dict(class_counts),
    }

    # Decision logic.
    #
    # Rule A (strict, ledger-grade): runnable stable + passed up + no regressions.
    #   This is what the official `accepted_runs.jsonl` + `programbench_lock_board.json`
    #   record. The measurement surface is identical to the baseline so the
    #   improvement is directly comparable. ProgramBench submission entries
    #   must be Rule A.
    #
    # Rule B (sidecar, training/discovery-grade): runnable changed but no test
    #   that USED to pass is now failing (newly_failing == []) AND passed > 0.
    #   Real work but the measurement surface differs from the baseline, so the
    #   delta can't enter the official ledger as-is. Rule B accepts go to
    #   `rule_b_promotions.jsonl` and feed the failure-signal corpus + cortex
    #   pull. They become eligible for the official ledger only after a clean
    #   Rule A re-gate against the new baseline.
    #
    # Promotion certification:
    #   Explicit Rule-B promotion mode compares the second eval against the
    #   first Rule-B eval as the new measurement surface. It can enter the
    #   Rule-A ledger only if runnable is stable, no previously-passing test
    #   regressed, and passed count is >= the Rule-B baseline.
    #
    # Reject:
    #   - passed delta <= 0 (no improvement)
    #   - newly_failing > 0 (previously-passing test regressed)
    newly_failing_count = len(diff["newly_failing"])
    if allow_stable_certification:
        if newly_failing_count > 0:
            decision = "reject"
            decision_rule = None
            reason = (
                f"{newly_failing_count} previously-passing test(s) now fail "
                f"during Rule-B promotion certification; refusing official ledger"
            )
            exit_code = 1
        elif delta["runnable"] != 0:
            decision = "reject"
            decision_rule = None
            reason = (
                f"runnable changed during Rule-B promotion certification "
                f"({baseline['runnable']} -> {candidate['runnable']}); "
                "measurement surface is still unstable"
            )
            exit_code = 1
        elif delta["passed"] < 0:
            decision = "reject"
            decision_rule = None
            reason = (
                f"passed regressed during Rule-B promotion certification "
                f"({baseline['passed']} -> {candidate['passed']}); refusing official ledger"
            )
            exit_code = 1
        else:
            decision = "accept"
            decision_rule = "A"
            reason = (
                f"Rule-B promotion certified: passed {delta['passed']:+d}, "
                f"runnable stable at {candidate['runnable']}, 0 regressions "
                "(rule A: certified shifted-surface baseline)"
            )
            exit_code = 0
    elif delta["passed"] <= 0:
        decision = "reject"
        decision_rule = None
        reason = (
            f"passed delta = {delta['passed']:+d} (baseline {baseline['passed']} -> "
            f"candidate {candidate['passed']}); requires strict improvement"
        )
        exit_code = 1
    elif newly_failing_count > 0:
        newly_passing_count = len(diff["newly_passing"])
        if newly_passing_count > newly_failing_count:
            # Rule C (progress-grade): net-positive improvement with some regressions.
            # Regressions must be fixed before the ledger can accept this — but the
            # direction is correct and the improvement is real. Goes to rule_c_progress.jsonl.
            decision = "accept"
            decision_rule = "C"
            reason = (
                f"passed {delta['passed']:+d}, runnable {delta['runnable']:+d}, "
                f"{newly_passing_count} newly-passing > {newly_failing_count} regressions "
                f"(rule C: progress-grade — fix {newly_failing_count} regression(s) "
                f"to reach rule A/B eligibility)"
            )
            exit_code = 0
        else:
            decision = "reject"
            decision_rule = None
            reason = (
                f"{newly_failing_count} previously-passing test(s) now fail "
                f"(passed {delta['passed']:+d}, runnable {delta['runnable']:+d}); "
                f"newly_passing={newly_passing_count} <= newly_failing={newly_failing_count}; "
                "net-negative or neutral — regression is disqualifying"
            )
            exit_code = 1
    elif delta["runnable"] == 0:
        decision = "accept"
        decision_rule = "A"
        reason = (
            f"passed {delta['passed']:+d}, runnable stable at {candidate['runnable']} "
            "(rule A: strict — eligible for official ledger)"
        )
        exit_code = 0
    else:
        # delta.runnable != 0 AND newly_failing == 0 AND passed up:
        # pure-improvement on a shifted surface. Real work. Goes to sidecar.
        decision = "accept"
        decision_rule = "B"
        reason = (
            f"passed {delta['passed']:+d}, runnable {delta['runnable']:+d}, "
            f"0 regressions (rule B: sidecar — eligible for rule_b_promotions.jsonl "
            f"and failure-signal corpus; NOT the official ledger until a clean "
            f"Rule A re-gate against the new baseline)"
        )
        exit_code = 0

    # Strip per_test from the dump (it's the bulk; deltas are what matter)
    baseline_dump = {k: v for k, v in baseline.items() if k != "per_test"}
    candidate_dump = {k: v for k, v in candidate.items() if k != "per_test"}

    # Capture failure signal into the cross-tool corpus (runs on every gate,
    # regardless of accept/reject — failures are signal either way).
    try:
        signal_path = _write_failure_signal(slug, candidate, diff, decision)
    except Exception as sig_err:
        signal_path = None
        sys.stderr.write(f"[gate] failure-signal extractor failed: {sig_err}\n")

    result = {
        "slug": slug,
        "candidate_run_root": str(run_root),
        "baseline_path": str(baseline_eval),
        "min_baseline_passed": min_baseline_passed,
        "baseline": baseline_dump,
        "candidate": candidate_dump,
        "delta": delta,
        "decision": decision,
        "decision_rule": decision_rule,  # "A" (strict/ledger), "B" (sidecar), "C" (progress/fix-regressions), or None on reject
        "reason": reason,
        "exit_code": exit_code,
        "failure_signal_corpus": str(signal_path) if signal_path else None,
        "promotion_certification": bool(allow_stable_certification),
    }
    _write_json(out_path, result)
    if status_path.exists():
        _write_json(
            status_path,
            {
                "slug": slug,
                "status": "gate-finished",
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "decision": decision,
                "reason": reason,
                "exit_code": exit_code,
                "gate_result_path": str(out_path),
                "log_path": str(log_path),
            },
        )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument(
        "run_root",
        type=Path,
        help="parent dir holding <slug>/submission.tar.gz (output of pb_pack_candidate.py)",
    )
    ap.add_argument(
        "--baseline-eval",
        type=Path,
        required=True,
        help="path to the baseline eval JSON to compare against",
    )
    ap.add_argument(
        "--min-baseline-passed",
        type=int,
        required=True,
        help="minimum acceptable baseline passed count (sanity check)",
    )
    ap.add_argument(
        "--python",
        type=Path,
        default=None,
        help="Python interpreter for the eval runner (default: current sys.executable)",
    )
    ap.add_argument(
        "--skip-eval",
        action="store_true",
        help="skip running the official eval (use existing candidate eval JSON for smoke/dry-run)",
    )
    ap.add_argument(
        "--allow-stable-certification",
        action="store_true",
        help="Rule-B promotion mode: accept a stable second eval with passed >= baseline",
    )
    args = ap.parse_args()

    run_root = args.run_root if args.run_root.is_absolute() else ROOT / args.run_root

    result = run_gate(
        slug=args.slug,
        run_root=run_root,
        baseline_eval=args.baseline_eval,
        min_baseline_passed=args.min_baseline_passed,
        py=args.python,
        skip_eval=args.skip_eval,
        allow_stable_certification=args.allow_stable_certification,
    )

    print(
        json.dumps(
            {
                "decision": result["decision"],
                "decision_rule": result.get("decision_rule"),
                "reason": result["reason"],
                "exit_code": result["exit_code"],
                "baseline_passed": result.get("baseline", {}).get("passed"),
                "candidate_passed": result.get("candidate", {}).get("passed"),
                "runnable_delta": result.get("delta", {}).get("runnable")
                if "delta" in result
                else None,
                "gate_result_path": str(run_root / "gate_result.json"),
            },
            indent=2,
        )
    )

    return int(result.get("exit_code", 2))


if __name__ == "__main__":
    raise SystemExit(main())
