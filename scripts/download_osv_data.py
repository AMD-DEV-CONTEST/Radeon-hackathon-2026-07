#!/usr/bin/env python3
"""Download OSV vulnerability data for Python/npm ecosystems.

Downloads OSV bulk data and builds a local JSON index for fast lookup.
No external API calls at runtime.

Usage:
    python scripts/download_osv_data.py
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from urllib.request import urlopen

DATA_DIR = Path(__file__).parent.parent / "data" / "osv"
INDEX_FILE = DATA_DIR / "index.json"

# OSV bulk download URLs by ecosystem
OSV_BULK_URLS = {
    "PyPI": "https://osv-vulnerabilities.storage.googleapis.com/PyPI/all.zip",
    "npm": "https://osv-vulnerabilities.storage.googleapis.com/npm/all.zip",
}


def download_and_extract(ecosystem: str, url: str) -> list[dict]:
    """Download and extract OSV bulk data for an ecosystem."""
    print(f"  Downloading {ecosystem} vulnerability data...")
    zip_path = DATA_DIR / f"osv_{ecosystem.lower()}.zip"

    try:
        with urlopen(url, timeout=180) as resp:
            zip_path.write_bytes(resp.read())

        vulns = []
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.endswith(".json"):
                    with zf.open(name) as f:
                        try:
                            data = json.loads(f.read())
                            vulns.append(data)
                        except json.JSONDecodeError:
                            continue

        zip_path.unlink()  # Remove zip after extraction
        print(f"  {ecosystem}: {len(vulns)} vulnerabilities loaded")
        return vulns

    except Exception as e:
        print(f"  Failed to download {ecosystem}: {e}")
        return []


def build_index(vulns: list[dict], ecosystem: str) -> dict[str, list[dict]]:
    """Build a package-name index for fast lookup."""
    index: dict[str, list[dict]] = {}

    for vuln in vulns:
        vuln_id = vuln.get("id", "unknown")
        summary = vuln.get("summary", vuln.get("details", "")[:200])

        # Extract severity
        severity = "unknown"
        cvss_score = 0.0
        for sev in vuln.get("severity", []):
            if sev.get("type") == "CVSS_V3":
                score_str = sev.get("score", "")
                # Parse CVSS vector for score
                match = re.search(r"baseScore\s*[:=]\s*([\d.]+)", score_str)
                if match:
                    cvss_score = float(match.group(1))
                if "CRITICAL" in score_str.upper():
                    severity = "critical"
                elif "HIGH" in score_str.upper():
                    severity = "high"
                elif "MEDIUM" in score_str.upper():
                    severity = "medium"
                elif "LOW" in score_str.upper():
                    severity = "low"

        # Extract CWE
        cwe = ""
        for ref in vuln.get("references", []):
            url = ref.get("url", "")
            cwe_match = re.search(r"CWE-\d+", url)
            if cwe_match:
                cwe = cwe_match.group()
                break

        # Extract affected packages and version ranges
        for aff in vuln.get("affected", []):
            pkg = aff.get("package", {})
            if pkg.get("ecosystem") != ecosystem:
                continue

            pkg_name = pkg.get("name", "").lower()
            if not pkg_name:
                continue

            # Extract version ranges
            ranges = []
            for r in aff.get("ranges", []):
                events = r.get("events", [])
                introduced = None
                fixed = None
                for event in events:
                    if "introduced" in event:
                        introduced = event["introduced"]
                    if "fixed" in event:
                        fixed = event["fixed"]
                if introduced or fixed:
                    ranges.append({"introduced": introduced, "fixed": fixed})

            # Extract specific affected versions
            versions = aff.get("versions", [])

            entry = {
                "id": vuln_id,
                "summary": summary[:200],
                "severity": severity,
                "cvss_score": cvss_score,
                "cwe": cwe,
                "ranges": ranges,
                "versions": versions[:20],  # Limit to prevent bloat
            }

            if pkg_name not in index:
                index[pkg_name] = []
            index[pkg_name].append(entry)

    return index


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Building local OSV vulnerability index...\n")

    combined_index: dict[str, list[dict]] = {}

    for ecosystem, url in OSV_BULK_URLS.items():
        vulns = download_and_extract(ecosystem, url)
        index = build_index(vulns, ecosystem)

        # Merge into combined index
        for pkg, entries in index.items():
            key = f"{ecosystem}:{pkg}"
            combined_index[key] = entries

        print(f"  {ecosystem}: {len(index)} packages indexed\n")

    # Save combined index
    with open(INDEX_FILE, "w") as f:
        json.dump(combined_index, f, indent=2, ensure_ascii=False)

    size_mb = INDEX_FILE.stat().st_size / 1024 / 1024
    print(f"Index saved: {INDEX_FILE}")
    print(f"Total packages: {len(combined_index)}")
    print(f"Index size: {size_mb:.1f} MB")
    print("\nDone! No network calls needed at runtime.")


if __name__ == "__main__":
    main()
