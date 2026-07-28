"""Fase D test plan: index round-trip integrity, end-to-end mapping of a
small fixture project (no live GPU/model needed -- generate_once is
monkeypatched), cancellation between files when the chat goes busy, and
search_map's tool-shape output."""

import asyncio
import json
from pathlib import Path

import pytest

from core.rag import cartographer as carto


@pytest.fixture(autouse=True)
def _isolate_maps_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(carto, "MAPS_DIR", str(tmp_path / "maps"))
    carto._bm25_cache.clear()
    carto._busy_since = None
    yield
    carto._bm25_cache.clear()
    carto._busy_since = None


@pytest.fixture
def fixture_project(tmp_path) -> Path:
    project = tmp_path / "fixture-project"
    project.mkdir()
    (project / "main.py").write_text(
        "import os\n\nclass App:\n    def run(self):\n        pass\n", encoding="utf-8",
    )
    (project / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "ignored.js").write_text("should not be discovered\n", encoding="utf-8")
    return project


def test_index_round_trip_ok(tmp_path, fixture_project):
    index = {"main.py": {"source_hash": "abc123", "mapped_at": 1.0, "stage": "full"}}
    carto._save_index(str(fixture_project), index)
    reloaded = carto._load_index(str(fixture_project))
    assert reloaded == index


def test_index_round_trip_catches_corruption(tmp_path, fixture_project, monkeypatch):
    index = {"main.py": {"source_hash": "abc123", "mapped_at": 1.0, "stage": "full"}}
    # Simulate a write that doesn't actually persist correctly by writing
    # something else with the same atomic_write_json call intercepted --
    # here, more directly: corrupt the file right after a real save.
    carto._save_index(str(fixture_project), index)
    idx_path = carto._index_path(str(fixture_project))
    idx_path.write_text("{not valid json", encoding="utf-8")
    reloaded = carto._load_index(str(fixture_project))
    assert reloaded == {}  # corrupt file degrades to empty, not a crash


def test_discover_files_skips_node_modules(fixture_project):
    files = carto._discover_files(str(fixture_project))
    assert "main.py" in files
    assert "utils.py" in files
    assert not any("node_modules" in f for f in files)


def test_path_hash_changes_with_content(fixture_project):
    p = fixture_project / "main.py"
    h1 = carto.path_hash(str(p))
    p.write_text(p.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    h2 = carto.path_hash(str(p))
    assert h1 != h2


def test_end_to_end_mapping_without_live_llm(fixture_project, monkeypatch):
    """No GPU/model available in this environment -- generate_once is
    monkeypatched to a canned response, exactly like the Flight Recorder
    cancellation test mocks vte_bridge.stream_generate."""
    import core.utils.vte_bridge as vte_bridge
    monkeypatch.setattr(vte_bridge, "generate_once", lambda *a, **kw: "Handles the app's entrypoint.")

    async def _run():
        mapped_any = False
        for _ in range(10):  # bounded: 2 real files + safety margin
            did_work = await carto._map_one_pending_file(str(fixture_project))
            if not did_work:
                break
            mapped_any = True
        return mapped_any

    assert asyncio.run(_run())

    index = carto._load_index(str(fixture_project))
    assert index["main.py"]["stage"] == "full"
    assert index["utils.py"]["stage"] == "full"

    map_dir = carto._map_dir(str(fixture_project)) / "MAP"
    doc = (map_dir / "main.py.md").read_text(encoding="utf-8")
    assert "class App" in doc
    assert "def run" in doc
    assert "Handles the app's entrypoint." in doc


def test_worker_stops_between_files_when_chat_goes_busy(fixture_project, monkeypatch):
    """Bounded interruption: at most one file's worth of work happens once
    the chat is busy again."""
    import core.utils.vte_bridge as vte_bridge
    monkeypatch.setattr(vte_bridge, "generate_once", lambda *a, **kw: "summary")

    async def _run():
        carto._on_turn_start()  # simulate a live chat turn starting
        return await carto._map_one_pending_file(str(fixture_project))

    did_work = asyncio.run(_run())
    assert did_work is False
    assert carto._load_index(str(fixture_project)) == {}


def test_search_map_bm25_returns_relevant_doc(fixture_project, monkeypatch):
    # Distinct summaries per file, not the same canned string for both --
    # an identical summary on every doc in a tiny 2-file corpus is a
    # pathological case for BM25's classic IDF term (a term in every
    # document can get zero/negative IDF), not representative of real
    # per-file LLM summaries.
    def _fake_generate_once(model, messages, temperature=0.3, max_tokens=512):
        prompt = messages[0]["content"]
        if "main.py" in prompt:
            return "The application entrypoint, wires up App and starts it running."
        return "A small utility module with one helper function."

    import core.utils.vte_bridge as vte_bridge
    monkeypatch.setattr(vte_bridge, "generate_once", _fake_generate_once)

    async def _run():
        for _ in range(10):
            if not await carto._map_one_pending_file(str(fixture_project)):
                break

    asyncio.run(_run())
    results = carto.query_map(str(fixture_project), "application entrypoint App running", top_k=3)
    assert results
    assert results[0]["file"] == "main.py.md"


def test_query_map_empty_corpus_returns_empty_list(fixture_project):
    assert carto.query_map(str(fixture_project), "anything") == []


def test_cartographer_disabled_flag(monkeypatch):
    monkeypatch.setenv("AETHERIS_CARTOGRAPHER_ENABLED", "false")
    assert carto.cartographer_enabled() is False
    assert carto.cartographer_auto_inject_enabled() is False


def test_auto_inject_sub_flag_independent_of_parent(monkeypatch):
    monkeypatch.setenv("AETHERIS_CARTOGRAPHER_ENABLED", "true")
    monkeypatch.setenv("AETHERIS_CARTOGRAPHER_AUTO_INJECT", "false")
    assert carto.cartographer_enabled() is True
    assert carto.cartographer_auto_inject_enabled() is False
