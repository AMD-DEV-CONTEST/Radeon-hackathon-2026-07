"""Regression tests: the agent must be able to read seed documents
itself (deriving the schema) instead of interrogating the user."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foundry.tools import ToolBox


def make_toolbox(tmp_path):
    return ToolBox({"run": {"out_root": str(tmp_path)}}, "cfg.toml",
                   teacher_ctl=None)


def test_no_path_lists_available_documents(tmp_path):
    tb = make_toolbox(tmp_path)
    result = tb.dispatch("read_seed_document", {})
    paths = [d["path"] for d in result["available_documents"]]
    assert "seeds/triage_policy.md" in paths


def test_read_returns_document_content(tmp_path):
    tb = make_toolbox(tmp_path)
    result = tb.dispatch("read_seed_document",
                         {"path": "seeds/triage_policy.md"})
    assert "outage" in result["content"]
    assert "P1" in result["content"]
    assert result["truncated"] is False


def test_oversize_document_is_truncated_with_note(tmp_path, monkeypatch):
    tb = make_toolbox(tmp_path)
    monkeypatch.setattr(ToolBox, "MAX_DOC_CHARS", 100)
    result = tb.dispatch("read_seed_document",
                         {"path": "seeds/triage_policy.md"})
    assert len(result["content"]) == 100
    assert result["truncated"] is True
    assert "datagen always uses the full text" in result["note"]


def test_missing_document_is_clean_error(tmp_path):
    tb = make_toolbox(tmp_path)
    result = tb.dispatch("read_seed_document", {"path": "seeds/nope.md"})
    assert "error" in result and "not found" in result["error"]
