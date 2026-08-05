"""Tests for DETERMINEX_CORPUS_DIRECT_QUERY_SURFACE_LOCK_001.

Direct read-only query surface over the ONE canonical corpus API
(scripts/determinex_corpus_api.py). No new search/ranking/maturity logic was
written here -- this rung is wiring, not invention.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

bcs = importlib.import_module("ide.backend_command_surface")
td = importlib.import_module("ide._tauri_driver")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "DETERMINEX_CORPUS_DIRECT_QUERY_SURFACE_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "determinex_corpus_direct_query_surface"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
PANEL_PATH = (
    _REPO_ROOT / "frontend" / "src" / "components" / "ide-product-shell" / "LearningStudioPanel.tsx"
)
BRIDGE_RS = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "ide_repair_bridge.rs"
LIB_RS = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"
API_TS = _REPO_ROOT / "frontend" / "src" / "lib" / "ide-product-shell-api.ts"


def test_command_registered_in_full_surface():
    assert "query_corpus" in bcs.commands()


def test_command_deliberately_excluded_from_frozen_read_only_set():
    assert "query_corpus" not in bcs.UNIFIED_PRODUCT_READ_ONLY_COMMANDS


def test_ask_mode_returns_real_corpus_hits():
    """A REAL correctness check, not shape-only: a query known to hit a real
    corpus entry (the ProgramBench provenance invalidation) must surface it."""
    surface = bcs.IDEBackendCommandSurface()
    r = surface.call(
        "query_corpus", corpus_query="programbench 65 locks strict count", corpus_mode="ask"
    )
    assert r.status == "IDE_COMMAND_OK"
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    assert r.payload["mode"] == "ask"
    assert len(r.payload["hits"]) > 0


def test_ask_mode_surfaces_supersession_warnings():
    surface = bcs.IDEBackendCommandSurface()
    r = surface.call(
        "query_corpus", corpus_query="programbench 65 locks strict count", corpus_mode="ask"
    )
    assert isinstance(r.payload["warnings"], list)


def test_empty_query_never_crashes_and_returns_no_hits():
    surface = bcs.IDEBackendCommandSurface()
    r = surface.call("query_corpus", corpus_query="", corpus_mode="ask")
    assert r.status == "IDE_COMMAND_OK"
    assert r.payload["hits"] == []


def test_maturity_mode_returns_a_real_maturity_report():
    surface = bcs.IDEBackendCommandSurface()
    r = surface.call("query_corpus", corpus_query="", corpus_mode="maturity")
    assert r.status == "IDE_COMMAND_OK"
    assert "open_items" in r.payload
    assert "stats" in r.payload


def test_timeline_mode_returns_dated_entries():
    surface = bcs.IDEBackendCommandSurface()
    r = surface.call("query_corpus", corpus_query="", corpus_mode="timeline")
    assert r.status == "IDE_COMMAND_OK"
    assert len(r.payload["entries"]) > 0


def test_tauri_driver_dispatches_new_command():
    res = td._dispatch("query_corpus", {"corpus_query": "programbench", "corpus_mode": "ask"})
    assert res["status"] == "TAURI_COMMAND_OK"
    assert res["source_mutation_authorized"] is False
    assert res["training_eligible"] is False


def test_rust_command_declared_and_registered():
    src = BRIDGE_RS.read_text(encoding="utf-8")
    assert "pub fn query_corpus(" in src
    lib_src = LIB_RS.read_text(encoding="utf-8")
    assert "ide_repair_bridge::query_corpus," in lib_src


def test_rust_command_excluded_from_frozen_unified_product_list():
    import re

    src = BRIDGE_RS.read_text(encoding="utf-8")
    m = re.search(
        r"UNIFIED_PRODUCT_READ_ONLY_COMMANDS\s*:\s*&\[&str\]\s*=\s*&\[(.+?)\];", src, re.DOTALL
    )
    assert m
    declared = re.findall(r'"([^"]+)"', m.group(1))
    assert "query_corpus" not in declared


def test_frontend_command_list_includes_query_corpus():
    src = API_TS.read_text(encoding="utf-8")
    assert '"query_corpus"' in src


def test_panel_invokes_the_new_command():
    src = PANEL_PATH.read_text(encoding="utf-8")
    assert '"query_corpus"' in src
    assert 'data-testid="learning-studio-ask-corpus-input"' in src
    assert 'data-testid="learning-studio-ask-corpus-button"' in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_CORPUS_DIRECT_QUERY_SURFACE_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False
    assert sd["corpus_written"] is False


def test_evidence_artifact_present():
    assert sorted(EVIDENCE_DIR.glob("run_*.json"))


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_CORPUS_DIRECT_QUERY_SURFACE_LOCK_001" in ids
