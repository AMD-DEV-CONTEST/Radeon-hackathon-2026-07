"""Repository license scan wrapper for assurance artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from corpus.code_ingest.license_detector import detect

DEFAULT_OUT = ROOT / "assurance" / "licenses" / "license_inventory.json"


def _rel(p: object) -> str:
    """Path relative to ROOT, with forward slashes. Machine-independent by construction.

    Falls back to the basename rather than the absolute path when something genuinely lives
    outside the checkout -- an inventory row is worth less than leaking where the repo sits,
    and this file is published. Non-path values pass through unchanged (`source` is sometimes
    a short string like "classifier" rather than a file).
    """
    if not p:
        return ""
    s = str(p)
    if not (("/" in s) or ("\\" in s)):
        return s  # not a path at all
    try:
        return Path(s).resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return Path(s).name


def dependency_paths() -> list[Path]:
    """The third-party licence surfaces that actually ship with this product.

    WHY THIS EXISTS (2026-07-30). `paths` defaulted to `[ROOT]`, and `scan()` calls `detect()`
    once per element -- so the inventory had exactly ONE row: the repository root, whose licence
    is our own AGPL. `security_gate` then explicitly exempts that row, which left `real_blocks`
    permanently empty. A gate named "license_scan", underwriting `license_inventory_reviewed:
    true` in the legal packet for an AGPL release, had therefore never examined a single
    dependency and could only fail if our own LICENSE stopped being AGPL.

    Python distributions expose their licence in `*.dist-info` (LICENSE file and/or METADATA);
    npm packages in their own directory. Both are directories `detect()` already understands.
    Direct npm dependencies only -- the full transitive tree is tens of thousands of directories
    and belongs to a dedicated SBOM tool, not to a gate that has to finish.
    """
    paths: list[Path] = []

    for site in (
        ROOT / ".venv" / "Lib" / "site-packages",
        ROOT / ".venv" / "lib" / "site-packages",
    ):
        if site.is_dir():
            paths.extend(sorted(p for p in site.glob("*.dist-info") if p.is_dir()))
            break

    package_json = ROOT / "frontend" / "package.json"
    node_modules = ROOT / "frontend" / "node_modules"
    if package_json.is_file() and node_modules.is_dir():
        try:
            declared = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            declared = {}
        for name in sorted(declared.get("dependencies") or {}):
            candidate = node_modules.joinpath(*name.split("/"))
            if candidate.is_dir():
                paths.append(candidate)

    return paths


# A wheel's licence usually is NOT a LICENSE file. It lives in dist-info/METADATA, either in the
# `License:` header or, more often, in a trove classifier. `detect()` looks for licence FILES, so
# on first run 144 of 174 dependency surfaces came back spdx_id=None -- which would have converted
# this gate from never-failing to always-failing, and an always-failing gate gets switched off
# rather than fixed. Reading METADATA is reading the declaration that actually exists.
_CLASSIFIER_SPDX = {
    "MIT License": "MIT",
    "MIT No Attribution License (MIT-0)": "MIT-0",
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0-only",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "GNU Affero General Public License v3": "AGPL-3.0-only",
    "The Unlicense (Unlicense)": "Unlicense",
    "zlib/libpng License": "Zlib",
}


def _license_from_dist_info(path: Path) -> tuple[str | None, str]:
    """(spdx_id, source) read from a dist-info METADATA declaration, or (None, "")."""
    metadata = path / "METADATA"
    if not metadata.is_file():
        return None, ""
    try:
        text = metadata.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, ""

    classifier_hit: tuple[str, str] | None = None
    for raw in text.splitlines():
        if not raw.strip():
            break  # headers end at the first blank line; the body is the long description
        if raw.startswith("License-Expression:"):
            value = raw.split(":", 1)[1].strip()
            if value:
                return value, "dist-info METADATA License-Expression"
        if raw.startswith("Classifier: License ::"):
            leaf = raw.split("::")[-1].strip()
            mapped = _CLASSIFIER_SPDX.get(leaf)
            if mapped and classifier_hit is None:
                classifier_hit = (mapped, f"dist-info METADATA classifier ({leaf})")
        if raw.startswith("License:"):
            value = raw.split(":", 1)[1].strip()
            # Many wheels put the entire licence TEXT here; only short values are an identifier.
            if value and value.upper() not in {"UNKNOWN", ""} and len(value) <= 40:
                return value, "dist-info METADATA License"
    if classifier_hit:
        return classifier_hit
    return None, ""


# Documented exceptions, with the reason recorded in the artifact rather than applied silently.
# A gate that hides its exemptions is the failure mode this whole sweep was about, so each entry
# states WHY, and anything not listed here still blocks.
_LICENCE_EXCEPTIONS = {
    "pyinstaller": (
        "GPL-2.0-WITH-Bootloader-exception",
        "PyInstaller is GPL-2.0 WITH the Bootloader Exception, which explicitly permits building "
        "and distributing applications under any licence. Only the bootloader is linked into our "
        "output, and the exception exists for exactly this use. Not a copyleft obligation on "
        "Determinex.",
    ),
}


def _is_first_party(name: str) -> bool:
    """Our own distributions, installed into the venv by `pip install -e .`.

    These show up as AGPL-3.0-only (correctly -- it is us) or as unknown for the local preview
    packages. Counting our own licence as a third-party conflict would make the inventory noise.
    """
    return name.startswith(("determinex-", "determinex_"))


def scan(paths: list[Path]) -> dict:
    rows = []
    for path in paths:
        result = detect(path)
        spdx = result.spdx_id
        bucket_name = result.bucket
        allowed = result.ingest_allowed
        source = result.source
        confidence = result.confidence
        if spdx is None and path.name.endswith(".dist-info"):
            declared, declared_source = _license_from_dist_info(path)
            if declared:
                from corpus.code_ingest.license_detector import (  # local: avoid import cycle
                    bucket as _bucket,
                )
                from corpus.code_ingest.license_detector import (
                    ingest_allowed as _ingest_allowed,
                )
                from corpus.code_ingest.license_detector import (
                    normalize as _normalize,
                )

                spdx = _normalize(declared)
                bucket_name = _bucket(spdx)
                allowed = _ingest_allowed(spdx)
                source = declared_source
                confidence = "medium"
        distribution = path.name.split("-")[0].lower().replace("_", "-")
        note = ""
        if _is_first_party(path.name):
            allowed = True
            bucket_name = "first_party"
            note = "Determinex's own distribution installed into the venv; not a third party."
        elif distribution in _LICENCE_EXCEPTIONS and not allowed:
            corrected, why = _LICENCE_EXCEPTIONS[distribution]
            spdx = corrected
            allowed = True
            bucket_name = "green_by_exception"
            note = why
        rows.append(
            {
                # Relative to ROOT, not absolute. The inventory is a PUBLISHED compliance
                # artifact -- every one of its 179 rows carried a full
                # C:\Dev\Determinex\.venv\Lib\site-packages\... path, so the public repo was
                # shipping one machine's filesystem layout, and the rows were unreadable to
                # anyone whose checkout lives anywhere else. Relative paths are the actual
                # compliance content; the drive letter never was.
                "path": _rel(path),
                "spdx_id": spdx,
                "bucket": bucket_name,
                "ingest_allowed": allowed,
                "source": _rel(source),
                "confidence": confidence,
                "note": note,
            }
        )
    return {
        "schema_version": "determinex-license-inventory-v1",
        "rows": rows,
        "blocked_count": sum(1 for row in rows if not row["ingest_allowed"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # No default of [ROOT]: that made the whole inventory one row for our own repository. With no
    # arguments the scan now covers the third-party licence surfaces that actually ship.
    parser.add_argument("paths", nargs="*", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    targets = list(args.paths) if args.paths else dependency_paths()
    if not targets:
        # Nothing to scan is not a pass: it means the environment was not installed, so no licence
        # was examined. Reporting "0 blocked" here would be the same silence-looks-like-safety
        # shape this scanner is meant to prevent.
        print(
            "license_scan: no dependency licence surfaces found (is the venv installed?)",
            file=sys.stderr,
        )
        return 2
    report = scan(targets)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.out)
    print(
        json.dumps(
            {"blocked_count": report["blocked_count"], "rows": len(report["rows"])}, indent=2
        )
    )
    return 0 if report["blocked_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
