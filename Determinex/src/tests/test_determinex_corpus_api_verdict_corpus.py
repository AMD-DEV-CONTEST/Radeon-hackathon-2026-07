"""tests/test_determinex_corpus_api_verdict_corpus.py — streaming access to the
9GB pb_verdict_corpus.jsonl (~591K lines, mixed conversation/verdict schema).

Found 2026-07-20: this file (every PB gate result feeds it -- "rejects are
training signal, not waste") had NO query surface through
determinex_corpus_api at all. Full semantic embedding at that scale isn't
attempted (days of Ollama calls, a real vector-DB problem, not a numpy-cache
one) -- these two functions instead stream the file line-by-line so it's at
least discoverable and literal-text-searchable, without ever loading the
9GB into memory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_corpus_api as api  # noqa: E402


def _write_fixture(tmp_path: Path) -> Path:
    p = tmp_path / "fake_verdict.jsonl"
    rows = [
        {"conversations": [{"from": "system", "value": "x"}]},
        {
            "slug": "stathissideris__ditaa.f2286c4",
            "verdict": "lock",
            "root_cause": "SyntaxError",
            "fix_summary": "Remove comma",
        },
        {
            "slug": "ast-grep__ast-grep",
            "verdict": "bounce",
            "root_cause": "mixed real-fail",
            "fix_summary": "apply pattern",
        },
        {"conversations": [{"from": "human", "value": "y"}]},
        {
            "slug": "oppiliappan__eva.41ae245",
            "verdict": "lock",
            "root_cause": "tarball cap",
            "fix_summary": "rebuild",
        },
    ]
    text = "\n".join(json.dumps(r) for r in rows)
    text += "\nnot valid json at all\n"  # malformed line must not crash parsing
    text += "\n"  # trailing blank line must be skipped, not counted as a row
    p.write_text(text, encoding="utf-8")
    return p


def test_verdict_corpus_stats_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "VERDICT_CORPUS_PATH", tmp_path / "nope.jsonl")
    s = api.verdict_corpus_stats()
    assert s.exists is False
    assert s.total_lines == 0


def test_verdict_corpus_stats_counts_correctly(tmp_path, monkeypatch):
    p = _write_fixture(tmp_path)
    monkeypatch.setattr(api, "VERDICT_CORPUS_PATH", p)
    s = api.verdict_corpus_stats()
    assert s.exists is True
    assert s.conversation_records == 2
    assert s.verdict_counts == {"lock": 2, "bounce": 1}
    assert s.file_bytes > 0


def test_verdict_corpus_stats_respects_max_lines(tmp_path, monkeypatch):
    p = _write_fixture(tmp_path)
    monkeypatch.setattr(api, "VERDICT_CORPUS_PATH", p)
    s = api.verdict_corpus_stats(max_lines=2)
    assert s.total_lines == 2


def test_verdict_corpus_grep_finds_real_match(tmp_path, monkeypatch):
    p = _write_fixture(tmp_path)
    monkeypatch.setattr(api, "VERDICT_CORPUS_PATH", p)
    hits = api.verdict_corpus_grep("ditaa", limit=5)
    assert len(hits) == 1
    assert hits[0]["slug"] == "stathissideris__ditaa.f2286c4"


def test_verdict_corpus_grep_skips_conversation_records(tmp_path, monkeypatch):
    """A query matching text inside a "conversations" record must not be
    returned -- grep only surfaces verdict-shaped rows."""
    p = tmp_path / "conv_only.jsonl"
    p.write_text(
        json.dumps({"conversations": [{"from": "human", "value": "mentions ditaa here"}]}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "VERDICT_CORPUS_PATH", p)
    hits = api.verdict_corpus_grep("ditaa", limit=5)
    assert hits == []


def test_verdict_corpus_grep_respects_limit(tmp_path, monkeypatch):
    p = tmp_path / "many_locks.jsonl"
    rows = [
        {"slug": f"tool{i}", "verdict": "lock", "root_cause": "x", "fix_summary": "y"}
        for i in range(10)
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "VERDICT_CORPUS_PATH", p)
    hits = api.verdict_corpus_grep("lock", limit=3)
    assert len(hits) == 3


def test_verdict_corpus_grep_malformed_lines_do_not_crash(tmp_path, monkeypatch):
    p = _write_fixture(tmp_path)
    monkeypatch.setattr(api, "VERDICT_CORPUS_PATH", p)
    # the fixture includes a "not valid json at all" line containing neither
    # query term -- exercise a query that would have to scan past it
    hits = api.verdict_corpus_grep("eva.41ae245", limit=5)
    assert len(hits) == 1
    assert hits[0]["slug"] == "oppiliappan__eva.41ae245"
