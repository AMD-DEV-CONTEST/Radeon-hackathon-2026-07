"""Lock for the 2026-07-03 assertion-aware oracle fix.

Root cause of the overnight 0-lock plateau (found by inspecting bore, the highest
scorer at 24/39): the reimpl oracle (make_verify) demanded byte-EXACT reproduction
of the reference binary's output, but the OFFICIAL ProgramBench tests grade with
CONTAINS (expect_in) / rc-only for the error-formatting cases. bore's 39 examples:
0 require exact stdout -- all are expect_in/expect_rc. So the model was graded on
reproducing full clap error banners (incl. the real binary's own name) verbatim,
when the test only needed a substring. Every tool plateaued on its ~15 hardest
error stations. The oracle now honors the test's REAL criteria when an Observation
carries an `assertion`; fuzz probes (assertion=None) keep exact match.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import determinex_observe as OBS  # noqa: E402


def _probe(argv=("server", "--min-port", "50000", "--max-port", "40000")):
    return OBS.Probe("spec::port_range", list(argv))


_REF_STDERR = (
    "error: port range is empty\n\nUsage: bore-cli server [OPTIONS]\n\n"
    "For more information, try '--help'.\n"
)


def test_contains_assertion_passes_substring_candidate():
    obs = OBS.Observation(
        _probe(),
        "",
        _REF_STDERR,
        1,
        assertion={"expect_in": ["port range is empty"], "expect_rc": 1, "expect_stdout": None},
    )
    # a small model emits the substring + rc, NOT the exact clap banner
    v = OBS.make_verify([obs], runner=lambda c, p: ("", "error: port range is empty\n", 1))
    assert v("x").passed


def test_exact_oracle_would_reject_the_same_candidate():
    # PROOF this was the plateau: with no assertion (exact match), the substring
    # candidate FAILS because it doesn't reproduce the full banner.
    obs = OBS.Observation(_probe(), "", _REF_STDERR, 1)  # assertion=None -> exact
    v = OBS.make_verify([obs], runner=lambda c, p: ("", "error: port range is empty\n", 1))
    assert not v("x").passed


def test_contains_still_rejects_wrong_output_and_wrong_rc():
    obs = OBS.Observation(
        _probe(),
        "",
        _REF_STDERR,
        1,
        assertion={"expect_in": ["port range is empty"], "expect_rc": 1, "expect_stdout": None},
    )
    assert not OBS.make_verify([obs], runner=lambda c, p: ("", "", 0))("x").passed  # empty
    assert not OBS.make_verify([obs], runner=lambda c, p: ("", "wrong\n", 1))(
        "x"
    ).passed  # no substring
    # right message, wrong exit code -> still fails (rc is part of the assertion)
    assert not OBS.make_verify([obs], runner=lambda c, p: ("", "error: port range is empty\n", 0))(
        "x"
    ).passed


def test_contains_checks_the_stream_the_reference_used():
    # reference put the substring on STDERR -> a candidate emitting it on STDOUT must NOT pass
    obs = OBS.Observation(
        _probe(),
        "",
        _REF_STDERR,
        1,
        assertion={"expect_in": ["port range is empty"], "expect_rc": 1, "expect_stdout": None},
    )
    v = OBS.make_verify([obs], runner=lambda c, p: ("port range is empty\n", "", 1))  # wrong stream
    assert not v("x").passed


def test_rc_only_assertion():
    obs = OBS.Observation(
        _probe(("--version",)),
        "bore 0.5.0\n",
        "",
        0,
        assertion={"expect_in": [], "expect_rc": 0, "expect_stdout": None},
    )
    # any stdout, as long as rc==0 (the test only checks the exit code)
    assert OBS.make_verify([obs], runner=lambda c, p: ("anything\n", "", 0))("x").passed
    assert not OBS.make_verify([obs], runner=lambda c, p: ("", "", 3))("x").passed


def test_partial_substring_match_gives_gradient():
    # 2 of 3 required substrings present -> score between 0 and 1 (verified search can climb)
    obs = OBS.Observation(
        _probe(),
        "",
        "A B C\n",
        1,
        assertion={"expect_in": ["A", "B", "C"], "expect_rc": 1, "expect_stdout": None},
    )
    res = OBS.make_verify([obs], runner=lambda c, p: ("", "A B\n", 1))("x")  # missing C
    assert not res.passed
    assert 0.0 < res.score < 1.0
