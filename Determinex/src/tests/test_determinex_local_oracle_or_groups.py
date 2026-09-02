"""Tests for determinex_local_oracle.py's OR-group (expect_in_any) enforcement (2026-07-16).

Closes the loop on the BoolOp/OR fix in determinex_io_extractor.py
(tests/test_determinex_io_extractor_boolop_or.py): a captured OR-group is only meaningful if
something actually CHECKS a candidate's real output against it. Without this, expect_in_any
would be captured correctly but silently ignored -- a candidate satisfying none of a group's
alternatives would still be reported as passing, exactly the "corpus knows but doesn't act on
it" gap this whole session has been closing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_local_oracle as oracle  # noqa: E402
from determinex_io_extractor import Example  # noqa: E402


def _ex(**kwargs) -> Example:
    return Example(test="t", **kwargs)


def test_passes_when_first_alternative_present():
    ex = _ex(expect_in_any=[["squash", "patch"]])
    ok, reason, detail = oracle._check(ex, 0, "output mentions squash here", "")
    assert ok


def test_passes_when_second_alternative_present():
    ex = _ex(expect_in_any=[["squash", "patch"]])
    ok, reason, detail = oracle._check(ex, 0, "output mentions patch here", "")
    assert ok


def test_fails_when_neither_alternative_present():
    ex = _ex(expect_in_any=[["squash", "patch"]])
    ok, reason, detail = oracle._check(ex, 0, "completely unrelated output", "")
    assert not ok
    assert reason == "contains_any"
    assert "squash" in detail and "patch" in detail


def test_checks_stderr_too():
    ex = _ex(expect_in_any=[["error-a", "error-b"]])
    ok, reason, detail = oracle._check(ex, 1, "", "saw error-b during run")
    assert ok


def test_case_insensitive_when_ci_flag_set():
    ex = _ex(expect_in_any=[["SQUASH", "PATCH"]], ci=True)
    ok, reason, detail = oracle._check(ex, 0, "output mentions squash here", "")
    assert ok


def test_case_sensitive_by_default_fails_on_case_mismatch():
    ex = _ex(expect_in_any=[["SQUASH", "PATCH"]], ci=False)
    ok, reason, detail = oracle._check(ex, 0, "output mentions squash here", "")
    assert not ok


def test_multiple_or_groups_all_must_have_at_least_one_match():
    """Two independent OR-groups: each is its own 'at least one' requirement -- this is
    the AND-of-ORs shape a test like `assert (A or B) ... assert (C or D)` produces."""
    ex = _ex(expect_in_any=[["a1", "a2"], ["b1", "b2"]])
    ok, reason, detail = oracle._check(ex, 0, "has a1 and b2 both", "")
    assert ok

    ok2, reason2, detail2 = oracle._check(ex, 0, "has a1 but not the other group", "")
    assert not ok2
    assert reason2 == "contains_any"


def test_empty_expect_in_any_never_fails():
    ex = _ex(expect_in_any=[])
    ok, reason, detail = oracle._check(ex, 0, "anything at all", "")
    assert ok


def test_combines_correctly_with_plain_expect_in_and():
    """expect_in (AND) and expect_in_any (OR-groups) can coexist on the same Example --
    both must be satisfied."""
    ex = _ex(expect_in=["mandatory"], expect_in_any=[["opt-a", "opt-b"]])
    ok, reason, detail = oracle._check(ex, 0, "mandatory text plus opt-a here", "")
    assert ok

    # missing the AND-required snippet entirely -> fails on "contains", never reaches
    # the OR-group check
    ok2, reason2, detail2 = oracle._check(ex, 0, "opt-a present but the required word absent", "")
    assert not ok2
    assert reason2 == "contains"
