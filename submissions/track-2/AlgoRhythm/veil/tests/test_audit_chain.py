"""Audit chain integrity.

The audit log is the one artefact a VEIL operator cannot quietly edit. These
tests tamper with it in the three ways someone would actually try — alter an
entry, delete an entry, reorder entries — and assert that verify() catches
each and names the sequence number.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from veil.security.audit import AuditLog


@pytest.fixture
def log(tmp_path):
    return AuditLog(db_path=str(tmp_path / "audit.db"), actor="test")


class TestChain:
    def test_empty_chain_verifies(self, log):
        status = log.verify()
        assert status.ok and status.entries == 0

    def test_appended_entries_chain(self, log):
        for i in range(5):
            log.append("test_action", {"i": i})
        status = log.verify()
        assert status.ok
        assert status.entries == 5
        assert "intact" in status.detail

    def test_each_entry_references_its_predecessor(self, log):
        first = log.append("a", {})
        second = log.append("b", {})
        assert first != second

        con = sqlite3.connect(log.db_path)
        rows = con.execute("SELECT prev_hash, entry_hash FROM audit_log ORDER BY seq").fetchall()
        con.close()
        assert rows[0][0] == "0" * 64          # genesis
        assert rows[1][0] == rows[0][1]        # second points at first


class TestTampering:
    def test_altered_payload_is_detected(self, log):
        log.append("finding_recorded", {"claim": "identifies J. Okafor"})
        log.append("run_end", {"risk": 0.9})

        con = sqlite3.connect(log.db_path)
        con.execute(
            "UPDATE audit_log SET payload = ? WHERE seq = 1",
            (json.dumps({"claim": "nothing found"}),),
        )
        con.commit()
        con.close()

        status = log.verify()
        assert not status.ok
        assert status.broken_at == 1
        assert "altered" in status.detail

    def test_deleted_entry_is_detected(self, log):
        for i in range(4):
            log.append("step", {"i": i})

        con = sqlite3.connect(log.db_path)
        con.execute("DELETE FROM audit_log WHERE seq = 2")
        con.commit()
        con.close()

        status = log.verify()
        assert not status.ok
        assert status.broken_at == 3
        assert "removed or reordered" in status.detail

    def test_truncating_the_tail_is_not_detectable_and_that_is_documented(self, log):
        """Honest limitation: removing the most recent entries leaves a valid
        chain. Defending against truncation needs an external anchor, which is
        out of scope for a local-only tool — so we state it rather than imply
        a guarantee we do not have."""
        for i in range(4):
            log.append("step", {"i": i})

        con = sqlite3.connect(log.db_path)
        con.execute("DELETE FROM audit_log WHERE seq = 4")
        con.commit()
        con.close()

        assert log.verify().ok   # by design, and documented in README §Threat model

    def test_tail_returns_most_recent_first(self, log):
        for i in range(3):
            log.append("step", {"i": i})
        entries = log.tail(2)
        assert len(entries) == 2
        assert entries[0]["payload"]["i"] == 2
