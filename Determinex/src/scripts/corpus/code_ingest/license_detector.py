"""
License detector for corpus ingest pipeline.

Detection priority (highest confidence first):
  1. SPDX-License-Identifier header in file
  2. LICENSE / COPYING / LICENSE.txt file in directory
  3. Copyright/license pattern in file header (first 50 lines)
  4. package.json / setup.py / pom.xml / build.gradle license field
  5. README license section mention

Returns a LicenseResult with SPDX identifier and bucket classification.
No license found → bucket="unknown", ingest_allowed=False.
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from corpus.code_ingest.spdx_normalizer import bucket, ingest_allowed, normalize

log = logging.getLogger(__name__)

_LICENSE_FILENAMES = frozenset(
    {
        "LICENSE",
        "LICENSE.txt",
        "LICENSE.md",
        "LICENSE.rst",
        "LICENCE",
        "LICENCE.txt",
        "LICENCE.md",
        "COPYING",
        "COPYING.txt",
        "COPYING.md",
        "LICENSE-MIT",
        "LICENSE-APACHE",
        "LICENSE-BSD",
    }
)

_HEADER_LINES = 50  # scan first N lines of source files for license header


@dataclass
class LicenseResult:
    spdx_id: str | None
    bucket: str  # "green" | "yellow" | "red" | "unknown"
    ingest_allowed: bool
    source: str  # where we found the license info
    raw_text: str  # excerpt that triggered detection
    confidence: str  # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return {
            "spdx_id": self.spdx_id,
            "bucket": self.bucket,
            "ingest_allowed": self.ingest_allowed,
            "source": self.source,
            "confidence": self.confidence,
        }


def detect(path: Path) -> LicenseResult:
    """
    Detect the license for a file or directory.
    Returns LicenseResult. ingest_allowed=False if no green license found.
    """
    if path.is_dir():
        return _detect_directory(path)
    return _detect_file(path)


def _make_result(raw: str, source: str, confidence: str = "high") -> LicenseResult:
    spdx = normalize(raw)
    b = bucket(spdx)
    return LicenseResult(
        spdx_id=spdx,
        bucket=b,
        ingest_allowed=ingest_allowed(spdx),
        source=source,
        raw_text=raw[:200],
        confidence=confidence,
    )


def _unknown() -> LicenseResult:
    return LicenseResult(
        spdx_id=None,
        bucket="unknown",
        ingest_allowed=False,
        source="none",
        raw_text="",
        confidence="low",
    )


def _detect_directory(path: Path) -> LicenseResult:
    # 1. Look for LICENSE file
    for fname in _LICENSE_FILENAMES:
        candidate = path / fname
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
                result = _make_result(text[:2000], source=str(candidate), confidence="high")
                if result.spdx_id:
                    return result
            except Exception:
                pass

    # 2. Check package manifests
    for check in (_check_package_json, _check_setup_py, _check_pom_xml, _check_build_gradle):
        result = check(path)
        if result and result.spdx_id:
            return result

    # 3. Check README
    for readme_name in ("README.md", "README.rst", "README.txt", "README"):
        readme = path / readme_name
        if readme.is_file():
            try:
                text = readme.read_text(encoding="utf-8", errors="replace")
                result = _check_readme_license_section(text, source=str(readme))
                if result and result.spdx_id:
                    return result
            except Exception:
                pass

    return _unknown()


def _detect_file(path: Path) -> LicenseResult:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return _unknown()

    # 1. SPDX header in file (most authoritative)
    header = "\n".join(text.splitlines()[:_HEADER_LINES])
    spdx_match = re.search(r"SPDX-License-Identifier:\s*([^\n\r*]+)", header, re.I)
    if spdx_match:
        raw = spdx_match.group(0).strip()
        result = _make_result(raw, source=f"{path}:header", confidence="high")
        if result.spdx_id:
            return result

    # 2. Try directory-level detection for the parent
    dir_result = _detect_directory(path.parent)
    if dir_result.spdx_id:
        dir_result.source = f"parent_dir:{dir_result.source}"
        dir_result.confidence = "medium"
        return dir_result

    # 3. Copyright mention in header
    copyright_match = re.search(
        r"(mit|apache|bsd|isc|gpl|lgpl|agpl|mpl|cc0|unlicense|mozilla|eclipse).{0,200}(license|licen[cs]ed|copyright)",
        header,
        re.I,
    )
    if copyright_match:
        return _make_result(copyright_match.group(0), source=f"{path}:copyright", confidence="low")

    return _unknown()


def _check_package_json(path: Path) -> LicenseResult | None:
    pkg = path / "package.json"
    if not pkg.is_file():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        license_field = data.get("license", "")
        if license_field:
            return _make_result(license_field, source=str(pkg), confidence="high")
    except Exception:
        pass
    return None


def _check_setup_py(path: Path) -> LicenseResult | None:
    for fname in ("setup.py", "setup.cfg", "pyproject.toml"):
        f = path / fname
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'license\s*[=:]\s*["\']?([^"\'#\n\r,]+)', text, re.I)
            if m:
                return _make_result(m.group(1).strip(), source=str(f), confidence="high")
        except Exception:
            pass
    return None


def _check_pom_xml(path: Path) -> LicenseResult | None:
    pom = path / "pom.xml"
    if not pom.is_file():
        return None
    try:
        tree = ET.parse(pom)
        root = tree.getroot()
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        for lic in root.findall(".//licenses/license", ns) or root.findall(".//licenses/license"):
            name_el = lic.find("name") or lic.find("{http://maven.apache.org/POM/4.0.0}name")
            if name_el is not None and name_el.text:
                return _make_result(name_el.text, source=str(pom), confidence="high")
    except Exception:
        pass
    return None


def _check_build_gradle(path: Path) -> LicenseResult | None:
    for fname in ("build.gradle", "build.gradle.kts"):
        f = path / fname
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'license[dE]?\s*[={("\']+\s*([A-Za-z0-9.\-]+)', text, re.I)
            if m:
                return _make_result(m.group(1), source=str(f), confidence="medium")
        except Exception:
            pass
    return None


def _check_readme_license_section(text: str, source: str) -> LicenseResult | None:
    # Look for a "## License" section and grab the next 200 chars
    m = re.search(r"#+\s*licen[cs]e\b.{0,200}", text, re.I | re.DOTALL)
    if m:
        snippet = m.group(0)
        return _make_result(snippet, source=source, confidence="low")
    return None
