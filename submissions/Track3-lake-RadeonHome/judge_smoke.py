#!/usr/bin/env python3
"""One-command evidence validation for judges. Reads the SHA256SUMS manifest
and checks every file recorded in it.  Prints ``EVIDENCE_OK`` on success.

Usage::

    cd submissions/Track3-lake-RadeonHome
    python3 judge_smoke.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from radeon_home import __version__ as version  # noqa: F401 — smoke import


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "SHA256SUMS"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smoke() -> int:
    assert MANIFEST.exists(), f"Manifest missing: {MANIFEST}"

    lines = MANIFEST.read_text().strip().splitlines()
    assert len(lines) > 20, f"Expected >20 entries, got {len(lines)}"

    checked = 0
    for line in lines:
        expected_hash, _, rel = line.partition("  ")
        rel = rel.strip()
        target = HERE / rel
        if not target.exists():
            print(f"MISSING  {rel}")
            return 1
        actual = _hash(target)
        if actual != expected_hash:
            print(f"BAD HASH {rel}\n  expected {expected_hash}\n  got      {actual}")
            return 1
        checked += 1

    # Verify the technical report PDF is non-empty
    pdf = HERE / "RadeonHome-Technical-Report.pdf"
    assert pdf.exists(), "Technical report PDF missing"
    assert pdf.stat().st_size > 10_000, f"Technical report suspiciously small: {pdf.stat().st_size} B"

    # Verify source code is present
    source = HERE / "source" / "radeon_home"
    assert source.is_dir(), "Source directory missing"
    py_files = list(source.glob("*.py"))
    assert len(py_files) >= 20, f"Expected >=20 source files, got {len(py_files)}"

    # Verify evidence directory exists and is non-empty
    evidence = HERE / "evidence"
    assert evidence.is_dir(), "Evidence directory missing"
    evidence_files = list(evidence.rglob("*"))
    assert len(evidence_files) > 5, f"Expected >5 evidence files, got {len(evidence_files)}"

    print(f"EVIDENCE_OK ({checked} files verified, source={len(py_files)} modules)")
    return 0


if __name__ == "__main__":
    sys.exit(smoke())
