#!/usr/bin/env python3
"""
determinex_route_ab.py -- measure what the Model Router actually saves
=====================================================================
Runs the SAME specs twice and compares:

  arm "always"  -- one model does every step (the always-frontier baseline)
  arm "routed"  -- DETERMINEX_ROUTE=1 with a ladder, cheapest rung first

The comparison that matters is routed vs ALWAYS-FRONTIER, not routed vs
route-off. Route-off uses the configured local builder, which is free, so
"routing vs route-off" would show routing costing MORE and answer nothing. The
claim being tested is "don't send every step to the expensive model", so the
baseline has to be the expensive model doing every step.

WHAT IT REPORTS, AND WHY THE ESCALATION RATE IS FIRST
-----------------------------------------------------
A router that never escalates reports 100% savings, which is not a result -- it
means the task set was too easy to exercise the mechanism. So the escalation
rate is printed before any cost figure: if it is 0, the cost number is
meaningless and this script says so rather than letting it read as a win.

Real spend is read from logs/api_ledger/providers.jsonl (the ledger every cloud
call already appends to), not from the router's own relative `est_cost`. With an
all-local ladder both arms are genuinely $0 and the script reports that plainly
instead of manufacturing a percentage.

    python scripts/determinex_route_ab.py \
        --specs a.md,b.md \
        --baseline determinex/qwen7b \
        --ladder determinex/engineer,determinex/qwen7b
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_HIVE = _ROOT / "scripts" / "determinex_hive.py"
_LEDGER = _ROOT / "logs" / "api_ledger" / "providers.jsonl"
_ROUTES = _ROOT / "logs" / "api_ledger" / "route_decisions.jsonl"

_SESSION_RE = re.compile(r"Session created:\s*([0-9a-f-]{36})")
_STEPS_RE = re.compile(r"Steps:\s*(\d+)/(\d+)\s*complete,\s*(\d+)\s*failed")


@dataclass
class RunResult:
    spec: str
    session_id: str = ""
    steps_complete: int = 0
    steps_total: int = 0
    steps_failed: int = 0
    seconds: float = 0.0
    error: str = ""


@dataclass
class ArmResult:
    name: str
    runs: list[RunResult] = field(default_factory=list)
    usd: float = 0.0  # from the session manifests (the hive's accounting)
    ledger_usd: float = 0.0  # from providers.jsonl, as a cross-check
    escalations: int = 0
    route_rows: list[dict] = field(default_factory=list)

    @property
    def solved(self) -> int:
        return sum(1 for r in self.runs if r.steps_total and r.steps_complete == r.steps_total)

    @property
    def seconds(self) -> float:
        return sum(r.seconds for r in self.runs)


def _ledger_usd() -> float:
    """Total est_usd in the spend ledger right now. The A/B measures the DELTA."""
    if not _LEDGER.is_file():
        return 0.0
    total = 0.0
    for line in _LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            total += float(json.loads(line).get("est_usd", 0) or 0)
        except Exception:
            continue
    return total


def _session_usd(session_id: str) -> float:
    """Cost as the HIVE recorded it, from the session manifest.

    The first paid run of this harness reported $0 for both arms while the baseline
    arm had demonstrably called DeepSeek on every step. Cause: it read only
    logs/api_ledger/providers.jsonl, which determinex_providers._ledger_append writes
    -- and the hive does not go through that lane. It calls litellm via
    hive.api_client.api_call and accounts through record_api_call_cost, which lands in
    the manifest's api_cost_usd. Reading the wrong ledger produced a confident $0.
    """
    mp = _ROOT / "sessions" / session_id / "manifest.json"
    if not mp.is_file():
        return 0.0
    try:
        return float(json.loads(mp.read_text(encoding="utf-8")).get("api_cost_usd", 0) or 0)
    except Exception:
        return 0.0


def _route_rows_since(offset: int) -> list[dict]:
    if not _ROUTES.is_file():
        return []
    lines = _ROUTES.read_text(encoding="utf-8", errors="replace").splitlines()[offset:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _route_line_count() -> int:
    if not _ROUTES.is_file():
        return 0
    return len(_ROUTES.read_text(encoding="utf-8", errors="replace").splitlines())


def _run(cmd: list[str], env: dict, timeout: int) -> str:
    proc = subprocess.run(
        [sys.executable, *cmd],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return (proc.stdout or "") + (proc.stderr or "")


def run_one(spec: Path, env: dict, timeout: int, lang: str) -> RunResult:
    res = RunResult(spec=spec.name)
    t0 = time.time()
    try:
        out = _run([str(_HIVE), "new-session", "--spec", str(spec), "--lang", lang], env, timeout)
        m = _SESSION_RE.search(out)
        if not m:
            res.error = "no session id in new-session output"
            return res
        res.session_id = m.group(1)

        out = _run([str(_HIVE), "generate-dag", "--session", res.session_id], env, timeout)
        if "DAG generated" not in out:
            res.error = "generate-dag did not report a DAG"
            return res

        out = _run([str(_HIVE), "run-session", "--session", res.session_id], env, timeout)
        s = _STEPS_RE.search(out)
        if s:
            res.steps_complete, res.steps_total, res.steps_failed = (
                int(s.group(1)),
                int(s.group(2)),
                int(s.group(3)),
            )
        else:
            res.error = "run-session did not report a step tally"
    except subprocess.TimeoutExpired:
        res.error = f"timed out after {timeout}s"
    except Exception as e:  # a broken run is data, not a crash
        res.error = f"{type(e).__name__}: {e}"
    finally:
        res.seconds = round(time.time() - t0, 1)
    return res


def run_arm(name: str, specs: list[Path], env_extra: dict, timeout: int, lang: str) -> ArmResult:
    env = {**os.environ, **env_extra}
    # Each arm starts from a clean routing state so a stale variable from the caller's shell
    # cannot silently contaminate the baseline.
    #
    # Popping is no longer sufficient on its own to mean "off": `route_decision` derives a
    # default from the hardware tier when DETERMINEX_ROUTE is unset. So every arm must state
    # its routing intent in `env_extra` -- absence is a question now, not an answer.
    for var in ("DETERMINEX_ROUTE", "DETERMINEX_ROUTE_LADDER", "DETERMINEX_ROLE_BUILDER"):
        if var not in env_extra:
            env.pop(var, None)
    if "DETERMINEX_ROUTE" not in env_extra:
        raise ValueError(
            f"arm {name!r} does not state DETERMINEX_ROUTE. Since the default is derived from "
            "the hardware tier, an unset variable can mean ON -- so an arm that leaves it out "
            "is not measuring what its name says."
        )

    usd0, routes0 = _ledger_usd(), _route_line_count()
    arm = ArmResult(name=name)
    for spec in specs:
        print(f"  [{name}] {spec.name} ...", flush=True)
        r = run_one(spec, env, timeout, lang)
        arm.runs.append(r)
        status = r.error or f"{r.steps_complete}/{r.steps_total} complete"
        print(f"  [{name}] {spec.name}: {status} ({r.seconds}s)", flush=True)
    # The hive's own accounting is authoritative; the providers-ledger delta is kept
    # as a cross-check because a nonzero value there would mean spend arrived by a
    # second path this harness does not model.
    arm.usd = round(sum(_session_usd(r.session_id) for r in arm.runs if r.session_id), 6)
    arm.ledger_usd = round(_ledger_usd() - usd0, 6)
    arm.route_rows = _route_rows_since(routes0)
    arm.escalations = sum(int(r.get("escalations", 0) or 0) for r in arm.route_rows)
    return arm


def report(always: ArmResult, routed: ArmResult, baseline: str, ladder: list[str]) -> dict:
    n = len(always.runs)
    print("\n" + "=" * 72)
    print("ROUTER A/B")
    print(f"  baseline (always): {baseline}")
    print(f"  routed (ladder)  : {' -> '.join(ladder)}")
    print(f"  specs            : {n}")
    print("=" * 72)

    # Escalation rate FIRST: without it, a cost number is unreadable.
    steps_routed = len(routed.route_rows)
    esc = routed.escalations
    print(f"\nescalation: {esc} escalation(s) over {steps_routed} routed step(s)")
    if steps_routed == 0:
        print("  !! routing never ran -- ladder unconfigured, or every run failed early.")
    elif esc == 0:
        print("  !! ZERO escalations: every step was cleared by the cheapest rung.")
        print("     The mechanism was therefore never exercised, so any cost delta")
        print("     below is an artefact of an easy task set, NOT a measured saving.")

    # Grouped by MODEL, not just tier. A tier histogram is blind whenever two rungs
    # share a tier -- the first real run had ladder determinex/engineer ->
    # determinex/qwen7b, both local and therefore both tier 1, so it reported
    # "tier 1=3" for a run with 2 escalations and made the escalation invisible.
    by_model: dict[str, int] = {}
    by_tier: dict[int, int] = {}
    for r in routed.route_rows:
        m = str(r.get("model_used", "?"))
        by_model[m] = by_model.get(m, 0) + 1
        t = int(r.get("tier_used", 0) or 0)
        by_tier[t] = by_tier.get(t, 0) + 1
    if by_model:
        print(
            "  steps solved per model: "
            + ", ".join(f"{m}={c}" for m, c in sorted(by_model.items()))
        )
    if len(by_tier) == 1 and len(by_model) > 1:
        print("  (every rung shares one tier, so the tier histogram cannot separate")
        print("   them -- read the per-model line above, not the tier.)")
    elif by_tier:
        print(
            "  steps solved per tier: "
            + ", ".join(f"tier {t}={c}" for t, c in sorted(by_tier.items()))
        )

    print(f"\nsolved (all steps complete): always={always.solved}/{n}  routed={routed.solved}/{n}")
    print(
        f"wall clock                 : always={always.seconds:.0f}s  routed={routed.seconds:.0f}s"
    )
    print(f"spend, hive accounting      : always=${always.usd:.6f}  routed=${routed.usd:.6f}")
    print(
        f"  (providers-ledger cross-check: always=${always.ledger_usd:.6f} "
        f"routed=${routed.ledger_usd:.6f} -- nonzero here means spend arrived by a "
        f"path this harness does not model)"
    )

    if always.usd == 0.0 and routed.usd == 0.0:
        print("\n  Both arms spent $0. That is the honest result for an all-local ladder,")
        print("  not a 100% saving: no priced model was called in either arm. A dollar")
        print("  figure needs a funded paid rung in the ladder AND in --baseline.")
        saving = None
    elif always.usd > 0:
        saving = round((always.usd - routed.usd) / always.usd * 100.0, 1)
        print(f"\n  saving: {saving}%  (${always.usd - routed.usd:.6f} of ${always.usd:.6f})")
    else:
        saving = None
        print("\n  baseline spent $0 but routed did not -- cannot express that as a saving.")

    return {
        "baseline": baseline,
        "ladder": ladder,
        "specs": n,
        "always": {
            "solved": always.solved,
            "usd": always.usd,
            "ledger_usd": always.ledger_usd,
            "seconds": always.seconds,
            "runs": [vars(r) for r in always.runs],
        },
        "routed": {
            "solved": routed.solved,
            "usd": routed.usd,
            "ledger_usd": routed.ledger_usd,
            "seconds": routed.seconds,
            "escalations": esc,
            "routed_steps": steps_routed,
            "tier_histogram": by_tier,
            "model_histogram": by_model,
            "runs": [vars(r) for r in routed.runs],
        },
        "saving_percent": saving,
        "escalation_exercised": bool(esc),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--specs", required=True, help="comma-separated spec .md paths")
    ap.add_argument(
        "--baseline",
        required=True,
        help="the model that does EVERY step in the always-frontier arm",
    )
    ap.add_argument(
        "--ladder", required=True, help="comma-separated ladder for the routed arm, cheapest first"
    )
    ap.add_argument(
        "--lang",
        default="rust",
        help="target language. Defaults to rust DELIBERATELY: for python the "
        "Compiler Oracle is `python -m compileall` -- a SYNTAX check, so "
        "any valid code passes, the cheap rung never fails, and escalation "
        "can never be exercised. cargo build type-checks for real.",
    )
    ap.add_argument("--timeout", type=int, default=1800, help="per hive command, seconds")
    ap.add_argument("--k", type=int, default=2, help="verified-search samples per rung")
    ap.add_argument(
        "--out",
        type=Path,
        help="also write the result JSON here. Prefer assurance/evidence/ "
        "over logs/: logs/ is gitignored, so an A/B result written "
        "there is not preserved as evidence and cannot be cited later.",
    )
    args = ap.parse_args()

    specs = [Path(s.strip()) for s in args.specs.split(",") if s.strip()]
    missing = [str(s) for s in specs if not s.is_file()]
    if missing:
        print(f"spec(s) not found: {missing}", file=sys.stderr)
        return 2
    ladder = [m.strip() for m in args.ladder.split(",") if m.strip()]
    if len(ladder) < 2:
        print("--ladder needs 2+ models; one rung cannot escalate", file=sys.stderr)
        return 2

    print(f"arm 1/2: always-{args.baseline} (routing OFF)")
    # DETERMINEX_ROUTE=0 explicitly, NOT merely absent. `route_decision` derives its default
    # from the hardware tier and the ladder's cost, so on a tier-1+ host with the shipped
    # all-local ladder an unset variable now means ON -- which would have made this "routing
    # OFF" arm route, and the A/B would have compared routing against itself.
    always = run_arm(
        "always",
        specs,
        {"DETERMINEX_ROLE_BUILDER": args.baseline, "DETERMINEX_ROUTE": "0"},
        args.timeout,
        args.lang,
    )

    print(f"\narm 2/2: routed {' -> '.join(ladder)}")
    routed = run_arm(
        "routed",
        specs,
        {
            "DETERMINEX_ROUTE": "1",
            "DETERMINEX_ROUTE_LADDER": ",".join(ladder),
            "DETERMINEX_ROUTE_K": str(args.k),
        },
        args.timeout,
        args.lang,
    )

    payload = report(always, routed, args.baseline, ladder)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
