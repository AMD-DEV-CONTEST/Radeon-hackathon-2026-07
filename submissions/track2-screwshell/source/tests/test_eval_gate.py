"""Regression tests for the Wave-0 metric-gate source defects (B1/B4/B5/B6/B7).

These pin down the five *source* bugs the independent QA probe found -- all in
``screwshell/eval/``. They must fail on the buggy code and pass after the fix:

  * B1  ``normalize_path`` must preserve dotfiles (``.env`` stays ``.env``), so
        ``leak_penalty(must_not_cite=['.env'])`` no longer false-fires on the
        word "environment".
  * B4  ``compare()`` must (a) honour ``is_lower_better`` when judging a
        regression (a rise in a lower-is-better metric regresses) and (b) check
        the measurable LLM latency / token bars against ``THRESHOLDS`` via
        ``meets()``.
  * B5  ``to_markdown`` must render ``report.config`` (already the non_default
        diff dict), not ``report.config.get("non_default")`` which is always
        ``None``.
  * B6  ``run_eval`` must isolate a per-case crash -- one bad case must not lose
        the whole run, and its ``CaseResult.error`` must be populated.
  * B7  ``meets()`` is wired into the gate via ``check_bars``; a missed bar
        fails, so the declared ``THRESHOLDS`` are enforced, not decorative.
"""
from screwshell.eval.fakes import build_mock_orchestrator
from screwshell.eval.harness import run_eval
from screwshell.eval.report import aggregate, compare, to_markdown
from screwshell.eval.scorers import (
    citation_coverage,
    leak_penalty,
    normalize_path,
)
from screwshell.eval.thresholds import (
    THRESHOLDS,
    check_bars,
    is_lower_better,
    meets,
)
from screwshell.eval.types import CaseResult, EvalCase, EvalReport


# --------------------------------------------------------------------- B1 ---

def test_normalize_path_preserves_dotfiles():
    # The old ``.lstrip("./")`` was a character-set strip that ate dotfiles.
    assert normalize_path(".env") == ".env"
    assert normalize_path(".gitignore") == ".gitignore"
    assert normalize_path("...secret.txt") == "...secret.txt"
    assert normalize_path(".env") != "env"            # the core bug
    # A genuine leading "./" is still stripped.
    assert normalize_path("./docs/a.md") == "docs/a.md"
    # Windows separators normalise to forward slashes.
    assert normalize_path(r"docs\a.md") == "docs/a.md"


def test_leak_penalty_not_false_positive_on_environment_word():
    # Answer mentions "environment" but never cites the forbidden ".env".
    case = EvalCase(id="lp", query="q", must_not_cite=[".env"])
    res = CaseResult(
        case_id="lp", answer="The environment variable is fine.",
        ok=True, status="ok", scores={}, applies={},
        retrieved=[{"source": "docs/readme.md", "start_line": 1,
                    "end_line": 2}])
    # Before the fix this returned 0.0 (false leak) because ".env" -> "env"
    # matched the substring inside "environment".
    assert leak_penalty(res, case) == 1.0


def test_leak_penalty_flags_real_dotenv_citation():
    case = EvalCase(id="lp2", query="q", must_not_cite=[".env"])
    res = CaseResult(
        case_id="lp2", answer="See .env for the secret.",
        ok=True, status="ok", scores={}, applies={},
        retrieved=[{"source": ".env", "start_line": 1, "end_line": 2}])
    assert leak_penalty(res, case) == 0.0


# --------------------------------------------------------------------- B4 ---

def test_compare_lower_is_better_flips_worse_direction():
    # A lower-is-better scorer that RISES must regress (delta > +tol).
    base = {"aggregate": {"scorers": {"p95_seconds": 10.0},
                          "overall": 0.0, "llm": {}}}
    cur = {"aggregate": {"scorers": {"p95_seconds": 250.0},
                         "overall": 0.0, "llm": {}}}
    cmp = compare(base, cur)
    assert "p95_seconds" in cmp["regressed"]
    assert cmp["verdict"] == "REGRESS"

    # And the SAME rise, when it is a DROP, must NOT regress.
    base2 = {"aggregate": {"scorers": {"p95_seconds": 250.0},
                           "overall": 0.0, "llm": {}}}
    cur2 = {"aggregate": {"scorers": {"p95_seconds": 10.0},
                          "overall": 0.0, "llm": {}}}
    cmp2 = compare(base2, cur2)
    assert "p95_seconds" not in cmp2["regressed"]
    assert cmp2["verdict"] == "PASS"


def test_compare_flags_llm_bar_miss():
    # (b) the measurable LLM latency bar is checked via meets().
    base = {"aggregate": {"scorers": {}, "overall": 0.0,
                          "llm": {"p95_seconds": 10.0}}}
    cur = {"aggregate": {"scorers": {}, "overall": 0.0,
                         "llm": {"p95_seconds": 400.0}}}
    cmp = compare(base, cur)
    assert cmp["verdict"] == "FAIL"
    assert "p95_seconds" in cmp["bars_failed"]
    assert cmp["bars"]["p95_seconds"]["meets"] is False


def test_compare_within_bar_passes():
    agg_like = {"aggregate": {"scorers": {}, "overall": 0.0,
                              "llm": {"p95_seconds": 12.0}}}
    cmp = compare(agg_like, agg_like)
    assert cmp["verdict"] == "PASS"
    assert cmp["bars_failed"] == []


# --------------------------------------------------------------------- B5 ---

def test_to_markdown_renders_flags():
    report = EvalReport(started="2026-01-01", engine="mock",
                        config={"gbnf": 1, "prefill_slim": 1},
                        cases=[], scorers=[], seconds=0.0)
    md = to_markdown(report)
    assert "- flags   :" in md
    assert "gbnf" in md

    # An empty (baseline) config renders no flags line.
    empty = EvalReport(started="2026-01-01", engine="mock", config={},
                       cases=[], scorers=[], seconds=0.0)
    assert "- flags   :" not in to_markdown(empty)


# --------------------------------------------------------------------- B6 ---

def test_run_eval_isolates_case_crash():
    cases = [
        EvalCase(id="ok1", query="q1"),
        EvalCase(id="boom", query="q2"),
        EvalCase(id="ok2", query="q3"),
    ]

    class BoomFactory:
        def __init__(self):
            self.calls = 0

        def __call__(self, case, config):
            self.calls += 1
            if case.id == "boom":
                raise RuntimeError("simulated engine crash")
            return build_mock_orchestrator(case=case, config=config)

    report = run_eval(cases, BoomFactory(), repeats=1)
    assert len(report.cases) == 3
    by_id = {c.case_id: c for c in report.cases}

    # The healthy cases are unaffected.
    assert by_id["ok1"].ok is True
    assert by_id["ok2"].ok is True
    assert by_id["ok1"].scores           # still scored normally

    # The crashed case is recorded as a FAIL with its error populated.
    boom = by_id["boom"]
    assert boom.ok is False
    assert boom.error is not None
    assert "simulated engine crash" in boom.error


# --------------------------------------------------------------------- B7 ---

def test_check_bars_fails_missing_threshold():
    agg = {"llm": {"p95_seconds": 500.0, "calls": 3, "prompt_tokens": 100}}
    failed = check_bars(agg)
    assert "p95_seconds" in failed
    assert failed["p95_seconds"]["meets"] is False
    # metrics with no declared bar are skipped, not failed
    assert "calls" not in failed
    assert "prompt_tokens" not in failed


def test_check_bars_passes_when_within_bar():
    assert check_bars({"llm": {"p95_seconds": 12.0}}) == {}


def test_meets_is_direction_aware():
    # Lower-is-better: smaller is better.
    assert meets("p95_seconds", 100) is True
    assert meets("p95_seconds", 400) is False
    # Higher-is-better: larger is better.
    assert meets("citation_accuracy", 0.95) is True
    assert meets("citation_accuracy", 0.5) is False
    # Unbarred metric -> None (not a failure).
    assert meets("calls", 100) is None


def test_is_lower_better_covers_declared_latency_metrics():
    for m in ("p95_seconds", "p50_seconds", "mean_seconds", "total_seconds",
              "prompt_tokens", "new_tokens", "calls", "unaccounted_s"):
        assert is_lower_better(m) is True
    assert is_lower_better("citation_coverage") is False
