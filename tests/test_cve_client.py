"""Tests for CVE Client - SQLite-based local queries"""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.cve_client import CVEClient


class TestCVEClient:
    """Test the local SQLite-based CVE client."""

    def test_query_by_cwe_returns_results(self, tmp_path):
        """query_by_cwe should return CVE data from local SQLite."""
        # Create a temporary database
        db_path = tmp_path / "test_cve.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT,
                cwe_id TEXT,
                description TEXT,
                severity TEXT,
                cvss_score REAL,
                references_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cves VALUES (?, ?, ?, ?, ?, ?)",
            ("CVE-2024-1234", "CWE-120", "Buffer overflow in lib", "high", 8.5, "[]")
        )
        conn.execute(
            "INSERT INTO cves VALUES (?, ?, ?, ?, ?, ?)",
            ("CVE-2024-5678", "CWE-120", "Another overflow", "critical", 9.1, "[]")
        )
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        results = client.query_by_cwe("CWE-120", max_results=5)

        assert len(results) == 2
        # Results ordered by cvss_score DESC
        assert results[0]["cve_id"] == "CVE-2024-5678"
        assert results[0]["severity"] == "critical"
        assert results[1]["cve_id"] == "CVE-2024-1234"

    def test_query_by_cwe_no_results(self, tmp_path):
        """query_by_cwe returns empty list for unknown CWE."""
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT, cwe_id TEXT, description TEXT,
                severity TEXT, cvss_score REAL, references_json TEXT
            )
        """)
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        results = client.query_by_cwe("CWE-9999")
        assert results == []

    def test_has_known_exploits_true(self, tmp_path):
        """has_known_exploits returns True when high-severity CVEs exist."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT, cwe_id TEXT, description TEXT,
                severity TEXT, cvss_score REAL, references_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cves VALUES (?, ?, ?, ?, ?, ?)",
            ("CVE-2024-0001", "CWE-78", "OS command injection", "critical", 9.8, "[]")
        )
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        assert client.has_known_exploits("CWE-78") is True

    def test_has_known_exploits_false(self, tmp_path):
        """has_known_exploits returns False when only low-severity CVEs exist."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT, cwe_id TEXT, description TEXT,
                severity TEXT, cvss_score REAL, references_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cves VALUES (?, ?, ?, ?, ?, ?)",
            ("CVE-2024-0002", "CWE-200", "Info disclosure", "low", 3.1, "[]")
        )
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        assert client.has_known_exploits("CWE-200") is False

    def test_get_cve_summary(self, tmp_path):
        """get_cve_summary returns a formatted string."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT, cwe_id TEXT, description TEXT,
                severity TEXT, cvss_score REAL, references_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cves VALUES (?, ?, ?, ?, ?, ?)",
            ("CVE-2024-1234", "CWE-89", "SQL injection", "high", 8.1, "[]")
        )
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        summary = client.get_cve_summary("CWE-89")
        assert "CVE-2024-1234" in summary
        assert "high" in summary

    def test_get_cve_summary_no_data(self, tmp_path):
        """get_cve_summary returns message when no data found."""
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT, cwe_id TEXT, description TEXT,
                severity TEXT, cvss_score REAL, references_json TEXT
            )
        """)
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        summary = client.get_cve_summary("CWE-9999")
        assert "No CVE data" in summary

    def test_cwe_id_sanitization(self, tmp_path):
        """CWE ID with description text should be sanitized to just CWE-xxx."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT, cwe_id TEXT, description TEXT,
                severity TEXT, cvss_score REAL, references_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cves VALUES (?, ?, ?, ?, ?, ?)",
            ("CVE-2024-0001", "CWE-120", "Test", "high", 7.5, "[]")
        )
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        # Should work even with extra text
        results = client.query_by_cwe("CWE-120: Use of...")
        assert len(results) == 1

    def test_missing_db_file(self, tmp_path):
        """CVEClient handles missing database gracefully."""
        db_path = tmp_path / "nonexistent.db"
        client = CVEClient(db_path=db_path)
        results = client.query_by_cwe("CWE-120")
        assert results == []

    def test_max_results_limit(self, tmp_path):
        """query_by_cwe respects max_results parameter."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT, cwe_id TEXT, description TEXT,
                severity TEXT, cvss_score REAL, references_json TEXT
            )
        """)
        for i in range(10):
            conn.execute(
                "INSERT INTO cves VALUES (?, ?, ?, ?, ?, ?)",
                (f"CVE-2024-{i:04d}", "CWE-79", f"XSS #{i}", "medium", 5.0, "[]")
            )
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        results = client.query_by_cwe("CWE-79", max_results=3)
        assert len(results) == 3

    def test_get_stats(self, tmp_path):
        """get_stats returns database statistics."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE cves (
                cve_id TEXT, cwe_id TEXT, description TEXT,
                severity TEXT, cvss_score REAL, references_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO cves VALUES (?, ?, ?, ?, ?, ?)",
            ("CVE-2024-0001", "CWE-120", "Test", "high", 7.5, "[]")
        )
        conn.commit()
        conn.close()

        client = CVEClient(db_path=db_path)
        stats = client.get_stats()
        assert "total_cves" in stats
        assert stats["total_cves"] == 1
