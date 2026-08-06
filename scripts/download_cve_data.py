#!/usr/bin/env python3
"""Download NVD CVE data and build local SQLite database.

Downloads NVD JSON feeds for recent years, filters by relevant CWEs,
and builds a local SQLite database at data/vuln_db.sqlite.

No external API calls at runtime — all data is pre-downloaded.

Usage:
    python scripts/download_cve_data.py [--years 2023 2024 2025 2026]
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
from pathlib import Path
from urllib.request import urlopen

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "vuln_db.sqlite"

# NVD JSON 2.0 feed URLs
NVD_FEED_BASE = "https://nvd.nist.gov/feeds/json/cve/2.0"

# CWE IDs relevant to our 27 detection rules
RELEVANT_CWES = {
    "CWE-78", "CWE-95", "CWE-89", "CWE-79", "CWE-502",
    "CWE-120", "CWE-415", "CWE-476", "CWE-134", "CWE-22",
    "CWE-798", "CWE-287", "CWE-327", "CWE-328", "CWE-611",
    "CWE-377", "CWE-617", "CWE-73", "CWE-190", "CWE-200",
    "CWE-295", "CWE-918", "CWE-1321", "CWE-400", "CWE-770",
    "CWE-256", "CWE-704", "CWE-191", "CWE-122", "CWE-125",
}


def download_feed(year: int) -> list[dict]:
    """Download and decompress NVD JSON feed for a specific year."""
    url = f"{NVD_FEED_BASE}/nvdcve-2.0-{year}.json.gz"
    print(f"  Downloading NVD feed for {year}...")

    try:
        with urlopen(url, timeout=120) as resp:
            data = gzip.decompress(resp.read()).decode("utf-8")
        feed = json.loads(data)
        return feed.get("vulnerabilities", [])
    except Exception as e:
        print(f"  Failed to download {year}: {e}")
        return []


def extract_cve_metadata(item: dict) -> dict | None:
    """Extract relevant metadata from a CVE entry."""
    cve = item.get("cve", {})
    cve_id = cve.get("id", "")
    if not cve_id:
        return None

    # Description
    desc = ""
    for d in cve.get("descriptions", []):
        if d.get("lang") == "en":
            desc = d.get("value", "")
            break

    # CVSS scores
    metrics = cve.get("metrics", {})
    severity = "unknown"
    cvss_score = 0.0

    for version_key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
        for metric in metrics.get(version_key, []):
            cvss_data = metric.get("cvssData", {})
            if cvss_data:
                cvss_score = cvss_data.get("baseScore", 0.0)
                severity = cvss_data.get("baseSeverity", "unknown").lower()
                break
        if severity != "unknown":
            break

    # References (max 3)
    refs = [r.get("url", "") for r in cve.get("references", [])[:3]]

    # Extract CWE IDs
    cwe_ids = set()

    # From weakness descriptions
    for weakness in cve.get("weaknesses", []):
        for desc_entry in weakness.get("description", []):
            val = desc_entry.get("value", "")
            if val.startswith("CWE-"):
                cwe_ids.add(val)

    # From description text as fallback
    if not cwe_ids:
        cwe_matches = re.findall(r"CWE-\d+", desc)
        cwe_ids.update(cwe_matches)

    # Filter to relevant CWEs only
    relevant = cwe_ids & RELEVANT_CWES
    if not relevant:
        return None

    return {
        "cve_id": cve_id,
        "description": desc[:500],
        "severity": severity,
        "cvss_score": cvss_score,
        "references": refs,
        "cwe_ids": list(relevant),
    }


def build_database(years: list[int]) -> None:
    """Build SQLite database from NVD feeds."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed existing database: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cves (
            cve_id TEXT PRIMARY KEY,
            cwe_id TEXT NOT NULL,
            description TEXT,
            severity TEXT,
            cvss_score REAL,
            references_json TEXT,
            published_date TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cwe ON cves(cwe_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_severity ON cves(severity)")

    total_inserted = 0

    for year in years:
        items = download_feed(year)
        year_inserted = 0

        for item in items:
            meta = extract_cve_metadata(item)
            if meta is None:
                continue

            published = item.get("cve", {}).get("published", "")

            for cwe_id in meta["cwe_ids"]:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO cves
                    (cve_id, cwe_id, description, severity, cvss_score, references_json, published_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        meta["cve_id"],
                        cwe_id,
                        meta["description"],
                        meta["severity"],
                        meta["cvss_score"],
                        json.dumps(meta["references"]),
                        published,
                    ),
                )
                year_inserted += 1

        print(f"  {year}: {year_inserted} relevant CVE entries inserted")
        total_inserted += year_inserted

    conn.commit()
    conn.close()

    print(f"\nDatabase built: {DB_PATH}")
    print(f"Total entries: {total_inserted}")
    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    print(f"Database size: {size_mb:.1f} MB")


def main():
    parser = argparse.ArgumentParser(description="Build local NVD CVE database")
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[2023, 2024, 2025, 2026],
        help="Years to download (default: 2023 2024 2025 2026)",
    )
    args = parser.parse_args()

    print("Building local NVD CVE database...")
    print(f"Years: {args.years}")
    print(f"Target: {DB_PATH}\n")

    build_database(args.years)

    print("\nDone! No network calls needed at runtime.")


if __name__ == "__main__":
    main()
