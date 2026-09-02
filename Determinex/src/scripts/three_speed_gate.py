"""scripts/three_speed_gate.py — three-speed eval escalation gate.

The cockpit's load-bearing "stop blind waiting" piece. Before a proposed
scaffold patch goes through the full 115-tool eval (~6 hours), it passes
through two cheaper gates that catch the obvious failures in seconds-to-minutes.

  micro  ─ 20 deterministic behavioral tests for the 8 universal CLI patterns.
           Runs against an in-memory subprocess of the scaffold's executable.
           Cost: ~5 seconds total. Verdict: does the scaffold behave at all?

  shard  ─ 5 representative real tools eval'd via the official harness.
           Cost: ~10-15 minutes wall (4 parallel workers). Verdict: does the
           patch lift on real tools, or is it micro-only?

  full   ─ all 115 in-scope residual tools. Cost: ~3-6 hours wall.
           Verdict: ship-it or fall-back.

Each gate has a pass threshold. A patch must pass strictly LOWER gates before
the next one runs. If micro fails, full doesn't burn a worker for 6 hours.

The gate writes ledger events at every transition so the cockpit shows the
escalation path live.

CLI:
    # Run only micro against a scaffold dir's executable
    python scripts/three_speed_gate.py --gate micro --executable /path/to/executable

    # Run micro then shard. Shard auto-runs only if micro passes.
    python scripts/three_speed_gate.py --gate up-to-shard \\
        --scaffold-root T:/determinex-programbench/mass_run_v2_iter1 \\
        --shard-tools agourlay__zip-password-finder.704700d psampaz__go-mod-outdated.bb79367 ...

    # Full escalation chain (micro -> shard -> full)
    python scripts/three_speed_gate.py --gate full \\
        --scaffold-root T:/determinex-programbench/mass_run_v2_iter1 \\
        --run-id mass_run_v2_iter1 \\
        --shard-tools <5-tool-list> \\
        --pb-dir T:/Dev/ProgramBench

The gate does NOT generate patches — it validates patches another loop produced.
Future advisor->patch-generator wiring calls this gate as its safety belt.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
from programbench_resource_guard import (  # type: ignore[import-not-found]
    build_eval_cmd,
    describe_policy,
)
from run_ledger import LedgerEvent, append_event  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Micro tests — 20 deterministic behavioral checks for the 8 universal patterns
# ---------------------------------------------------------------------------


@dataclass
class MicroCase:
    """One micro test: invoke the executable with these args/stdin and assert."""

    name: str
    family: str  # the universal CLI pattern this covers
    argv: list[str]  # args after the executable
    stdin: bytes = b""
    # Assertions: each is one of
    #   ("rc",         expected_int)
    #   ("rc_in",      [1, 2])
    #   ("stdout_contains", "substr")
    #   ("stderr_contains", "substr")
    #   ("stdout_empty",  None)
    #   ("stderr_empty",  None)
    assertions: list[tuple[str, object]] = field(default_factory=list)


MICRO_CASES: list[MicroCase] = [
    # Pattern 3: --help on stdout, exit 0
    MicroCase(
        "help_long_exits_zero",
        "help",
        argv=["--help"],
        assertions=[("rc", 0), ("stdout_contains", "sage")],
    ),
    MicroCase("help_short_exits_zero", "help", argv=["-h"], assertions=[("rc", 0)]),
    # Pattern 7: --version on stdout, exit 0
    MicroCase("version_long_exits_zero", "version", argv=["--version"], assertions=[("rc", 0)]),
    MicroCase("version_short_exits_zero", "version", argv=["-V"], assertions=[("rc", 0)]),
    # Pattern 6 (iter-1 patch target): unknown flag -> clap wording, rc=1
    MicroCase(
        "unknown_long_flag_clap",
        "rc_2_unknown_option",
        argv=["--does-not-exist"],
        assertions=[("rc", 1), ("stderr_contains", "unexpected argument")],
    ),
    MicroCase(
        "unknown_short_flag_clap",
        "rc_2_unknown_option",
        argv=["-Z"],
        assertions=[("rc", 1), ("stderr_contains", "unexpected argument")],
    ),
    MicroCase(
        "unknown_eqform_flag_clap",
        "rc_2_unknown_option",
        argv=["--foo=bar"],
        assertions=[("rc", 1), ("stderr_contains", "unexpected argument")],
    ),
    MicroCase(
        "unknown_flag_writes_usage",
        "rc_2_unknown_option",
        argv=["--nope"],
        assertions=[("rc", 1), ("stderr_contains", "Usage")],
    ),
    # Pattern 4: empty stdin -> exit 0, no output
    MicroCase(
        "empty_stdin_exits_zero", "empty_input", argv=["-"], stdin=b"", assertions=[("rc", 0)]
    ),
    MicroCase(
        "stdin_passthrough", "stdin_handling", argv=["-"], stdin=b"hello\n", assertions=[("rc", 0)]
    ),
    # Pattern 1/8: missing file arg or invalid value
    MicroCase(
        "nonexistent_file_rc_nonzero",
        "file_not_found",
        argv=["/tmp/_no_such_file_for_micro.xyz"],
        assertions=[("rc_in", [1, 2]), ("stderr_contains", "")],
    ),
    # Pattern 5: --no-color stub
    MicroCase(
        "no_color_accepted_no_crash",
        "no_color_negation",
        argv=["--no-color", "--help"],
        assertions=[("rc", 0)],
    ),
    MicroCase(
        "color_accepted_no_crash",
        "no_color_negation",
        argv=["--color", "--help"],
        assertions=[("rc", 0)],
    ),
    # Pattern 6 mixed: ensure --help still wins even with unknown flag after
    MicroCase("help_wins_over_garbage", "help", argv=["--help", "--bogus"], assertions=[("rc", 0)]),
    # Pattern 8: missing required arg path — scaffold treats inputs as optional
    # with stdin fallback, so bare invocation with TTY returns 0 (this matches
    # the scaffold's default; tools that REQUIRE an arg will fail their tool-
    # specific tests, not this micro).
    MicroCase(
        "bare_invocation_no_args",
        "stdin_handling",
        argv=[],
        stdin=b"",
        assertions=[("rc_in", [0, 1, 2])],
    ),
    # Output flag accepted form (cheap regression check)
    MicroCase(
        "output_flag_form_accepted",
        "output_flag",
        argv=["-o", "/tmp/_micro_out", "--help"],
        assertions=[("rc", 0)],
    ),
    # -- separator stops flag parsing
    MicroCase(
        "dashdash_stops_parsing",
        "rc_2_unknown_option",
        argv=["--", "--this-is-positional"],
        assertions=[("rc_in", [0, 1, 2])],
    ),
    # Unknown flag rc must be non-zero (broader than rc=1 in case some tools
    # legitimately want rc=2; gate only fails if zero)
    MicroCase(
        "unknown_flag_nonzero_rc",
        "rc_2_unknown_option",
        argv=["--definitely-not-a-real-flag"],
        assertions=[("rc_in", [1, 2])],
    ),
    # Version + unknown flag — version should still print
    MicroCase(
        "version_wins_over_garbage",
        "version",
        argv=["--version", "--bogus"],
        assertions=[("rc", 0)],
    ),
    # Multiple positionals don't crash (pattern 2)
    MicroCase(
        "multiple_positionals_smoke",
        "multiple_inputs",
        argv=["-", "-"],
        stdin=b"line\n",
        assertions=[("rc_in", [0, 1, 2])],
    ),
]


@dataclass
class MicroResult:
    case: MicroCase
    passed: bool
    rc: int
    stdout: bytes
    stderr: bytes
    failure_reason: str = ""


def run_micro(executable: Path, *, timeout: float = 5.0) -> list[MicroResult]:
    """Run every MicroCase against the given executable. Returns per-case results."""
    if not executable.is_file():
        raise FileNotFoundError(f"micro: executable not found: {executable}")

    out: list[MicroResult] = []
    for case in MICRO_CASES:
        try:
            proc = subprocess.run(
                [sys.executable, str(executable), *case.argv]
                if executable.suffix == ".py"
                else [str(executable), *case.argv],
                input=case.stdin,
                capture_output=True,
                timeout=timeout,
            )
            rc = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired:
            out.append(
                MicroResult(
                    case=case, passed=False, rc=-1, stdout=b"", stderr=b"", failure_reason="timeout"
                )
            )
            continue
        except Exception as e:
            out.append(
                MicroResult(
                    case=case,
                    passed=False,
                    rc=-1,
                    stdout=b"",
                    stderr=b"",
                    failure_reason=f"{type(e).__name__}: {e}",
                )
            )
            continue

        # Check assertions
        reasons: list[str] = []
        for kind, val in case.assertions:
            if kind == "rc" and rc != val:
                reasons.append(f"rc={rc} expected {val}")
            elif kind == "rc_in" and rc not in val:  # type: ignore[operator]
                reasons.append(f"rc={rc} not in {val}")
            elif kind == "stdout_contains" and isinstance(val, str) and val.encode() not in stdout:
                if val:  # skip empty contains (cheap noop)
                    reasons.append(f"stdout missing {val!r}")
            elif kind == "stderr_contains" and isinstance(val, str) and val.encode() not in stderr:
                if val:
                    reasons.append(f"stderr missing {val!r}")
            elif kind == "stdout_empty" and stdout.strip():
                reasons.append(f"stdout not empty: {stdout[:80]!r}")
            elif kind == "stderr_empty" and stderr.strip():
                reasons.append(f"stderr not empty: {stderr[:80]!r}")
        passed = len(reasons) == 0
        out.append(
            MicroResult(
                case=case,
                passed=passed,
                rc=rc,
                stdout=stdout,
                stderr=stderr,
                failure_reason="; ".join(reasons),
            )
        )
    return out


def micro_summary(results: list[MicroResult]) -> dict:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    by_family: dict[str, dict] = {}
    for r in results:
        fam = r.case.family
        by_family.setdefault(fam, {"passed": 0, "failed": 0, "total": 0})
        by_family[fam]["total"] += 1
        by_family[fam]["passed" if r.passed else "failed"] += 1
    return {
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / max(total, 1), 3),
        "by_family": by_family,
        "failures": [
            {"name": r.case.name, "family": r.case.family, "reason": r.failure_reason}
            for r in results
            if not r.passed
        ],
    }


# ---------------------------------------------------------------------------
# Shard / Full — wrappers around the existing programbench eval harness
# ---------------------------------------------------------------------------


def _eval_subset(
    *,
    scaffold_root: Path,
    pb_dir: Path,
    filter_re: str,
    timeout: int,
) -> dict:
    """Run programbench eval against a subset (regex filter) of one scaffold root.

    Returns the eval JSON dict aggregated across all matched instances.
    """
    cmd, policy = build_eval_cmd(
        scaffold_root=scaffold_root,
        filter_re=filter_re,
        force=True,
    )
    if policy.quarantined:
        return {
            "error": f"eval quarantined by resource guard: {policy.reason}",
            "policy": describe_policy(policy),
        }
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(pb_dir),
            capture_output=True,
            text=True,
            timeout=min(timeout, policy.timeout_seconds),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout}s"}

    # Aggregate the per-instance eval.json files in the matched instance dirs.
    import re as _re

    rx = _re.compile(filter_re)
    aggregate = {"instances": [], "total_passed": 0, "total_tests": 0}
    for sub in scaffold_root.iterdir():
        if not sub.is_dir() or not rx.search(sub.name):
            continue
        for ej in sub.glob("*.eval.json"):
            try:
                d = json.loads(ej.read_text(encoding="utf-8"))
            except Exception:
                continue
            results = d.get("test_results", [])
            p = sum(1 for r in results if r.get("status") == "passed")
            t = p + sum(1 for r in results if r.get("status") == "failure")
            aggregate["instances"].append(
                {
                    "instance_id": sub.name,
                    "passed": p,
                    "total": t,
                    "score": round(100 * p / max(t, 1), 1),
                }
            )
            aggregate["total_passed"] += p
            aggregate["total_tests"] += t
    aggregate["aggregate_score"] = round(
        100 * aggregate["total_passed"] / max(aggregate["total_tests"], 1), 1
    )
    aggregate["stdout_tail"] = (proc.stdout or "")[-1500:]
    aggregate["stderr_tail"] = (proc.stderr or "")[-1500:]
    return aggregate


# ---------------------------------------------------------------------------
# Gate driver — runs the chain
# ---------------------------------------------------------------------------

GATE_MICRO_PASS_RATE = 0.85  # 17/20 by default

# Iter-1 lesson 2026-05-14: aggregate score on the shard isn't enough — the
# patch must move multiple tools (so we don't burn 6h on a one-tool fluke) and
# must not regress any tool. The rule:
#
#     PASS shard if (improved_tools >= 3) OR (avg_delta_pp >= +2.0)
#                                  AND regressed_tools == 0
#
# If no baseline is supplied (`baseline_root` is None) the gate falls back to
# absolute-score behavior (legacy) — useful for the first-ever shard.
GATE_SHARD_MIN_IMPROVED_TOOLS = 3
GATE_SHARD_MIN_AVG_DELTA_PP = 2.0
GATE_SHARD_REGRESSION_TOLERANCE_PP = 0.0  # any negative delta is a regression
GATE_SHARD_LEGACY_FLOOR_PP = 1.0  # used only when no baseline supplied


def _per_tool_baseline_scores(baseline_root: Path, shard_tools: list[str]) -> dict[str, float]:
    """Return {instance_id: score} for the shard tools from baseline_root's eval JSONs."""
    out: dict[str, float] = {}
    for iid in shard_tools:
        ej = baseline_root / iid / f"{iid}.eval.json"
        if not ej.is_file():
            continue
        try:
            d = json.loads(ej.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tr = d.get("test_results", []) or []
        if not tr:
            out[iid] = 0.0
            continue
        passed = sum(1 for t in tr if t.get("status") == "passed")
        out[iid] = round(100.0 * passed / len(tr), 2)
    return out


def _evaluate_shard_verdict(
    *,
    shard_result: dict,
    baseline_scores: dict[str, float],
) -> tuple[bool, dict]:
    """Apply iter-1 shard rule: ≥3 tools lift OR ≥+2pp avg, with zero regressions.

    If baseline_scores is empty, falls back to the legacy aggregate-floor rule.
    """
    instances = shard_result.get("instances", []) or []
    if not baseline_scores:
        agg = shard_result.get("aggregate_score", 0.0)
        return (
            agg >= GATE_SHARD_LEGACY_FLOOR_PP,
            {
                "rule": "legacy_aggregate_floor",
                "aggregate_score": agg,
                "threshold_pp": GATE_SHARD_LEGACY_FLOOR_PP,
            },
        )
    deltas: list[tuple[str, float, float, float]] = []  # (iid, base, iter, delta)
    for inst in instances:
        iid = inst.get("instance_id")
        if iid is None:
            continue
        base = baseline_scores.get(iid)
        if base is None:
            continue
        deltas.append((iid, base, inst["score"], round(inst["score"] - base, 2)))
    improved = [d for d in deltas if d[3] > 0]
    regressed = [d for d in deltas if d[3] < -GATE_SHARD_REGRESSION_TOLERANCE_PP]
    avg_delta = round(sum(d[3] for d in deltas) / max(len(deltas), 1), 2) if deltas else 0.0
    rule_meets = (
        len(improved) >= GATE_SHARD_MIN_IMPROVED_TOOLS or avg_delta >= GATE_SHARD_MIN_AVG_DELTA_PP
    )
    passed = rule_meets and not regressed
    return (
        passed,
        {
            "rule": "iter1_lesson_3of5_or_2pp_no_regression",
            "deltas": [{"iid": d[0], "base": d[1], "iter": d[2], "delta_pp": d[3]} for d in deltas],
            "n_improved": len(improved),
            "n_regressed": len(regressed),
            "avg_delta_pp": avg_delta,
            "threshold_improved": GATE_SHARD_MIN_IMPROVED_TOOLS,
            "threshold_avg_pp": GATE_SHARD_MIN_AVG_DELTA_PP,
        },
    )


def run_gate(
    *,
    gate: str,
    executable: Path | None = None,
    scaffold_root: Path | None = None,
    shard_tools: list[str] | None = None,
    run_id: str = "gate_run",
    pb_dir: Path = Path("T:/Dev/ProgramBench"),
    baseline_root: Path | None = None,
) -> dict:
    """Execute the gate chain. gate ∈ {micro, up-to-shard, full}."""
    report: dict = {
        "gate": gate,
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    # ── micro ──────────────────────────────────────────────────────────
    if executable is None:
        # If scaffold_root provided, pick its first instance's executable
        if scaffold_root is None:
            raise ValueError("micro requires either --executable or --scaffold-root")
        first = next(
            (s for s in scaffold_root.iterdir() if (s / "source" / "executable").is_file()), None
        )
        if first is None:
            raise FileNotFoundError(f"no <inst>/source/executable found under {scaffold_root}")
        executable = first / "source" / "executable"

    print(f"[gate] running micro against {executable}", flush=True)
    micro_results = run_micro(executable)
    msum = micro_summary(micro_results)
    report["micro"] = msum
    append_event(
        LedgerEvent(
            run_id=run_id,
            phase="gate_micro",
            status="passed" if msum["pass_rate"] >= GATE_MICRO_PASS_RATE else "failed",
            score=msum["pass_rate"] * 100.0,
            extra={"by_family": msum["by_family"], "n_failures": len(msum["failures"])},
        )
    )

    if msum["pass_rate"] < GATE_MICRO_PASS_RATE:
        print(
            f"[gate] MICRO FAILED ({msum['passed']}/{msum['total']} = {msum['pass_rate'] * 100:.0f}%); "
            f"escalation halted. Top failures:",
            flush=True,
        )
        for f in msum["failures"][:5]:
            print(f"  - {f['name']}  ({f['family']})  {f['reason']}", flush=True)
        report["verdict"] = "halted_at_micro"
        return report

    if gate == "micro":
        report["verdict"] = "micro_passed"
        return report

    # ── shard ──────────────────────────────────────────────────────────
    if not shard_tools or not scaffold_root:
        raise ValueError("shard / full require --shard-tools and --scaffold-root")
    shard_filter = "|".join(_filter_safe(t) for t in shard_tools)
    print(f"[gate] running shard ({len(shard_tools)} tools) against {scaffold_root}", flush=True)
    shard = _eval_subset(
        scaffold_root=scaffold_root,
        pb_dir=pb_dir,
        filter_re=shard_filter,
        timeout=1800,
    )
    report["shard"] = shard
    baseline_scores = (
        _per_tool_baseline_scores(baseline_root, shard_tools) if baseline_root is not None else {}
    )
    shard_pass, verdict_detail = _evaluate_shard_verdict(
        shard_result=shard,
        baseline_scores=baseline_scores,
    )
    report["shard_verdict"] = verdict_detail
    append_event(
        LedgerEvent(
            run_id=run_id,
            phase="gate_shard",
            status="passed" if shard_pass else "failed",
            score=shard.get("aggregate_score", 0.0),
            extra={
                "instances": shard.get("instances", [])[:25],
                "verdict_detail": verdict_detail,
            },
        )
    )
    if not shard_pass:
        print(
            f"[gate] SHARD FAILED ({verdict_detail.get('rule')}): "
            f"improved={verdict_detail.get('n_improved')}, "
            f"regressed={verdict_detail.get('n_regressed')}, "
            f"avg_delta={verdict_detail.get('avg_delta_pp')}pp — full eval HALTED.",
            flush=True,
        )
        report["verdict"] = "halted_at_shard"
        return report

    if gate == "up-to-shard":
        report["verdict"] = "shard_passed"
        return report

    # ── full ───────────────────────────────────────────────────────────
    print(f"[gate] running full eval (every instance under {scaffold_root})", flush=True)
    full = _eval_subset(
        scaffold_root=scaffold_root,
        pb_dir=pb_dir,
        filter_re=".*",
        timeout=24 * 60 * 60,
    )
    report["full"] = full
    append_event(
        LedgerEvent(
            run_id=run_id,
            phase="gate_full",
            status="passed",
            score=full.get("aggregate_score", 0.0),
            extra={"n_instances": len(full.get("instances", []))},
        )
    )
    report["verdict"] = "full_passed"
    return report


def _filter_safe(s: str) -> str:
    """Escape regex metachars in instance_id for use in `--filter`."""
    import re as _re

    return _re.escape(s)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    ap = argparse.ArgumentParser(description="Three-speed eval gate (micro → shard → full)")
    ap.add_argument("--gate", choices=["micro", "up-to-shard", "full"], default="micro")
    ap.add_argument(
        "--executable",
        type=Path,
        default=None,
        help="path to a single ./executable (micro-only mode)",
    )
    ap.add_argument(
        "--scaffold-root",
        type=Path,
        default=None,
        help="directory containing per-instance scaffold dirs",
    )
    ap.add_argument(
        "--shard-tools",
        nargs="+",
        default=None,
        help="instance_ids to use as the shard subset (5 recommended)",
    )
    ap.add_argument("--run-id", default="gate_" + str(int(time.time())))
    ap.add_argument("--pb-dir", type=Path, default=Path("T:/Dev/ProgramBench"))
    ap.add_argument(
        "--baseline-root",
        type=Path,
        default=None,
        help="prior iter's scaffold root (e.g. mass_run_v2_base) — "
        "enables iter-1 lesson rule: pass shard only if ≥3/5 tools "
        "improve OR avg delta ≥ +2pp, with zero regressions",
    )
    ap.add_argument("--json", action="store_true", help="emit JSON report instead of pretty")
    args = ap.parse_args()

    report = run_gate(
        gate=args.gate,
        executable=args.executable,
        scaffold_root=args.scaffold_root,
        shard_tools=args.shard_tools,
        run_id=args.run_id,
        pb_dir=args.pb_dir,
        baseline_root=args.baseline_root,
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("verdict", "").endswith("_passed") else 1

    print()
    print(f"=== Verdict: {report.get('verdict', 'unknown')} ===")
    if "micro" in report:
        m = report["micro"]
        print(f"  micro: {m['passed']}/{m['total']} ({m['pass_rate'] * 100:.0f}%)")
    if "shard" in report:
        s = report["shard"]
        print(
            f"  shard: {len(s.get('instances', []))} tools  agg={s.get('aggregate_score', 0):.1f}%"
        )
    if "full" in report:
        f = report["full"]
        print(
            f"  full:  {len(f.get('instances', []))} tools  agg={f.get('aggregate_score', 0):.1f}%"
        )
    return 0 if report.get("verdict", "").endswith("_passed") else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
