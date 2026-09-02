"""tests/test_determinex_db_import_evals.py — cmd_import_evals canonical wiring.

determinex_db.py's cmd_import_evals() used to hand-roll its own
test_results[].get("status")=="passed" loop right next to
determinex_eval_report.py, the canonical eval-JSON reader whose own
docstring explicitly warns against exactly that kind of re-derivation
(it's how the failed-vs-failure counting bug kept recurring). Converted
2026-07-20 to route through ER.load() instead.
"""

from __future__ import annotations

import glob as glob_module
import json
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_db as db  # noqa: E402


def test_import_evals_uses_canonical_loader_and_lands_correct_row(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", tmp_path / "test.duckdb")

    ej = tmp_path / "fake__tool1" / "result.eval.json"
    ej.parent.mkdir()
    ej.write_text(
        json.dumps(
            {
                "test_results": [
                    {"name": "tests.test_a::test_one", "status": "passed"},
                    {"name": "tests.test_a::test_two", "status": "passed"},
                    {"name": "tests.test_a::test_three", "status": "failure"},
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(glob_module, "glob", lambda pattern: [str(ej)])

    db.cmd_import_evals(types.SimpleNamespace())

    c = db.conn()
    rows = c.execute("SELECT instance_id, passed, total, pct FROM evals").fetchall()
    c.close()

    assert rows == [("fake__tool1", 2, 3, 66.67)]


def test_import_evals_skips_empty_test_results(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", tmp_path / "test.duckdb")

    ej = tmp_path / "fake__empty" / "result.eval.json"
    ej.parent.mkdir()
    ej.write_text(json.dumps({"test_results": []}), encoding="utf-8")

    monkeypatch.setattr(glob_module, "glob", lambda pattern: [str(ej)])

    db.cmd_import_evals(types.SimpleNamespace())

    c = db.conn()
    rows = c.execute("SELECT instance_id FROM evals").fetchall()
    c.close()
    assert rows == []


def test_import_evals_skips_unreadable_file(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", tmp_path / "test.duckdb")

    ej = tmp_path / "fake__broken" / "result.eval.json"
    ej.parent.mkdir()
    ej.write_text("{not valid json", encoding="utf-8")

    monkeypatch.setattr(glob_module, "glob", lambda pattern: [str(ej)])

    # Must not raise -- the canonical loader's own exception path is caught
    # the same way the old bare json.loads() try/except was.
    db.cmd_import_evals(types.SimpleNamespace())

    c = db.conn()
    rows = c.execute("SELECT instance_id FROM evals").fetchall()
    c.close()
    assert rows == []
