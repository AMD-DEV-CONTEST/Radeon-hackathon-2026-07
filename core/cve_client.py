"""CodeRisk Agent - Local CVE Database Client

Queries a local SQLite database built from NVD JSON feeds.
No external API calls — 100% offline operation.

Usage:
    # Build database first (one-time setup):
    python scripts/download_cve_data.py

    # Then query locally:
    client = CVEClient()
    results = client.query_by_cwe("CWE-120")
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "vuln_db.sqlite"


class CVEClient:
    """Query local NVD SQLite database for CVE information by CWE ID.

    All data is pre-downloaded — no network calls at runtime.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._cache: dict[str, list[dict]] = {}
        self._conn: Optional[sqlite3.Connection] = None

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create SQLite connection."""
        if self._conn is None:
            if not self.db_path.exists():
                console.print(
                    f"[yellow]CVE database not found at {self.db_path}. "
                    f"Run: python scripts/download_cve_data.py[/]"
                )
                console.print(
                    f"[dim]  CVE lookup will return empty results until database is built.[/]"
                )
                # Return empty in-memory database as fallback
                self._conn = sqlite3.connect(":memory:")
                self._conn.execute(
                    "CREATE TABLE cves (cve_id TEXT, cwe_id TEXT, description TEXT, "
                    "severity TEXT, cvss_score REAL, references_json TEXT)"
                )
            else:
                self._conn = sqlite3.connect(str(self.db_path))
                self._conn.row_factory = sqlite3.Row
        return self._conn

    def query_by_cwe(
        self,
        cwe_id: str,
        max_results: int = 5,
    ) -> list[dict]:
        """Query CVEs associated with a CWE ID from local database.

        Args:
            cwe_id: CWE identifier (e.g. "CWE-120" or "CWE-120: Buffer Overflow")
            max_results: Maximum number of results to return

        Returns:
            List of CVE records sorted by CVSS score (descending)
        """
        cache_key = f"{cwe_id}:{max_results}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Sanitize CWE ID — extract just "CWE-xxx"
        cwe_match = re.match(r"(CWE-\d+)", cwe_id)
        if cwe_match:
            cwe_id = cwe_match.group(1)
        else:
            return []

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT cve_id, description, severity, cvss_score, references_json
            FROM cves
            WHERE cwe_id = ?
            ORDER BY cvss_score DESC
            LIMIT ?
            """,
            (cwe_id, max_results),
        )

        results = []
        for row in cursor.fetchall():
            if isinstance(row, sqlite3.Row):
                cve_id = row["cve_id"]
                desc = row["description"]
                severity = row["severity"]
                cvss = row["cvss_score"]
                refs_json = row["references_json"]
            else:
                cve_id, desc, severity, cvss, refs_json = row

            results.append(
                {
                    "cve_id": cve_id,
                    "description": desc or "",
                    "severity": severity or "unknown",
                    "cvss_score": cvss or 0.0,
                    "references": json.loads(refs_json) if refs_json else [],
                }
            )

        self._cache[cache_key] = results
        return results

    def has_known_exploits(self, cwe_id: str) -> bool:
        """Check if a CWE has known high-severity CVEs (CVSS >= 7.0)."""
        results = self.query_by_cwe(cwe_id, max_results=3)
        return any(
            r["severity"] in ("high", "critical") and r["cvss_score"] >= 7.0
            for r in results
        )

    def get_cve_summary(self, cwe_id: str) -> str:
        """Get a brief summary of CVEs for a CWE."""
        results = self.query_by_cwe(cwe_id, max_results=3)
        if not results:
            return f"No CVE data found for {cwe_id}"

        summaries = []
        for r in results:
            summaries.append(
                f"{r['cve_id']} ({r['severity']}, CVSS {r['cvss_score']}): "
                f"{r['description'][:100]}..."
            )
        return " | ".join(summaries)

    def get_stats(self) -> dict:
        """Get database statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cves")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT cwe_id) FROM cves")
        cwe_count = cursor.fetchone()[0]
        return {"total_cves": total, "cwe_categories": cwe_count}

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
