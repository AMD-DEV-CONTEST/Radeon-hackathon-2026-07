"""Tests for scripts/corpus/corpus_fts.py -- BM25 ranking via SQLite FTS5.

Same synthetic-fixture style as test_corpus_embeddings.py: no live corpus, no Ollama, no
network. The index is built into a tmp_path so nothing here touches the real
corpus/programbench/fts_index.sqlite3.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "corpus"))
import corpus_fts as fts  # noqa: E402


def _fixture() -> dict:
    """Entries chosen so ranking has a single defensible right answer.

    `underscore_key_target` exists to pin the specific defect this module was written for:
    determinex_corpus_api._tokens() uses [a-z0-9_]+, so a snake_case key is ONE token and a
    multi-word query can never intersect it. FTS5's unicode61 tokeniser splits on underscore.
    """
    return {
        "_topic_index": {
            "ORACLE_MECHANICS": [
                {"key": "provenance_restore_entry", "summary": "short pointer summary"},
            ],
        },
        "class_patterns": {
            "collection_cap": {
                "detect": "del items[400:] in conftest",
                "fix": "remove the collection cap and re-evaluate the full suite",
            },
        },
        "learned_classes": {},
        "provenance_restore_entry": (
            "provenance restore provenance restore provenance restore: the archive was "
            "restored after a provenance audit found upstream source builds"
        ),
        "underscore_key_target": "unrelated body text with no query words in it at all",
        "distractor_entry": "a document about something else entirely, mentioning restore once",
    }


@pytest.fixture()
def built_index(tmp_path, monkeypatch):
    monkeypatch.setattr(fts, "INDEX_PATH", tmp_path / "fts_index.sqlite3")
    result = fts.build_index(corpus=_fixture(), force=True)
    assert result["ok"], result
    return result


def test_fts5_is_available():
    """FTS5 is a compile-time SQLite option. If this fails the module correctly degrades to
    [], but the whole BM25 leg is inert -- worth knowing loudly rather than silently."""
    assert fts.fts5_available(), "SQLite built without FTS5; bm25_search will return []"


def test_build_indexes_every_entry(built_index):
    # 3 top-level entries + 1 class_pattern. The _topic_index row for
    # provenance_restore_entry MERGES into that existing top-level key rather than adding a
    # second row -- corpus_embeddings._entries() dedupes it deliberately (the 2026-07-19
    # cache-collision fix), and reusing that function is what keeps the key spaces aligned.
    assert built_index["indexed"] == 4
    assert built_index["rebuilt"] is True


def test_rebuild_is_skipped_when_fingerprint_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(fts, "INDEX_PATH", tmp_path / "fts_index.sqlite3")
    first = fts.build_index(corpus=_fixture(), force=True)
    second = fts.build_index(corpus=_fixture())
    assert first["rebuilt"] is True
    assert second["rebuilt"] is False
    assert first["fingerprint"] == second["fingerprint"]


def test_corpus_change_invalidates_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(fts, "INDEX_PATH", tmp_path / "fts_index.sqlite3")
    fts.build_index(corpus=_fixture(), force=True)
    changed = dict(_fixture())
    changed["brand_new_entry"] = "text that did not exist before"
    assert fts.build_index(corpus=changed)["rebuilt"] is True


def test_term_frequency_beats_single_mention(built_index):
    """The core BM25 property token-overlap lacks: the entry that is ABOUT the query
    outranks one that merely mentions a query word once."""
    hits = fts.bm25_search("provenance restore", k=5, auto_build=False)
    assert hits, "expected hits for a query whose terms are in the corpus"
    assert hits[0]["key"] == "provenance_restore_entry"
    keys = [h["key"] for h in hits]
    assert keys.index("provenance_restore_entry") < keys.index("distractor_entry")


def test_snake_case_key_words_are_matchable(built_index):
    """The defect this module exists to close: query words that appear ONLY inside a
    snake_case key. determinex_corpus_api._tokens() cannot match these at all."""
    hits = fts.bm25_search("underscore key target", k=5, auto_build=False)
    assert [h["key"] for h in hits][:1] == ["underscore_key_target"]


def test_scores_are_normalised_descending(built_index):
    hits = fts.bm25_search("provenance restore collection", k=5, auto_build=False)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == pytest.approx(1.0)
    assert all(0.0 < s <= 1.0 for s in scores)


@pytest.mark.parametrize(
    "query",
    ['fts5 "unbalanced quote', "wildcard*", "NEAR(a b", "col:umn", "a AND", "-minus", "((("],
)
def test_fts5_operator_syntax_cannot_reach_the_engine(built_index, query):
    """FTS5 MATCH treats -, ", *, :, ^ and parens as operators, so raw user text is a syntax
    error (or worse) waiting to happen. _safe_match_query strips to quoted word tokens."""
    hits = fts.bm25_search(query, k=5, auto_build=False)
    assert isinstance(hits, list)  # no exception, no traceback


def test_empty_and_stopword_only_queries_return_empty(built_index):
    for query in ("", "   ", "!!!", "a"):
        assert fts.bm25_search(query, k=5, auto_build=False) == []


def test_missing_index_returns_empty_not_raises(tmp_path, monkeypatch):
    """Degradation contract: callers (hybrid_search) treat BM25 as best-effort."""
    monkeypatch.setattr(fts, "INDEX_PATH", tmp_path / "does_not_exist.sqlite3")
    assert fts.bm25_search("provenance", k=5, auto_build=False) == []


def test_hits_match_semantic_search_shape(built_index):
    """hybrid_search blends these two by key, so the dict shape must agree with
    corpus_embeddings.semantic_search()."""
    hit = fts.bm25_search("provenance restore", k=1, auto_build=False)[0]
    assert set(hit) == {"key", "score", "snippet", "topic"}


def test_stats_reports_built_and_fresh(built_index, monkeypatch):
    # stats() re-derives the fingerprint from ce._entries() with no corpus arg, which would
    # load the REAL corpus and report this fixture index as stale. Bind the ORIGINAL function
    # before patching -- a lambda that calls the patched attribute recurses into itself.
    original = fts.ce._entries
    monkeypatch.setattr(fts.ce, "_entries", lambda corpus=None: original(_fixture()))
    s = fts.stats()
    assert s["available"] is True
    assert s["built"] is True
    assert s["indexed"] == 4
    assert s["stale"] is False


def test_stats_detects_a_stale_index(built_index, monkeypatch):
    """The fingerprint's whole purpose: notice the corpus moved out from under the index."""
    original = fts.ce._entries
    changed = dict(_fixture())
    changed["added_after_the_build"] = "new text"
    monkeypatch.setattr(fts.ce, "_entries", lambda corpus=None: original(changed))
    assert fts.stats()["stale"] is True
