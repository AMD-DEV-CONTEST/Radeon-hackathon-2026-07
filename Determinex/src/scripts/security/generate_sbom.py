"""
SBOM generator for Determinex's Python environment.

Generates SBOMs in two formats:
  - SPDX 2.3 (JSON) — ISO/IEC 5962:2021
  - CycloneDX 1.5 (JSON)

Output files:
  assurance/sbom/determinex-python.spdx.json
  assurance/sbom/determinex-python.cyclonedx.json

Requires: pip-licenses (pip install pip-licenses)
Falls back to pip list --format=json if pip-licenses unavailable.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SBOM_DIR = _REPO_ROOT / "assurance" / "sbom"

_DETERMINEX_VERSION = "1.0.0-dev"
_NAMESPACE_PREFIX = "https://determinex.local/sbom/python"


def _get_packages_via_pip_licenses() -> list[dict]:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip_licenses",
                "--format=json",
                "--with-urls",
                "--with-license-file",
                "--no-license-path",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _get_packages_via_pip() -> list[dict]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            raw = json.loads(result.stdout)
            return [
                {"Name": p["name"], "Version": p["version"], "License": "NOASSERTION"} for p in raw
            ]
    except Exception:
        pass
    return []


def generate_spdx(packages: list[dict]) -> dict:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    doc_id = hashlib.blake2b((str(now) + "determinex-python").encode(), digest_size=8).hexdigest()

    packages_list = []
    relationships = []

    for pkg in packages:
        name = pkg.get("Name", "unknown")
        version = pkg.get("Version", "")
        license_str = pkg.get("License", "NOASSERTION")
        spdx_id = f"SPDXRef-{name.replace('-', '_').replace('.', '_')}-{version.replace('.', '_')}"
        homepage = pkg.get("URL", "")

        packages_list.append(
            {
                "SPDXID": spdx_id,
                "name": name,
                "versionInfo": version,
                "downloadLocation": homepage or "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": license_str
                if license_str not in ("UNKNOWN", "")
                else "NOASSERTION",
                "licenseDeclared": license_str
                if license_str not in ("UNKNOWN", "")
                else "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": spdx_id,
            }
        )

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"determinex-python-{_DETERMINEX_VERSION}",
        "documentNamespace": f"{_NAMESPACE_PREFIX}/{doc_id}",
        "documentDescribes": [
            f"SPDXRef-{p.get('Name', '').replace('-', '_').replace('.', '_')}-{p.get('Version', '').replace('.', '_')}"
            for p in packages[:5]
        ],
        "packages": packages_list,
        "relationships": relationships,
        "creationInfo": {
            "created": now,
            "creators": ["Tool: determinex-generate-sbom"],
            "licenseListVersion": "3.21",
        },
    }


def generate_cyclonedx(packages: list[dict]) -> dict:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    serial = hashlib.blake2b(
        (str(now) + "determinex-python-cdx").encode(), digest_size=8
    ).hexdigest()

    components = []
    for pkg in packages:
        name = pkg.get("Name", "unknown")
        version = pkg.get("Version", "")
        license_str = pkg.get("License", "")
        comp: dict = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower()}@{version}",
        }
        if license_str and license_str not in ("UNKNOWN", "NOASSERTION", ""):
            comp["licenses"] = [{"expression": license_str}]
        components.append(comp)

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": now,
            "tools": [{"name": "determinex-generate-sbom", "version": _DETERMINEX_VERSION}],
            "component": {
                "type": "application",
                "name": "determinex-python",
                "version": _DETERMINEX_VERSION,
            },
        },
        "components": components,
    }


def run(output_dir: Path | None = None) -> dict[str, Path]:
    out_dir = output_dir or _SBOM_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    packages = _get_packages_via_pip_licenses() or _get_packages_via_pip()
    log.info("[generate_sbom] found %d packages", len(packages))

    spdx = generate_spdx(packages)
    cdx = generate_cyclonedx(packages)

    spdx_path = out_dir / "determinex-python.spdx.json"
    cdx_path = out_dir / "determinex-python.cyclonedx.json"

    spdx_path.write_text(json.dumps(spdx, indent=2), encoding="utf-8")
    cdx_path.write_text(json.dumps(cdx, indent=2), encoding="utf-8")

    log.info("[generate_sbom] wrote %s and %s", spdx_path, cdx_path)
    return {"spdx": spdx_path, "cyclonedx": cdx_path}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    paths = run()
    print(f"SPDX:     {paths['spdx']}")
    print(f"CycloneDX:{paths['cyclonedx']}")
