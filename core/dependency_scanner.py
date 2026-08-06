"""Dependency Scanner Module (Local Only)

Scans project dependencies for known vulnerabilities using local OSV data.
No external API calls — all vulnerability data is pre-downloaded.

Usage:
    # Build local data first (one-time setup):
    python scripts/download_osv_data.py

    # Then scan locally:
    findings = scan_project_dependencies(Path("./my_project"))
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()

# Local OSV data paths
OSV_DATA_DIR = Path(__file__).parent.parent / "data" / "osv"
OSV_INDEX_PATH = OSV_DATA_DIR / "index.json"

# Fallback: known vulnerable packages (when OSV data is unavailable)
_LOCAL_VULN_DB: dict[str, dict] = {
    "django": {
        "vulnerable_below": "4.2.0",
        "cwe": "CWE-89",
        "description": "Old Django versions have SQL injection vulnerabilities",
    },
    "flask": {
        "vulnerable_below": "2.3.0",
        "cwe": "CWE-79",
        "description": "Old Flask versions have XSS vulnerabilities",
    },
    "requests": {
        "vulnerable_below": "2.31.0",
        "cwe": "CWE-295",
        "description": "Old requests versions have certificate verification issues",
    },
    "pyyaml": {
        "vulnerable_below": "6.0",
        "cwe": "CWE-502",
        "description": "Old PyYAML versions allow arbitrary code execution via yaml.load()",
    },
    "pillow": {
        "vulnerable_below": "10.0.0",
        "cwe": "CWE-120",
        "description": "Old Pillow versions have buffer overflow vulnerabilities",
    },
    "cryptography": {
        "vulnerable_below": "41.0.0",
        "cwe": "CWE-327",
        "description": "Old cryptography versions have weak algorithm support",
    },
    "lodash": {
        "vulnerable_below": "4.17.21",
        "cwe": "CWE-1321",
        "description": "Old lodash versions have prototype pollution vulnerability",
    },
    "express": {
        "vulnerable_below": "4.18.0",
        "cwe": "CWE-1321",
        "description": "Old Express versions have open redirect vulnerabilities",
    },
    "axios": {
        "vulnerable_below": "1.6.0",
        "cwe": "CWE-918",
        "description": "Old Axios versions have SSRF vulnerability",
    },
}


# ─── Local OSV Index ────────────────────────────────────────────

_osv_index: Optional[dict] = None


def _load_osv_index() -> dict[str, list[dict]]:
    """Load OSV package index from local data (cached)."""
    global _osv_index
    if _osv_index is not None:
        return _osv_index

    if not OSV_INDEX_PATH.exists():
        _osv_index = {}
        return _osv_index

    try:
        with open(OSV_INDEX_PATH) as f:
            _osv_index = json.load(f)
        return _osv_index
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[dim]OSV index load failed: {e}[/]")
        _osv_index = {}
        return _osv_index


# ─── Version Comparison ─────────────────────────────────────────

def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse version string to tuple for comparison."""
    cleaned = re.sub(r"^[><=!~^]+", "", version_str.strip())
    parts = []
    for p in cleaned.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


def _version_below(current: str, threshold: str) -> bool:
    """Check if current version is below threshold."""
    return _parse_version(current) < _parse_version(threshold)


def _version_in_ranges(version: str, ranges: list[dict]) -> bool:
    """Check if a version falls within vulnerable ranges."""
    current = _parse_version(version)

    for rng in ranges:
        introduced = rng.get("introduced")
        fixed = rng.get("fixed")

        intro_ver = _parse_version(introduced) if introduced else None
        fixed_ver = _parse_version(fixed) if fixed else None

        # Version must be >= introduced (or no introduced constraint)
        if intro_ver and current < intro_ver:
            continue

        # Version must be < fixed (or no fixed = still vulnerable)
        if fixed_ver and current >= fixed_ver:
            continue

        return True

    return False


# ─── Local OSV Query ────────────────────────────────────────────

def _query_local_osv(package_name: str, version: str) -> list[dict]:
    """Query local OSV data for vulnerabilities of a specific package."""
    index = _load_osv_index()

    # Try ecosystem-specific keys
    results = []
    for ecosystem in ["PyPI", "npm"]:
        key = f"{ecosystem}:{package_name.lower()}"
        if key not in index:
            continue

        for vuln in index[key]:
            affected = False

            # Check specific versions
            if version in vuln.get("versions", []):
                affected = True

            # Check version ranges
            if not affected:
                ranges = vuln.get("ranges", [])
                if ranges and _version_in_ranges(version, ranges):
                    affected = True

            if affected:
                results.append(
                    {
                        "id": vuln.get("id", "unknown"),
                        "summary": vuln.get("summary", ""),
                        "severity": vuln.get("severity", "unknown"),
                        "cvss_score": vuln.get("cvss_score", 0.0),
                        "cwe": vuln.get("cwe", ""),
                    }
                )

    return results


# ─── Scanning Functions ─────────────────────────────────────────

def scan_requirements_txt(file_path: Path) -> list[dict]:
    """Scan Python requirements.txt for vulnerable packages."""
    findings = []

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return findings

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        match = re.match(
            r"^([a-zA-Z0-9_-]+)\s*[><=!~]+\s*([0-9][0-9.]*)", line
        )
        if not match:
            continue

        pkg_name = match.group(1).lower()
        version = match.group(2)

        # Try local OSV data first
        osv_vulns = _query_local_osv(pkg_name, version)
        if osv_vulns:
            for v in osv_vulns:
                findings.append(
                    {
                        "package": pkg_name,
                        "version": version,
                        "cwe": v.get("cwe", "CWE-000"),
                        "description": v.get("summary", "Vulnerability found via OSV"),
                        "fix": f"Upgrade {pkg_name} — see {v.get('id', 'OSV')} for details",
                        "source": "osv_local",
                        "osv_id": v.get("id", ""),
                    }
                )
        else:
            # Fallback to local dictionary
            if pkg_name in _LOCAL_VULN_DB:
                vuln = _LOCAL_VULN_DB[pkg_name]
                if _version_below(version, vuln["vulnerable_below"]):
                    findings.append(
                        {
                            "package": pkg_name,
                            "version": version,
                            "cwe": vuln["cwe"],
                            "description": vuln["description"],
                            "fix": f"Upgrade {pkg_name} to >= {vuln['vulnerable_below']}",
                            "source": "local_fallback",
                        }
                    )

    return findings


def scan_package_json(file_path: Path) -> list[dict]:
    """Scan Node.js package.json for vulnerable packages."""
    findings = []

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(content)
    except Exception:
        return findings

    deps = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))

    for pkg_name, version in deps.items():
        pkg_lower = pkg_name.lower()

        # Try local OSV data first
        clean_version = re.sub(r"^[><=!~^]+", "", version.strip())
        if clean_version:
            osv_vulns = _query_local_osv(pkg_lower, clean_version)
            if osv_vulns:
                for v in osv_vulns:
                    findings.append(
                        {
                            "package": pkg_name,
                            "version": version,
                            "cwe": v.get("cwe", "CWE-000"),
                            "description": v.get("summary", "Vulnerability found"),
                            "fix": f"Upgrade {pkg_name} — see {v.get('id', 'OSV')} for details",
                            "source": "osv_local",
                        }
                    )
                continue

        # Fallback to local dictionary
        if pkg_lower in _LOCAL_VULN_DB:
            vuln = _LOCAL_VULN_DB[pkg_lower]
            clean_version = re.sub(r"^[><=!~^]+", "", version.strip())
            if clean_version and _version_below(
                clean_version, vuln["vulnerable_below"]
            ):
                findings.append(
                    {
                        "package": pkg_name,
                        "version": version,
                        "cwe": vuln["cwe"],
                        "description": vuln["description"],
                        "fix": f"Upgrade {pkg_name} to >= {vuln['vulnerable_below']}",
                    }
                )

    return findings


def scan_project_dependencies(project_path: Path) -> list[dict]:
    """Scan a project directory for dependency vulnerabilities.

    Scans requirements.txt, pyproject.toml, and package.json.
    All lookups are local — no network calls.
    """
    all_findings = []

    # Python: requirements.txt
    req_file = project_path / "requirements.txt"
    if req_file.exists():
        findings = scan_requirements_txt(req_file)
        for f in findings:
            f["file"] = str(req_file)
        all_findings.extend(findings)

    # Python: pyproject.toml
    pyproject = project_path / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text()
            deps_match = re.search(
                r'dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL
            )
            if deps_match:
                for line in deps_match.group(1).split("\n"):
                    match = re.match(
                        r'^\s*"([a-zA-Z0-9_-]+)[><=!~]*([0-9][0-9.]*)', line
                    )
                    if match:
                        pkg_name = match.group(1).lower()
                        version = match.group(2)

                        osv_vulns = _query_local_osv(pkg_name, version)
                        if osv_vulns:
                            for v in osv_vulns:
                                all_findings.append(
                                    {
                                        "package": pkg_name,
                                        "version": version,
                                        "cwe": v.get("cwe", "CWE-000"),
                                        "description": v.get(
                                            "summary", "Vulnerability found"
                                        ),
                                        "fix": f"Upgrade {pkg_name}",
                                        "file": str(pyproject),
                                        "source": "osv_local",
                                    }
                                )
                        elif pkg_name in _LOCAL_VULN_DB:
                            vuln = _LOCAL_VULN_DB[pkg_name]
                            if _version_below(version, vuln["vulnerable_below"]):
                                all_findings.append(
                                    {
                                        "package": pkg_name,
                                        "version": version,
                                        "cwe": vuln["cwe"],
                                        "description": vuln["description"],
                                        "fix": f"Upgrade {pkg_name} to >= {vuln['vulnerable_below']}",
                                        "file": str(pyproject),
                                    }
                                )
        except Exception:
            pass

    # Node.js: package.json
    pkg_json = project_path / "package.json"
    if pkg_json.exists():
        findings = scan_package_json(pkg_json)
        for f in findings:
            f["file"] = str(pkg_json)
        all_findings.extend(findings)

    return all_findings
