#!/usr/bin/env python3
"""
determinex_pb_official_score.py -- THE official ProgramBench scorer (canonical, in-repo)
=====================================================================================
For two weeks the board used raw `passed / len(test_results)`. That is NOT the official
metric. ProgramBench ships `programbench info`, which scores:

    result.for_branches(get_active_branches(inst)).without_ignored(get_ignored_tests(inst))
    score = n_resolved / len(result)        # n_resolved = count(status == "passed")

i.e. it DROPS every PB-designated `ignored_tests` (reasons gold_fail / dummy_pass) from BOTH
numerator and denominator, drops ignored branches, and STILL counts not_run (the June-6 lesson).
A displayed integer 100 may be a rounded 99.5 -> a TRUE lock requires n_resolved == len EXACTLY.

Raw scoring counted ignored_tests against us -> systematically under-scored any tool with
gold_fail/dummy_pass tests (and falsely made some look like "ceilings"). This module is the
single canonical implementation so pb_parallel / pb_ingest / the gate never diverge again.

It ALSO subsumes the perm/root-skip "problem": perm tests that self-skip as root are gold_fail
-> in ignored_tests -> officially dropped. droppriv is neither needed nor safe (it regresses).

Requires the `programbench` package importable (its src on sys.path or pip-installed).

Usage:
  python scripts/determinex_pb_official_score.py <iid> <eval.json> [<iid> <eval.json> ...]
  python scripts/determinex_pb_official_score.py --glob '/root/citadel-programbench/*/*/*.eval.json'
"""

from __future__ import annotations

import argparse
import glob as _glob
import os
import sys
from dataclasses import dataclass


def _ensure_pb_importable() -> None:
    for p in ("/root/ProgramBench/src", os.environ.get("PROGRAMBENCH_SRC", "")):
        if p and p not in sys.path and os.path.isdir(p):
            sys.path.insert(0, p)


@dataclass
class OfficialScore:
    iid: str
    n_resolved: int
    total: int  # len after for_branches + without_ignored (not_run counted)
    is_true_100: bool
    pct: float
    raw_resolved: int
    raw_total: int


def score_eval(
    iid: str, eval_json_path: str, instances: dict | None = None
) -> OfficialScore | None:
    """Official score for one eval.json. `instances` maps instance_id -> task instance dict."""
    _ensure_pb_importable()
    from programbench.eval.eval import EvaluationResult
    from programbench.utils.load_data import (
        get_active_branches,
        get_ignored_tests,
        load_all_instances,
    )

    if instances is None:
        instances = {i["instance_id"]: i for i in load_all_instances(include_tests=True)}
    inst = instances.get(iid)
    if inst is None:
        return None
    try:
        res = EvaluationResult.model_validate_json(open(eval_json_path, encoding="utf-8").read())
    except Exception:
        return None
    raw_resolved, raw_total = res.n_resolved, len(res)
    r = res.for_branches(get_active_branches(inst)).without_ignored(get_ignored_tests(inst))
    total = len(r)
    if total == 0:
        return None
    nr = r.n_resolved
    return OfficialScore(
        iid=iid,
        n_resolved=nr,
        total=total,
        is_true_100=(nr == total),
        pct=100.0 * nr / total,
        raw_resolved=raw_resolved,
        raw_total=raw_total,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="*", help="alternating <iid> <eval.json> ...")
    ap.add_argument("--glob", help="glob of */<iid>/<iid>.eval.json")
    args = ap.parse_args()
    _ensure_pb_importable()
    from programbench.utils.load_data import load_all_instances

    instances = {i["instance_id"]: i for i in load_all_instances(include_tests=True)}

    jobs: list[tuple[str, str]] = []
    if args.glob:
        for ej in _glob.glob(args.glob):
            iid = os.path.basename(ej)[: -len(".eval.json")]
            jobs.append((iid, ej))
    it = iter(args.pairs)
    for iid in it:
        jobs.append((iid, next(it)))

    locks = 0
    for iid, ej in jobs:
        s = score_eval(iid, ej, instances)
        if s is None:
            print(f"  {iid}: UNSCORABLE (not in task data / bad json)")
            continue
        tag = "TRUE-100 LOCK" if s.is_true_100 else f"miss {s.total - s.n_resolved}"
        locks += s.is_true_100
        print(
            f"  {s.iid}: OFFICIAL {s.n_resolved}/{s.total} = {s.pct:.2f}%  "
            f"(raw {s.raw_resolved}/{s.raw_total})  {tag}"
        )
    if jobs:
        print(f"== {locks} true-100 official lock(s) of {len(jobs)} scored ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
