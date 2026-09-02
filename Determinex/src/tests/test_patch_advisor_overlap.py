"""tests/test_patch_advisor_overlap.py — assertion-string overlap signal.

Iter-1 lesson: family share alone over-predicts patchability. Advisor now
computes literal assertion-string overlap and penalizes confidence when
<30% of the failing tests in the target family actually expect the patch's
wording. These tests pin that contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

from programbench_patch_advisor import (  # noqa: E402
    compute_assertion_string_overlap,
    propose,
)


def _write_eval_json(p: Path, failures: list[dict]) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "test_results": failures,
            }
        ),
        encoding="utf-8",
    )
    return p


def test_overlap_returns_none_when_no_literal_strings():
    """No literal_match_strings → signal can't be computed → None."""
    out, n = compute_assertion_string_overlap([], family="x", literal_match_strings=[])
    assert out is None
    assert n == 0


def test_overlap_high_when_failures_match_wording(tmp_path):
    """If every rc-family failure expects 'unexpected argument', overlap = 100%.
    Each message must contain a rc-classifier trigger ('unknown option' or
    'unexpected argument') to land in the bucket."""
    p = _write_eval_json(
        tmp_path / "t.eval.json",
        [
            {
                "status": "failure",
                "name": "test_unknown_flag_1",
                "extra": {
                    "message": "assert 'unknown option: -A' == 'error: unexpected argument'\n"
                },
            },
            {
                "status": "failure",
                "name": "test_unknown_flag_2",
                "extra": {
                    "message": "actual unknown option: -X expected: unexpected argument '-X'"
                },
            },
            {"status": "passed", "name": "test_help"},  # ignored
        ],
    )
    overlap, n = compute_assertion_string_overlap(
        [p],
        family="rc_2_unknown_option",
        literal_match_strings=["unexpected argument"],
    )
    assert n == 2
    assert overlap == 1.0


def test_overlap_low_when_tests_want_app_errors(tmp_path):
    """The iter-1 hyperfine case: rc-family failures (scaffold's 'unknown
    option:' wording puts them in the bucket) but the EXPECTED content
    is a tool-specific app error → patch wording overlap is low."""
    p = _write_eval_json(
        tmp_path / "t.eval.json",
        [
            # 1 of 10 tests literally expects the patch wording — 'unknown
            # option' on the actual side classifies it, 'unexpected argument'
            # on the expected side counts as overlap hit.
            {
                "status": "failure",
                "name": "test_truly_unknown",
                "extra": {
                    "message": (
                        "actual: 'tool: unknown option: -X' expected: 'error: unexpected argument'"
                    )
                },
            },
            # 9 of 10 want tool-specific app errors. Classifier still buckets
            # them as rc_2_unknown_option (actual stderr triggers it), but the
            # expected side has nothing about 'unexpected argument' — that's
            # the cliff the patch falls off.
            *[
                {
                    "status": "failure",
                    "name": f"test_app_{i}",
                    "extra": {
                        "message": (
                            f"actual: 'tool: unknown option: -L' "
                            f"expected: 'Error: Duplicate parameter names: x{i}'"
                        )
                    },
                }
                for i in range(9)
            ],
        ],
    )
    overlap, n = compute_assertion_string_overlap(
        [p],
        family="rc_2_unknown_option",
        literal_match_strings=["unexpected argument"],
    )
    assert n == 10
    # The first test's expected side has 'unexpected argument' → 1 hit.
    # The other 9 tests' expected sides have 'Duplicate parameter names'
    # but no 'unexpected argument' → 0 hits each. Total: 1/10 = 0.1.
    assert overlap == 0.1


def test_propose_penalizes_confidence_when_overlap_low(tmp_path):
    """Low overlap (<30%) downgrades confidence from high to low.

    Fake test must contain rc-family classifier triggers (e.g. 'unknown option')
    so it lands in the bucket — but NOT contain the patch's literal wording
    ('unexpected argument'). That's the iter-1 scenario: scaffold emits one
    wording, test asserts on a different one entirely."""
    p = _write_eval_json(
        tmp_path / "low.eval.json",
        [
            # Classifier hits 'unknown option' (scaffold output) but the expected
            # side asserts a tool-specific app error — patch wording absent.
            {
                "status": "failure",
                "name": "t",
                "extra": {
                    "message": (
                        "actual: 'tool: unknown option: -L' "
                        "expected: 'Error: Duplicate parameter names: x'"
                    )
                },
            },
        ],
    )
    snapshot = {
        "top_families": [
            {"family": "rc_2_unknown_option", "failures": 1000, "tools_affected": 100},
        ],
    }
    recs = propose(snapshot, eval_json_paths=[p])
    assert len(recs) == 1
    r = recs[0]
    # Overlap should be 0% — substring 'unexpected argument' is not in the msg
    assert r.assertion_string_overlap == 0.0
    assert r.confidence_adjustment == "penalty_low_overlap"
    # Raw confidence 0.85 (high) → adjusted should land on "low"
    assert r.confidence_label == "low"


def test_propose_no_penalty_when_overlap_high(tmp_path):
    """High overlap means the patch wording is what tests literally expect."""
    p = _write_eval_json(
        tmp_path / "high.eval.json",
        [
            # 'unknown option' lands the test in rc bucket; expected side ALSO
            # contains the patch wording — overlap will be 100%.
            {
                "status": "failure",
                "name": "t",
                "extra": {
                    "message": (
                        "actual: 'tool: unknown option: -X' "
                        "expected: 'error: unexpected argument -X found'"
                    )
                },
            },
        ],
    )
    snapshot = {
        "top_families": [
            {"family": "rc_2_unknown_option", "failures": 1000, "tools_affected": 100},
        ],
    }
    recs = propose(snapshot, eval_json_paths=[p])
    r = recs[0]
    assert r.assertion_string_overlap == 1.0
    assert r.confidence_adjustment == "none"
    assert r.confidence_label == "high"


def test_propose_works_without_eval_paths_legacy():
    """Backward compat: no eval JSONs supplied → overlap is None, no penalty."""
    snapshot = {
        "top_families": [
            {"family": "rc_2_unknown_option", "failures": 100, "tools_affected": 10},
        ],
    }
    recs = propose(snapshot, eval_json_paths=None)
    r = recs[0]
    assert r.assertion_string_overlap is None
    assert r.confidence_adjustment == "none"


def test_profile_rc_unknown_carries_iter1_evidence_tag():
    """Iter-1 history must be preserved on the rc_2_unknown_option entry —
    future iterations should see the warning before re-picking this family."""
    from programbench_patch_advisor import PROGRAMBENCH_PROFILE

    p = PROGRAMBENCH_PROFILE["rc_2_unknown_option"]
    assert "low-universal-lift-evidence" in p.tags
    assert any("iter-1 shard" in h for h in p.history), (
        "iter-1 shard finding must be recorded in patch history"
    )
