"""ScrewShell end-to-end evaluation gate (blueprint T3).

The measurement gate is the only thing that lets any later optimization claim
"done": one command produces both arms of an A/B, and `report.compare()` turns
the difference into a verdict instead of an opinion.

Hard rules for everything in this package (blueprint §6.2 rules 6 and 8):

* **stdlib only** -- no torch / gradio / numpy / any third party. The gate must
  run on a laptop with no GPU, otherwise it cannot gate anything.
* **the harness never builds an engine.** `run_eval()` takes an
  `orchestrator_factory`; the caller decides whether that is a `ScriptedEngine`
  (local regression) or a real `build_app(...)` (bench run). This is what makes
  the gate itself testable.
* `fakes.py` is the single source of mock engines. New tests reuse it rather
  than growing another private FakeEngine.
"""
from __future__ import annotations

from screwshell.eval.types import (CaseResult, EvalCase, EvalReport, Scorer)

__all__ = ["CaseResult", "EvalCase", "EvalReport", "Scorer"]
