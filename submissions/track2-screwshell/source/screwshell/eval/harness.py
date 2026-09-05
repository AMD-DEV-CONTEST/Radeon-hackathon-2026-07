"""The measurement gate: run golden cases through an orchestrator, score them.

Hard rules (blueprint §6.2 rules 6 and 8):

  * **stdlib only** -- no torch / gradio / numpy / any third party. The gate
    must run on a laptop with no GPU, otherwise it cannot gate anything.
  * **this module NEVER builds an engine and NEVER imports torch.** The engine
    (and the whole Orchestrator graph) is produced by an injected
    ``orchestrator_factory`` supplied by the caller. That is what makes the gate
    itself testable: ``bench/eval_e2e.py --mode mock`` injects a factory that
    hangs a ``ScriptedEngine`` off the Orchestrator, while a bench run on the
    W7900 injects one that calls ``build_app(...)``. This file stays ignorant of
    which, so it can be unit-tested without a GPU and without importing torch.

The contract for ``orchestrator_factory``::

    orchestrator_factory(case: EvalCase, config: E2EConfig) -> Orchestrator

``run_eval`` drives ``orch.run(case.query)`` for every case (× ``repeats``),
extracts what the scorers need from the ``RunResult``, and records one
``CaseResult`` per run. ``report.aggregate`` then turns the run into the
numbers the regression gate compares.
"""
from __future__ import annotations

import datetime
import subprocess
import time
from typing import Any, Callable, Iterable, Optional

from screwshell.eval.scorers import (DEFAULT_SCORERS, applies, score_case,
                                     scorer_name)
from screwshell.eval.types import CaseResult, EvalCase, EvalReport


def _git_sha() -> str:
    """Best-effort git SHA for the report header; '' when unavailable."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def run_eval(cases: list[EvalCase],
             orchestrator_factory: Callable[[EvalCase, Any], Any],
             *, config: Any = None,
             scorers: Optional[Iterable] = None,
             repeats: int = 1,
             engine: str = "mock") -> EvalReport:
    """Run every case (× ``repeats``) and return an ``EvalReport``.

    Args:
        cases: golden-set items.
        orchestrator_factory: ``(case, config) -> Orchestrator`` supplied by the
            caller (the only place an engine is ever constructed).
        config: the active ``E2EConfig`` (flags), forwarded to the factory.
        scorers: the scorer functions to run; defaults to ``DEFAULT_SCORERS``.
        repeats: how many times to run each case (averaged by ``aggregate``).
        engine: a label for the report header ("mock" / "real" / ...).
    """
    scorer_fns = list(scorers) if scorers is not None else list(DEFAULT_SCORERS)
    names = [scorer_name(f) for f in scorer_fns]
    repeats = max(1, int(repeats))

    started = datetime.datetime.now().isoformat(timespec="seconds")
    git_sha = _git_sha()
    # Store only the flags that differ from baseline so the report header and a
    # later regression compare stay focused on what actually changed.
    if hasattr(config, "non_default"):
        cfg_dict = config.non_default()
    elif hasattr(config, "to_dict"):
        cfg_dict = config.to_dict()
    else:
        cfg_dict = (config or {})

    results: list[CaseResult] = []
    t0 = time.perf_counter()
    for _ in range(repeats):
        for case in cases:
            t_run = time.perf_counter()
            try:
                orch = orchestrator_factory(case, config)
                run = orch.run(case.query)
            except Exception as exc:  # one bad case must not sink the whole run
                elapsed = time.perf_counter() - t_run
                cr = CaseResult(
                    case_id=case.id, answer="", ok=False, status="failed",
                    seconds=round(elapsed, 3), skills=[], retrieved=[],
                    stats={}, error=str(exc),
                )
                cr.scores = {}
                cr.applies = {n: applies(n, case) for n in names}
                results.append(cr)
                continue
            elapsed = time.perf_counter() - t_run

            toolkit = getattr(orch, "toolkit", None)
            retrieved = list(getattr(toolkit, "seen_citations", None) or [])
            answer = run.answer or ""
            status = "failed" if not answer.strip() else "ok"

            cr = CaseResult(
                case_id=case.id, answer=answer, ok=bool(answer.strip()),
                status=status, seconds=round(elapsed, 3),
                skills=[t.skill for t in run.traces],
                retrieved=retrieved,
                stats={"llm": run.stats.get("llm"),
                       "budget": run.stats.get("budget"),
                       "phases": run.stats.get("phases")},
            )
            cr.scores = score_case(cr, case, scorer_fns)
            cr.applies = {n: applies(n, case) for n in names}
            results.append(cr)

    report = EvalReport(
        started=started, git_sha=git_sha, engine=engine, config=cfg_dict,
        cases=results, scorers=names,
        seconds=round(time.perf_counter() - t0, 3), repeats=repeats)
    return report


__all__ = ["run_eval"]
