#!/usr/bin/env python3
"""End-to-end evaluation CLI for ScrewShell (blueprint T3).

    python bench/eval_e2e.py --cases core_10 --mode mock \
        --flags "gbnf=1,prefill_slim=1,max_actions=2" --out bench/eval/

  --cases   name of a case file under screwshell/eval/cases/ (e.g. core_10),
            or a path to a .json file.
  --mode    mock | real.  mock runs locally with ScriptedEngine (no GPU);
            real builds the real app via build_app (needs a GPU / llama-server).
  --flags   comma list of E2EConfig switches (the A/B knob); see core/config.py.
  --out     directory for the .json + .md report.

On the first run with a given (cases, mode) tag it SEEDS a baseline; on later
runs it compares the new report against that baseline and prints a PASS /
REGRESS verdict, so a regression is caught locally instead of in CI.

Hard rule (blueprint §6.2 rule 6): this module never imports torch at load
time -- ``build_app`` (and thus the real torch backend) is imported lazily
inside the real branch only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from screwshell.core.config import E2EConfig
from screwshell.eval.fakes import build_mock_orchestrator
from screwshell.eval.harness import run_eval
from screwshell.eval.report import aggregate, compare, to_markdown
from screwshell.eval.thresholds import check_bars
from screwshell.eval.types import EvalCase


def _load_cases(name: str) -> list[EvalCase]:
    if name.endswith(".json") and os.path.isabs(name):
        path = name
    elif name.endswith(".json"):
        path = os.path.join(ROOT, name)
    else:
        path = os.path.join(ROOT, "screwshell", "eval", "cases", f"{name}.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return [EvalCase.from_dict(c) for c in raw]


def _mock_factory(case: EvalCase, config: E2EConfig) -> object:
    return build_mock_orchestrator(case=case, config=config)


def _real_factory(case: EvalCase, config: E2EConfig) -> object:
    from screwshell.app import build_app   # lazy: pulls in the torch backend
    ws = os.path.join(ROOT, case.workspace)
    ctx = build_app(ws, build_rag=True, l3_mode="roomy")
    ctx.orchestrator.config = config
    return ctx.orchestrator


def main() -> int:
    ap = argparse.ArgumentParser(description="ScrewShell eval gate")
    ap.add_argument("--cases", default="core_10")
    ap.add_argument("--mode", choices=["mock", "real"], default="mock")
    ap.add_argument("--flags", default="",
                    help="comma list of E2EConfig switches, e.g. gbnf=1,prefill_slim=1")
    ap.add_argument("--out", default=os.path.join(ROOT, "bench", "eval"))
    ap.add_argument("--repeats", type=int, default=1)
    args = ap.parse_args()

    config = E2EConfig().apply_flags(args.flags or None)
    cases = _load_cases(args.cases)
    factory = _real_factory if args.mode == "real" else _mock_factory

    print(f"[eval] mode={args.mode} cases={len(cases)} "
          f"flags={config.describe()}")

    report = run_eval(cases, factory, config=config, repeats=args.repeats,
                      engine=args.mode)
    report.tag = f"{args.cases}_{args.mode}"
    agg = aggregate(report)
    print(to_markdown(report))

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, f"{report.tag}.json")
    md_path = os.path.join(args.out, f"{report.tag}.md")
    report.to_json(json_path)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(report))
    print(f"[eval] wrote {json_path}")
    print(f"[eval] wrote {md_path}")

    # ---- absolute quality gate (B7): any measurable LLM bar not met -> fail.
    # The gate enforces what a run can always measure (latency / token bars),
    # so a genuinely slow or token-heavy run fails loudly instead of sliding.
    bars_failed = check_bars(agg)
    if bars_failed:
        print("[eval] GATE FAIL — measurable LLM bars not met:")
        for m, info in bars_failed.items():
            direction = "lower-is-better" if info["lower_is_better"] else \
                "higher-is-better"
            print(f"    {m}: {info['value']} (bar {info['bar']}, {direction})")
        return 1

    # regression gate vs a stored baseline (seeded on first run)
    baseline_file = os.path.join(args.out, f"{report.tag}.baseline.json")
    if os.path.isfile(baseline_file):
        with open(baseline_file, encoding="utf-8") as f:
            base = json.load(f)
        cmp = compare(base, report.to_dict())
        print(f"[eval] regression vs baseline: {cmp['verdict']} "
              f"(tol={cmp['tolerance']})")
        if cmp["regressed"]:
            print("  regressed scorers: " + ", ".join(cmp["regressed"]))
        if cmp["verdict"] != "PASS":
            return 1
    else:
        with open(baseline_file, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=1)
        print(f"[eval] seeded baseline at {baseline_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
