"""Tests for determinex_local_oracle.py's expect_not_in enforcement (2026-07-16).

Closes the loop on the NotIn fix in determinex_io_extractor.py
(tests/test_determinex_io_extractor_notin.py): a captured negative expectation is only
meaningful if something checks a candidate's real output against it. Without this,
expect_not_in would be captured correctly and then silently ignored -- a candidate whose
output DOES contain a forbidden snippet would still be reported as passing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_local_oracle as oracle  # noqa: E402
from determinex_io_extractor import Example  # noqa: E402


def _ex(**kwargs) -> Example:
    return Example(test="t", **kwargs)


def test_passes_when_forbidden_snippet_absent():
    ex = _ex(expect_not_in=["unexpected argument"])
    ok, reason, detail = oracle._check(ex, 0, "clean output, no errors", "")
    assert ok


def test_fails_when_forbidden_snippet_present_in_stdout():
    ex = _ex(expect_not_in=["unexpected argument"])
    ok, reason, detail = oracle._check(ex, 0, "error: unexpected argument '-x'", "")
    assert not ok
    assert reason == "not_contains"
    assert "unexpected argument" in detail


def test_fails_when_forbidden_snippet_present_in_stderr():
    ex = _ex(expect_not_in=["crash"])
    ok, reason, detail = oracle._check(ex, 1, "", "program did crash unexpectedly")
    assert not ok
    assert reason == "not_contains"


def test_case_insensitive_when_ci_flag_set():
    ex = _ex(expect_not_in=["ERROR"], ci=True)
    ok, reason, detail = oracle._check(ex, 0, "an error occurred", "")
    assert not ok


def test_case_sensitive_by_default_does_not_false_positive():
    ex = _ex(expect_not_in=["ERROR"], ci=False)
    ok, reason, detail = oracle._check(ex, 0, "an error occurred", "")
    assert ok  # lowercase "error" doesn't match uppercase-required "ERROR"


def test_multiple_forbidden_snippets_all_checked():
    ex = _ex(expect_not_in=["forbidden-a", "forbidden-b"])
    ok1, _, _ = oracle._check(ex, 0, "totally clean", "")
    assert ok1
    ok2, reason2, _ = oracle._check(ex, 0, "contains forbidden-b here", "")
    assert not ok2
    assert reason2 == "not_contains"


def test_empty_expect_not_in_never_fails():
    ex = _ex(expect_not_in=[])
    ok, reason, detail = oracle._check(ex, 0, "anything at all", "")
    assert ok


def test_combines_correctly_with_expect_in_and_expect_in_any():
    """All three constraint types (AND, OR-group, negative) can coexist and must ALL be
    satisfied."""
    ex = _ex(
        expect_in=["mandatory"], expect_in_any=[["opt-a", "opt-b"]], expect_not_in=["forbidden"]
    )
    ok, _, _ = oracle._check(ex, 0, "mandatory text plus opt-a here", "")
    assert ok

    ok2, reason2, _ = oracle._check(ex, 0, "mandatory text plus opt-a plus forbidden", "")
    assert not ok2
    assert reason2 == "not_contains"
