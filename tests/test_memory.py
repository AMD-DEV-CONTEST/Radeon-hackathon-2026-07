"""Tests for Memory Layer"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.memory import MemoryLayer
from core.models import Risk, Severity, Confidence, Language, Evidence


def _make_risk(risk_id="RISK-001", title="test", severity=Severity.HIGH, cwe_id="CWE-120"):
    return Risk(
        id=risk_id,
        title=title,
        description="test desc",
        severity=severity,
        confidence=Confidence.HIGH,
        cwe_id=cwe_id,
        language=Language.C,
        file_path=Path("test.c"),
        line_start=10,
        line_end=10,
        evidence=[Evidence(source="test", snippet="char buf[10]; gets(buf);", line_start=10, line_end=10, reasoning="test")],
        suggestion="fix it",
    )


class TestMemoryStoreRecall:
    def test_store_and_recall_correct(self):
        mem = MemoryLayer(persist=False)
        risk = _make_risk()
        mem.store_correct(risk)
        result = mem.recall(risk)
        assert result is not None
        entry, mem_type = result
        assert mem_type == "correct"
        assert entry.source_count >= 1

    def test_store_and_recall_error(self):
        mem = MemoryLayer(persist=False)
        risk = _make_risk()
        # Error memory needs source_count >= 2 to be recalled as "error"
        mem.store_error(risk)
        mem.store_error(risk)  # second time increments count to 2
        result = mem.recall(risk)
        assert result is not None
        entry, mem_type = result
        assert mem_type == "error"

    def test_recall_no_match(self):
        mem = MemoryLayer(persist=False)
        risk = _make_risk()
        result = mem.recall(risk)
        assert result is None

    def test_multiple_stores_increment_count(self):
        mem = MemoryLayer(persist=False)
        risk = _make_risk()
        mem.store_correct(risk)
        mem.store_correct(risk)
        result = mem.recall(risk)
        assert result is not None
        entry, _ = result
        assert entry.source_count >= 2


class TestMemoryStats:
    def test_stats_empty(self):
        mem = MemoryLayer(persist=False)
        stats = mem.get_stats()
        assert stats["correct_patterns"] == 0
        assert stats["error_patterns"] == 0

    def test_stats_with_data(self):
        mem = MemoryLayer(persist=False)
        mem.store_correct(_make_risk())
        mem.store_error(_make_risk(risk_id="RISK-002", title="error"))
        stats = mem.get_stats()
        assert stats["correct_patterns"] == 1
        assert stats["error_patterns"] == 1

    def test_clear(self):
        mem = MemoryLayer(persist=False)
        mem.store_correct(_make_risk())
        mem.clear()
        stats = mem.get_stats()
        assert stats["total"] == 0
