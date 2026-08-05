"""Tests for scripts/corpus/corpus_embeddings.py -- the local semantic index cache.

Uses the same synthetic fixture style as test_determinex_corpus_api.py (fast, no live corpus,
no Ollama dependency for the pure-function tests below).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "corpus"))
import corpus_embeddings as ce  # noqa: E402


def _fixture() -> dict:
    """A key deliberately present in BOTH _topic_index and as a top-level entry -- the exact
    shape that caused the 2026-07-19 non-convergent embeddings-cache bug (see
    build_knowledge.embeddings_cache_nonconvergent_dup_key_bug_20260719)."""
    return {
        "_topic_index": {
            "BUILD_TOOLCHAIN": [
                {"key": "dup_key_entry", "summary": "short pointer summary"},
                {"key": "topic_only_key", "summary": "only lives in the topic index"},
            ],
        },
        "class_patterns": {
            "some_pattern": {"detect": "d", "fix": "f"},
        },
        "learned_classes": {
            "learned_1": {"detect": "d", "fix": "f", "verified": True},
        },
        "dup_key_entry": {"_doc": "the fuller top-level blob for the same key"},
        "solo_entry": "a plain top-level entry with no topic-index pointer",
    }


def test_entries_has_globally_unique_keys():
    """Before the fix, _entries() emitted 'dup_key_entry' twice (once from _topic_index with
    the short summary, once from the top-level scan with the fuller blob) -- two DIFFERENT-text
    rows sharing one cache key, which made the embeddings cache's hash-based skip-check
    non-convergent (see the corpus finding referenced above)."""
    entries = ce._entries(_fixture())
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys)), (
        f"duplicate keys found: {[k for k in keys if keys.count(k) > 1]}"
    )


def test_entries_merges_topic_and_toplevel_preferring_fuller_text():
    entries = ce._entries(_fixture())
    row = next(e for e in entries if e["key"] == "dup_key_entry")
    assert "fuller top-level blob" in row["text"]
    assert row["topic"] == "BUILD_TOOLCHAIN"  # real topic label, not the generic "entry" one


def test_entries_keeps_topic_only_key_when_no_toplevel_counterpart():
    entries = ce._entries(_fixture())
    row = next(e for e in entries if e["key"] == "topic_only_key")
    assert "only lives in the topic index" in row["text"]


def test_entries_namespaces_class_pattern_and_learned_class_keys():
    entries = ce._entries(_fixture())
    keys = {e["key"] for e in entries}
    assert "class_pattern::some_pattern" in keys
    assert "learned_class::learned_1" in keys


def test_semantic_search_returns_empty_without_a_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "CACHE_VEC", tmp_path / "does_not_exist.npy")
    monkeypatch.setattr(ce, "CACHE_META", tmp_path / "does_not_exist.meta.json")
    assert ce.semantic_search("anything") == []


def test_stats_reports_not_exists_without_a_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "CACHE_VEC", tmp_path / "nope.npy")
    monkeypatch.setattr(ce, "CACHE_META", tmp_path / "nope.meta.json")
    assert ce.stats() == {"exists": False}
