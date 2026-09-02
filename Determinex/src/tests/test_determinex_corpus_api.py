"""Tests for determinex_corpus_api.py -- the read-only corpus query surface.

Uses a small synthetic corpus fixture (not the real 2.5MB build_knowledge.json) so these tests
stay fast and don't silently pass/fail based on the live corpus's current contents.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_corpus_api as api  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live_ollama(monkeypatch):
    """ask()/hybrid_search() now blend in semantic_search() (2026-07-19), which -- if the real
    embeddings_cache.npy/.meta.json happen to exist on disk, as they do in this checkout --
    reaches out to a live local Ollama endpoint. That silently broke this file's own stated
    contract ("fast... no Ollama dependency"): a full run went from ~4s to ~48s and became
    dependent on Ollama actually being up. Neutralize it here so semantic_search always behaves
    exactly like "no cache present" (empty list), which is hybrid_search's own documented
    graceful-degradation path -- these tests verify search()/ask() ranking logic, not the
    embeddings layer (that has its own tests in test_corpus_embeddings.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "corpus"))
    import corpus_embeddings

    monkeypatch.setattr(corpus_embeddings, "semantic_search", lambda *a, **k: [])


def _fixture() -> dict:
    return {
        "_topic_index": {
            "BUILD_TOOLCHAIN": [
                {"key": "go_toolchain_note", "summary": "go.mod version mismatches cause rc=127"},
                {"key": "no_summary_entry", "summary": ""},
                {"key": "pb_only_open_item", "summary": ""},
            ],
            "HACKATHON_CAMPAIGN": [
                {"key": "HACKATHON_LEVER_MAP_2026_07_13", "summary": "lever catalog"},
            ],
        },
        "class_patterns": {
            "go_x_toolchain": {
                "detect": "go.mod declares go <1.24",
                "symptom": "build.err requires go >= 1.24.0",
                "fix": "export GOTOOLCHAIN=go1.24.1",
            },
        },
        "learned_classes": {
            "learned_abc123": {
                "detect": "rust cargo build fails offline",
                "fix": "vendor deps with cargo vendor",
                "source_tool": "some_tool",
                "verified": True,
                "learned": "2026-07-16",
                "uses": 0,
            },
            "learned_unverified_should_never_exist": {
                "detect": "something",
                "fix": "something",
                "verified": False,
                "learned": "2026-07-16",
                "uses": 0,
            },
        },
        "learned_classes_quarantine_20260716": {
            "_doc": "quarantined batch",
            "count": 2,
            "entries": {"absorbed_x": {}, "absorbed_y": {}},
        },
        "no_summary_entry": "a plain string top-level entry about rc=127 build failures",
        "some_other_entry": {"_doc": "unrelated entry about locale timezone fixes"},
        "HACKATHON_LEVER_MAP_2026_07_13": (
            "=== NOT YET BUILT -- HIGHEST PRIORITY NEXT TIME ===\n"
            "- Weight repacking for 3x3 convs, OC-blocked, pure VPU.\n"
            "=== HIGH RISK, UNRESOLVED ===\n"
            "- Tensor-unit acceleration produces an accuracy bug, root cause never found."
        ),
        "pb_only_open_item": "this entry has a real TODO: finish the go-toolchain shim",
        "cross_ref_source": "See no_summary_entry for the real fix. Also see does_not_exist_entry.",
        "correction_entry": "CORRECTED 2026-06-30: the earlier claim in old_entry was WRONG and is now demoted.",
    }


def test_topics_lists_all_topic_index_keys():
    assert api.topics(_fixture()) == ["BUILD_TOOLCHAIN", "HACKATHON_CAMPAIGN"]


def test_topic_entries_falls_back_to_resolved_entry_when_summary_blank():
    rows = api.topic_entries("BUILD_TOOLCHAIN", _fixture())
    assert rows[0]["summary"] == "go.mod version mismatches cause rc=127"
    # the second row's index summary is blank -> resolved from the top-level string entry
    assert "rc=127" in rows[1]["summary"]


def test_get_entry_resolves_any_top_level_key():
    assert api.get_entry("some_other_entry", _fixture())["_doc"].startswith("unrelated")
    assert api.get_entry("does_not_exist", _fixture()) is None


def test_class_patterns_and_get_class_pattern():
    cp = api.class_patterns(_fixture())
    assert "go_x_toolchain" in cp
    assert api.get_class_pattern("go_x_toolchain", _fixture())["fix"].startswith("export")
    assert api.get_class_pattern("nope", _fixture()) is None


def test_learned_classes_verified_only_by_default():
    lc = api.learned_classes(corpus=_fixture())
    assert list(lc.keys()) == ["learned_abc123"]  # the unverified row is excluded by default


def test_learned_classes_verified_only_false_shows_everything():
    lc = api.learned_classes(verified_only=False, corpus=_fixture())
    assert len(lc) == 2


def test_stats_counts_match_fixture():
    s = api.stats(_fixture())
    assert s.class_pattern_count == 1
    assert s.learned_class_count == 2
    assert s.learned_class_verified_count == 1
    assert s.quarantined_keys == ["learned_classes_quarantine_20260716"]
    assert s.quarantined_count == 2
    assert "BUILD_TOOLCHAIN" in s.topics


def test_search_ranks_by_token_overlap_and_covers_all_sections():
    hits = api.search("rc=127 go toolchain", corpus=_fixture())
    sources = {h.source for h in hits}
    assert "topic" in sources
    assert "class_pattern" in sources
    assert "entry" in sources
    # highest-scoring hit should be the one with the most token overlap
    assert hits[0].score >= hits[-1].score


def test_search_never_surfaces_quarantined_or_unverified_entries():
    hits = api.search("something absorbed", corpus=_fixture())
    assert all(
        h.key not in ("absorbed_x", "absorbed_y", "learned_unverified_should_never_exist")
        for h in hits
    )


def test_search_empty_query_returns_nothing():
    assert api.search("", corpus=_fixture()) == []


def test_maturity_report_flags_empty_flywheel_and_quarantine():
    r = api.maturity_report(corpus=_fixture())
    # fixture has 1 verified learned_class -> flywheel is NOT empty here
    assert r.flywheel_is_empty is False
    # Renamed from quarantine_pending_reabsorption 2026-07-28: those entries were
    # REJECTED, not queued (0 verified and 0 ever used at quarantine; the 2026-07-18
    # salvage already readmitted the 234 that passed a quality gate). The old name
    # read as outstanding work and invited re-absorbing gated-out material.
    assert r.quarantined_rejected == 2


def test_maturity_report_keeps_the_old_quarantine_key_for_readers():
    """The rename must not break existing consumers of the JSON, so to_dict() emits
    both keys plus a note saying which reading is correct."""
    d = api.maturity_report(corpus=_fixture()).to_dict()
    assert d["quarantined_rejected"] == d["quarantine_pending_reabsorption"] == 2
    assert "rejected, not queued" in d["quarantine_note"]


def test_maturity_report_finds_real_markers_not_fabricated():
    """Every open_item must be a literal substring match the caller can verify
    themselves -- this is the whole point (grounded, not an LLM guessing at gaps)."""
    r = api.maturity_report(corpus=_fixture())
    keys_found = {i.key for i in r.open_items}
    assert "HACKATHON_LEVER_MAP_2026_07_13" in keys_found
    assert "pb_only_open_item" in keys_found
    for item in r.open_items:
        assert item.marker in item.snippet or item.snippet  # snippet is centered on the real match


def test_maturity_report_topic_filter_scopes_to_hackathon_only():
    r = api.maturity_report(topic_filter="HACKATHON_CAMPAIGN", corpus=_fixture())
    keys_found = {i.key for i in r.open_items}
    assert "HACKATHON_LEVER_MAP_2026_07_13" in keys_found
    # the PB-only TODO entry is NOT tagged HACKATHON_CAMPAIGN in the topic index -> excluded
    assert "pb_only_open_item" not in keys_found


def test_maturity_report_never_scans_quarantine_or_learned_classes_raw():
    r = api.maturity_report(corpus=_fixture())
    assert all(not i.key.startswith("learned_classes_quarantine_") for i in r.open_items)
    assert all(i.key not in ("learned_classes", "class_patterns") for i in r.open_items)


def test_maturity_report_to_dict_is_json_serializable():
    import json

    blob = json.dumps(api.maturity_report(corpus=_fixture()).to_dict())
    assert "open_items" in blob


def test_extract_cross_references_finds_real_see_mentions():
    refs = api.extract_cross_references(_fixture())
    targets = {(r.from_key, r.to_key) for r in refs}
    assert ("cross_ref_source", "no_summary_entry") in targets
    assert ("cross_ref_source", "does_not_exist_entry") in targets


def test_extract_cross_references_flags_existence_correctly():
    refs = api.extract_cross_references(_fixture())
    by_target = {r.to_key: r.to_key_exists for r in refs}
    assert by_target["no_summary_entry"] is True
    assert by_target["does_not_exist_entry"] is False


def test_related_entries_both_directions():
    rel = api.related_entries("no_summary_entry", _fixture())
    assert "cross_ref_source" in rel["inbound"]
    assert rel["outbound"] == []  # no_summary_entry has no outbound "see X" itself


def test_related_entries_unknown_key_returns_empty_not_error():
    rel = api.related_entries("totally_unknown_key", _fixture())
    assert rel == {"outbound": [], "inbound": []}


def test_find_superseded_claims_catches_real_correction_language():
    flags = api.find_superseded_claims(_fixture())
    keys_found = {f.key for f in flags}
    assert "correction_entry" in keys_found
    markers_found = {f.marker for f in flags if f.key == "correction_entry"}
    assert "CORRECTED" in markers_found
    assert "WRONG" in markers_found
    assert "demoted" in markers_found


def test_find_superseded_claims_never_scans_quarantine_or_registries():
    flags = api.find_superseded_claims(_fixture())
    assert all(not f.key.startswith("learned_classes_quarantine_") for f in flags)
    assert all(f.key not in ("learned_classes", "class_patterns") for f in flags)


def test_ask_composes_search_related_and_supersession_warnings():
    fixture = _fixture()
    # search for something that should surface both correction_entry and cross_ref_source
    r = api.ask("corrected wrong demoted claim", fixture)
    assert r.query == "corrected wrong demoted claim"
    assert any("correction_entry" in w for w in r.warnings)


def test_ask_no_warnings_when_top_hits_are_clean():
    r = api.ask("go build target rc=127", _fixture())
    assert not any("correction_entry" in w for w in r.warnings)


def test_ask_empty_query_returns_no_hits_no_crash():
    r = api.ask("", _fixture())
    assert r.hits == []
    assert r.top_hit_related == {"outbound": [], "inbound": []}
    assert r.warnings == []


def test_ask_to_dict_is_json_serializable():
    import json

    blob = json.dumps(api.ask("go toolchain", _fixture()).to_dict())
    assert "warnings" in blob


def test_live_ask_surfaces_known_invalidation_for_programbench_lock_count():
    """A REAL correctness check against the live corpus, not shape-only: this exact query
    is known (from the session's own history) to have a top hit describing the 2026-06-30
    provenance invalidation, plus at least one supersession warning in the result set."""
    r = api.ask("programbench 65 locks strict count")
    assert len(r.hits) > 0
    assert any("invalidat" in h.key.lower() or "methodology" in h.key.lower() for h in r.hits[:5])
    assert len(r.warnings) > 0


def test_timeline_sorts_chronologically_and_reads_key_dates():
    entries = api.timeline(corpus=_fixture())
    dates = [e.date for e in entries]
    assert dates == sorted(dates)
    keys = {e.key for e in entries}
    # every fixture key with a YYYY_MM_DD date should appear
    assert "correction_entry" not in keys  # no date in this key -- correctly excluded
    assert any(e.key == "HACKATHON_LEVER_MAP_2026_07_13" for e in entries)


def test_timeline_extracts_correct_iso_date_from_key():
    entries = api.timeline(corpus=_fixture())
    hit = next(e for e in entries if e.key == "HACKATHON_LEVER_MAP_2026_07_13")
    assert hit.date == "2026-07-13"
    assert hit.topic == "HACKATHON_CAMPAIGN"


def test_timeline_topic_filter():
    entries = api.timeline(topic_filter="HACKATHON_CAMPAIGN", corpus=_fixture())
    assert all(e.topic == "HACKATHON_CAMPAIGN" for e in entries)
    assert len(entries) == 1  # only HACKATHON_LEVER_MAP_2026_07_13 is tagged to this topic


def test_timeline_never_scans_quarantine_or_registries():
    entries = api.timeline(corpus=_fixture())
    assert all(not e.key.startswith("learned_classes_quarantine_") for e in entries)
    assert all(e.key not in ("learned_classes", "class_patterns") for e in entries)


def test_live_timeline_runs_without_error():
    """Smoke test against the REAL build_knowledge.json."""
    entries = api.timeline()
    assert isinstance(entries, list) and len(entries) > 0
    dates = [e.date for e in entries]
    assert dates == sorted(dates)


def test_live_cross_references_and_supersession_run_without_error():
    """Smoke test against the REAL build_knowledge.json."""
    refs = api.extract_cross_references()
    assert isinstance(refs, list) and len(refs) > 0
    flags = api.find_superseded_claims()
    assert isinstance(flags, list)


def test_live_maturity_report_runs_without_error():
    """Smoke test against the REAL build_knowledge.json."""
    r = api.maturity_report()
    assert isinstance(r.open_items, list)
    r_hackathon = api.maturity_report(topic_filter="HACKATHON_CAMPAIGN")
    assert len(r_hackathon.open_items) <= len(r.open_items)


def test_live_corpus_loads_and_searches_without_error():
    """Smoke test against the REAL build_knowledge.json -- catches schema drift early."""
    corpus = api.load_corpus()
    s = api.stats(corpus)
    assert s.total_top_level_entries > 0
    hits = api.search("go build target rc=127", corpus=corpus)
    assert isinstance(hits, list)


def _canonical_fixture() -> dict:
    return {
        "official_task_count": 2,
        "tasks": [
            {
                "id": "isona__dirble.e2dea9f",
                "repository": "Isona/dirble",
                "commit": "e2dea9f16dee2ba208b455f6fa61ca109bf9de2b",
                "language": "rs",
                "difficulty": "medium",
                "total_tests": 1108,
                "expected_active_tests": 715,
                "source_citation": {"task_yaml": "T:/fake/isona__dirble.e2dea9f/task.yaml:1"},
            },
            {
                "id": "chmln__handlr.90e78ba",
                "repository": "chmln/handlr",
                "commit": "90e78ba92d0355cb523abf268858f3123fd81238",
                "language": "rs",
                "difficulty": "medium",
                "total_tests": 908,
                "expected_active_tests": 722,
                "source_citation": {"task_yaml": "T:/fake/chmln__handlr.90e78ba/task.yaml:1"},
            },
        ],
    }


def test_task_provenance_matches_by_full_id():
    r = api.task_provenance("isona__dirble.e2dea9f", _canonical_fixture())
    assert r is not None
    assert r.repository == "Isona/dirble"
    assert r.commit == "e2dea9f16dee2ba208b455f6fa61ca109bf9de2b"
    assert r.match_field == "id"


def test_task_provenance_matches_by_bare_slug():
    # "dirble" is both the bare slug AND the repo name for this task -- repo_name is
    # checked first, which is still a correct match (the fixture's dirble entry has no
    # __ prefix collision to actually exercise the slug_base-only branch).
    r = api.task_provenance("dirble", _canonical_fixture())
    assert r is not None
    assert r.id == "isona__dirble.e2dea9f"
    assert r.match_field in ("repo_name", "slug_base")


def test_task_provenance_matches_by_repo_name_only():
    r = api.task_provenance("handlr", _canonical_fixture())
    assert r is not None
    assert r.id == "chmln__handlr.90e78ba"
    assert r.match_field == "repo_name"


def test_task_provenance_matches_by_full_owner_slash_repo():
    r = api.task_provenance("chmln/handlr", _canonical_fixture())
    assert r is not None
    assert r.match_field == "repo_full"


def test_task_provenance_is_case_insensitive():
    r = api.task_provenance("DIRBLE", _canonical_fixture())
    assert r is not None
    assert r.id == "isona__dirble.e2dea9f"


def test_task_provenance_unknown_query_returns_none_not_error():
    assert api.task_provenance("totally-not-a-tool", _canonical_fixture()) is None


def test_task_provenance_empty_canonical_returns_none():
    assert api.task_provenance("dirble", {"official_task_count": 0, "tasks": []}) is None


def test_load_canonical_tasks_missing_file_returns_empty_shape(tmp_path):
    empty = api.load_canonical_tasks(tmp_path / "does_not_exist.json")
    assert empty == {"official_task_count": 0, "tasks": []}


def test_live_task_provenance_finds_real_dirble_entry():
    """Smoke test against the REAL canonical_tasks.json -- this is the exact fact that was
    previously re-derived by hand-grepping T:/Dev/ProgramBench instead of being queried here."""
    r = api.task_provenance("isona__dirble.e2dea9f")
    assert r is not None
    assert r.repository == "Isona/dirble"
    assert r.commit == "e2dea9f16dee2ba208b455f6fa61ca109bf9de2b"


def test_live_tool_status_federates_dirble_across_stores():
    """The federated per-tool view must join provenance + eval_index (+ lock/capability when
    present) for a bare slug -- one query instead of opening 6 files by hand."""
    d = api.tool_status("dirble")
    assert d["provenance"] is not None
    assert d["provenance"]["id"] == "isona__dirble.e2dea9f"
    assert d["eval_index"] is not None
    assert d["eval_index"]["slug"].endswith("dirble")
    assert "provenance" in d["found_in"] and "eval_index" in d["found_in"]


def test_live_tool_status_unknown_tool_degrades_gracefully():
    d = api.tool_status("totally-not-a-tool")
    assert d["found_in"] == []
    assert d["provenance"] is None and d["eval_index"] is None


def test_search_dedupes_a_key_that_appears_in_both_topic_index_and_top_level():
    """pb_only_open_item is deliberately fixtured to appear in BOTH _topic_index.BUILD_TOOLCHAIN
    (empty summary -> low/no score) and as a full top-level entry (real content -> higher score).
    Before the 2026-07-19 fix, search() returned BOTH as separate SearchHits with the same key;
    any caller building a {key: hit} dict (hybrid_search) kept whichever sorted last -- silently
    the WORSE one. search() must now return exactly one hit per key, keeping the higher score."""
    hits = api.search("go toolchain shim finish", corpus=_fixture(), limit=20)
    matches = [h for h in hits if h.key == "pb_only_open_item"]
    assert len(matches) == 1
    assert matches[0].source == "entry"
    assert matches[0].score >= 1


def test_live_swebench_repo_info_finds_real_repo():
    d = api.swebench_repo_info("astropy/astropy")
    assert d is not None
    assert d["instances"] > 0
    assert "python" in d["languages"]


def test_live_swebench_repo_info_unknown_repo_returns_none():
    assert api.swebench_repo_info("totally/not-a-repo") is None


def test_live_swebench_stats_has_totals():
    stats = api.swebench_stats()
    assert "totals" in stats


def test_live_terminal_bench_task_finds_real_task():
    d = api.terminal_bench_task("acl-permissions-inheritance")
    assert d is not None
    assert d["difficulty"] in ("easy", "medium", "hard")


def test_live_terminal_bench_task_unknown_returns_none():
    assert api.terminal_bench_task("not-a-real-task") is None


def test_live_terminal_bench_stats_has_task_count():
    stats = api.terminal_bench_stats()
    assert stats.get("task_count") == 241


def test_live_wiring_census_guard_passes():
    """The census guard is the standing defense against built-but-invisible artifacts and
    split-brain data-root pointers. It must pass on the current tree."""
    import importlib
    import re
    import sys as _sys
    from pathlib import Path as _P

    root = _P(api.__file__).resolve().parents[1]
    _sys.path.insert(0, str(root / "scripts" / "corpus"))
    census_mod = importlib.import_module("corpus_wiring_census")
    res = census_mod.census()
    assert res["orphans"] == [], f"unwired corpus artifacts: {res['orphans']}"
    for p in res["pointers"]:
        # A pointer at an absolute location this machine does not have is machine-specific
        # configuration, not a broken pointer. `settings.corpus_root -> T:/determinex_corpus`
        # names a Windows drive that cannot exist on a Linux runner, and CI reported it as
        # "empty/broken" -- a true statement about the wrong thing. The orphan check above is
        # environment-independent and still holds everywhere.
        value = str(p.get("value") or "")
        # Match the drive prefix TEXTUALLY, not via Path.anchor. On Linux
        # PurePosixPath("T:/determinex_corpus").anchor is '' -- "T:" is an ordinary
        # character there, not a drive -- so the anchor test silently never fired and CI
        # still reported the pointer broken.
        drive = re.match(r"^([A-Za-z]):[\\/]", value)
        if drive and not _P(f"{drive.group(1)}:/").exists():
            continue
        assert p["resolves_nonempty"], f"pointer {p['pointer']} -> {p['value']} is empty/broken"


def test_hybrid_search_with_explicit_corpus_never_leaks_global_index_hits():
    """An explicit `corpus` must be answered from THAT corpus only.

    hybrid_search's BM25 and semantic legs read prebuilt GLOBAL indexes (corpus/programbench/
    fts_index.sqlite3, embeddings_cache.npy) derived from the default corpus. Neither takes a
    corpus argument. When BM25 was first wired in it ran unconditionally, so a scoped query got
    scored against the full corpus's documents -- real-corpus keys outranked the fixture's own
    entries and displaced them, which broke ask()'s top-5 supersession check. The semantic leg
    had the identical flaw but hid it by returning [] whenever Ollama was unreachable.
    """
    fixture = _fixture()
    hits = api.hybrid_search("corrected wrong demoted claim", corpus=fixture)
    fixture_keys = (
        set(fixture)
        | {k for rows in fixture["_topic_index"].values() for k in (r["key"] for r in rows)}
        | set(fixture["class_patterns"])
        | set(fixture["learned_classes"])
    )
    leaked = [h.key for h in hits if h.key not in fixture_keys]
    assert not leaked, f"hits from outside the supplied corpus: {leaked}"


def test_blend_key_merges_namespaced_pattern_keys_onto_bare_keys():
    """corpus_embeddings._entries()/corpus_fts namespace these; search() emits them bare. Without
    normalisation the same class_pattern competed with itself as two rows in the blend."""
    assert api._blend_key("class_pattern::collection_cap") == "collection_cap"
    assert api._blend_key("learned_class::some_tool") == "some_tool"
    assert api._blend_key("ordinary_entry_key") == "ordinary_entry_key"
