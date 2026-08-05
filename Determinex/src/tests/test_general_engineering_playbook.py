"""Tests for corpus/general_engineering_playbook.json and its wiring into determinex_corpus_api.

Distilled 2026-07-27 per Ryan's direct instruction: the ProgramBench campaign's real value to
END USERS is the transferable engineering lessons underneath its tool-specific framing, not the
campaign's own bulk artifacts (19.86 GB of PB-specific scaffolding/archives that stay non-gating
per RELEASE_CHECKLIST.md and never help a user on their own project). This file is that
distillation: real class_patterns from build_knowledge.json, reframed as general principles.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_corpus_api as api  # noqa: E402

PLAYBOOK_PATH = (
    Path(__file__).resolve().parent.parent / "corpus" / "general_engineering_playbook.json"
)


def test_playbook_file_exists_and_parses():
    assert PLAYBOOK_PATH.exists(), f"missing {PLAYBOOK_PATH}"
    data = json.loads(PLAYBOOK_PATH.read_text(encoding="utf-8"))
    assert isinstance(data.get("entries"), list)
    assert len(data["entries"]) >= 10


def test_every_entry_has_required_fields_and_traces_to_a_real_source():
    """Each entry must be traceable back to the class_pattern it was distilled from -- this is
    what keeps the playbook honest (a real distillation, not fabricated advice) and lets a
    reader go verify the original technical detail."""
    real_patterns = set(api.class_patterns().keys())
    pb = api.general_engineering_playbook()
    assert len(pb) >= 10
    for entry_id, entry in pb.items():
        for field in ("id", "category", "lesson", "why_it_generalizes", "source_pattern"):
            assert entry.get(field), f"{entry_id} missing/empty required field {field!r}"
        assert entry["id"] == entry_id
        assert entry["source_pattern"] in real_patterns, (
            f"{entry_id} claims source_pattern={entry['source_pattern']!r}, "
            f"which is not a real key in build_knowledge.json's class_patterns"
        )


def test_no_entry_names_a_specific_programbench_tool_in_its_lesson():
    """The whole point of distillation: the LESSON text itself must read as general advice, not
    a PB tool name. (source_pattern legitimately points at a PB-specific key; the lesson/
    why_it_generalizes prose must not.)"""
    # A conservative sample of literal PB tool names that appear as `applies_to` entries
    # in the source class_patterns this playbook draws from.
    pb_tool_markers = (
        "gowsdl",
        "pixterm",
        "felix",
        "duckdb",
        "ffmpeg",
        "brotli",
        "chroma",
        "serpl",
        "jplot",
        "go-critic",
        "eva ",
    )
    pb = api.general_engineering_playbook()
    for entry_id, entry in pb.items():
        prose = f"{entry['lesson']} {entry['why_it_generalizes']}".lower()
        hit = [m for m in pb_tool_markers if m in prose]
        assert not hit, f"{entry_id} names a PB-specific tool in its generalized prose: {hit}"


def test_general_playbook_is_queryable_via_search():
    """The whole reason this is wired into corpus_api rather than left as a standalone doc."""
    hits = api.search("test collection silently truncated fewer tests run than expected")
    sources = {h.source for h in hits}
    assert "general_playbook" in sources, (
        "expected at least one general_playbook hit for a query matching "
        "collection_cap_hides_untested_majority"
    )


def test_general_playbook_not_searched_against_an_explicit_scoped_corpus():
    """search()/hybrid_search() must answer from the SUPPLIED corpus only when one is given --
    the playbook file lives outside build_knowledge.json entirely, so pulling it in
    unconditionally would be the exact global-index-contamination bug fixed for BM25/embeddings
    in hybrid_search (see test_determinex_corpus_api.py's contamination regression test)."""
    fixture = {"_topic_index": {}, "class_patterns": {}, "learned_classes": {}}
    hits = api.search("test collection silently truncated", corpus=fixture)
    assert all(h.source != "general_playbook" for h in hits)


def test_missing_playbook_file_degrades_to_empty_not_raise():
    result = api.general_engineering_playbook(path=Path("does/not/exist.json"))
    assert result == {}


def test_malformed_playbook_file_degrades_to_empty_not_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert api.general_engineering_playbook(path=bad) == {}
