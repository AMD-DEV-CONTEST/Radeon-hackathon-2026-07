"""tests/test_determinex_eval_report.py — the canonical eval-JSON reader.

determinex_eval_report.py is the single place that understands ProgramBench
eval JSON (status vocabulary, bidir dedup, score formula) -- every other
script that needs a score should route through load() rather than
re-deriving test_results parsing. Converted to real pydantic models
2026-07-20 (TestResult/FailRecord/EvalReport were plain dataclasses with
zero validation); this covers the real-data path plus the new validated
WAL/JSON boundary at TestResult.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_eval_report as ER  # noqa: E402


def _write(tmp_path: Path, test_results: list[dict]) -> Path:
    p = tmp_path / "eval_report.json"
    p.write_text(json.dumps({"test_results": test_results}), encoding="utf-8")
    return p


def test_all_passed_is_a_lock(tmp_path):
    p = _write(
        tmp_path,
        [
            {"name": "tests.test_a::test_one", "status": "passed"},
            {"name": "tests.test_a::test_two", "status": "passed"},
        ],
    )
    rep = ER.load(p)
    assert rep.total == 2
    assert rep.passed == 2
    assert rep.not_run == 0
    assert rep.is_lock is True
    assert rep.score == 1.0
    assert rep.failures == []


def test_not_run_blocks_lock(tmp_path):
    p = _write(
        tmp_path,
        [
            {"name": "tests.test_a::test_one", "status": "passed"},
            {"name": "tests.test_a::test_two", "status": "not_run"},
        ],
    )
    rep = ER.load(p)
    assert rep.not_run == 1
    assert rep.is_lock is False


def test_failure_produces_parsed_fail_record(tmp_path):
    p = _write(
        tmp_path,
        [
            {
                "name": "tests.test_a::test_broken",
                "status": "failure",
                "extra": {
                    "text": (
                        "CompletedProcess(args=['./executable', '-x'], "
                        "returncode=1) assert returncode == 0"
                    )
                },
            },
        ],
    )
    rep = ER.load(p)
    assert len(rep.failures) == 1
    f = rep.failures[0]
    assert isinstance(f, ER.FailRecord)
    # _bare() only strips the dot-separated namespace prefix, not "::" --
    # "tests.test_a::test_broken".split(".")[-1] == "test_a::test_broken"
    assert f.short == "test_a::test_broken"
    assert f.argv == ["./executable", "-x"]
    assert f.returncode_actual == 1
    assert f.expect_rc == 0


def test_skipped_does_not_produce_a_failure(tmp_path):
    p = _write(
        tmp_path,
        [
            {"name": "tests.test_a::test_skipped_one", "status": "skipped"},
        ],
    )
    rep = ER.load(p)
    assert rep.failures == []
    assert rep.counts.get("skipped") == 1


def test_bidirectional_dedup_counts_unique_once(tmp_path):
    """eval.tests.* and tests.* namespaces double-count the same logical
    test -- unique_total/unique_passed should collapse them."""
    p = _write(
        tmp_path,
        [
            {"name": "eval.tests.test_a::test_one", "status": "passed"},
            {"name": "tests.test_a::test_one", "status": "passed"},
        ],
    )
    rep = ER.load(p)
    assert rep.total == 2  # raw count, bidir-inflated
    assert rep.unique_total == 1  # deduplicated


def test_malformed_entry_logged_not_crashed(tmp_path, capsys):
    """A test_results entry with a wrong-typed name must not crash load() --
    it gets validated, logged, and treated as an empty/failed record."""
    p = _write(
        tmp_path,
        [
            {"name": "tests.test_a::test_ok", "status": "passed"},
            {"name": 12345, "status": "error"},  # malformed: name should be str
        ],
    )
    rep = ER.load(p)
    assert rep.total == 2
    assert rep.passed == 1
    out = capsys.readouterr().out
    assert "malformed test_results entry" in out


def test_extra_field_any_type_still_stringified(tmp_path):
    """extra is deliberately typed as Any (not dict|str): the original bare
    .get() stringified whatever it found there, and a validated-but-narrow
    type would reject legitimate-if-unusual harness output that the old
    code handled fine."""
    p = _write(
        tmp_path,
        [
            {"name": "tests.test_a::test_weird", "status": "failure", "extra": 12345},
        ],
    )
    rep = ER.load(p)
    assert len(rep.failures) == 1
    assert rep.failures[0].text == "12345"


def test_load_against_real_locked_eval_report():
    """Sanity check against a real archived ProgramBench eval report, not
    just synthetic fixtures."""
    real = (
        _ROOT
        / "corpus"
        / "programbench"
        / "locked"
        / "abishekvashok__cmatrix.5c082c6"
        / "eval_report.json"
    )
    if not real.is_file():
        pytest.skip("archived eval_report.json not present in this checkout")
    rep = ER.load(real)
    assert rep.total > 0
    assert rep.passed == rep.total  # this specific archive is a locked 100%
    assert rep.is_lock is True


def test_model_dump_json_serializable(tmp_path):
    """main()'s --json path calls model_dump(); must round-trip through
    json.dumps without error (pydantic's dump must be plain-JSON-safe)."""
    p = _write(tmp_path, [{"name": "tests.test_a::test_one", "status": "passed"}])
    rep = ER.load(p)
    dumped = rep.model_dump()
    assert json.dumps(dumped)  # raises if not serializable
