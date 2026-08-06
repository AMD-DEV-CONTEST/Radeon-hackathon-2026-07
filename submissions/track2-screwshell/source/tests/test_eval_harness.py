"""Tests for the T3 evaluation gate: harness + compare regression detection.

Drives the real ``run_eval`` over a small golden set wired to a
``ScriptedEngine`` (the mock-only path, no GPU, no torch). Verifies the report
shape, that objective scorers actually get exercised, and that ``compare()``
flags a genuine degradation as REGRESS.
"""
import pytest

from screwshell.eval.fakes import build_mock_orchestrator
from screwshell.eval.harness import run_eval
from screwshell.eval.report import aggregate, compare
from screwshell.eval.types import EvalCase


CASES = [
    EvalCase(id="t1", query="Explain the router forbidden-expert guard.",
             must_cite=["screwshell/core/router.py"], expect_skills=["code"]),
    EvalCase(id="t2", query="Summarize the ROCm tuning notes.",
             must_cite=["demo_workspace/docs/rocm_notes.md"], expect_skills=["doc"]),
    EvalCase(id="t3", query="Compare the two migration strategies.",
             must_cite=["demo_workspace/docs/migration_plan.md"],
             expect_skills=["agent", "doc"]),
]


def test_run_eval_produces_report():
    report = run_eval(CASES, build_mock_orchestrator, repeats=1)
    assert len(report.cases) == 3
    for cr in report.cases:
        assert cr.ok, f"{cr.case_id} produced an empty answer"
        assert cr.scores, f"{cr.case_id} has no scores"
        assert cr.applies, f"{cr.case_id} did not record applicable scorers"
        # skills came from the routed plan steps
        assert cr.skills, f"{cr.case_id} recorded no skills"
    agg = aggregate(report)
    assert agg["cases"] == 3
    assert agg["ok"] == 3
    assert agg["overall"] > 0.0


def test_objective_scorers_exercised():
    report = run_eval(CASES, build_mock_orchestrator, repeats=1)
    agg = aggregate(report)
    # every case has must_cite -> citation_coverage applies & the scripted
    # answer cites the source -> 1.0
    assert agg["applied"]["citation_coverage"] == 3
    assert agg["scorers"]["citation_coverage"] == 1.0
    # routing matches the planned skills -> 1.0
    assert agg["scorers"]["routing_accuracy"] == 1.0
    # status matches expectation (ok) -> 1.0
    assert agg["scorers"]["status_match"] == 1.0


def test_compare_flags_regression():
    good = run_eval(CASES, build_mock_orchestrator, repeats=1)

    def degraded_factory(case, config):
        # same wiring, but the answer omits the required citation
        return build_mock_orchestrator(case=case, config=config,
                                       final="No sources were consulted.")

    bad = run_eval(CASES, degraded_factory, repeats=1)
    cmp = compare(good, bad)
    assert cmp["verdict"] == "REGRESS"
    assert "citation_coverage" in cmp["regressed"]


def test_compare_identical_passes():
    good = run_eval(CASES, build_mock_orchestrator, repeats=1)
    cmp = compare(good, good)
    assert cmp["verdict"] == "PASS"
    assert cmp["regressed"] == []


# --------------------------------------------------------------- llm-judge --
def test_llm_judge_applies_only_when_injected():
    """LLM-as-a-judge scorer (OPENSOURCE_COMPARISON §5 B档): without an
    injected judge_fn it must NOT be applicable (no 0.0 pollution); with one
    it scores the answer."""
    from screwshell.eval import scorers
    from screwshell.eval.scorers import applies, score_case
    from screwshell.eval.types import CaseResult, EvalCase

    case = EvalCase(id="j1", query="q", kind="qa")
    res = CaseResult(case_id="j1", answer="answer text", ok=True, status="ok")
    assert applies("llm_judge", case) is False, "no judge -> not applicable"

    seen = {}

    def stub(query, answer, gold):
        seen.update(query=query, answer=answer)
        return 0.8

    scorers.set_judge(stub)
    try:
        assert applies("llm_judge", case) is True
        scores = score_case(res, case, scorers=scorers.DEFAULT_SCORERS)
        assert scores["llm_judge"] == pytest.approx(0.8)
        assert seen["answer"] == "answer text"
    finally:
        scorers.set_judge(None)
