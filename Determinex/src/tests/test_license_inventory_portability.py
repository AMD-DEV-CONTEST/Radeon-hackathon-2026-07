"""The published licence inventory must not carry one machine's filesystem layout.

assurance/licenses/license_inventory.json is a PUBLISHED compliance artifact -- it ships in
the public mirror. Every one of its 179 rows used to record an absolute path
(C:\\Dev\\Determinex\\.venv\\Lib\\site-packages\\...), which leaked where the checkout lives
and made the rows meaningless to anyone whose repo is somewhere else. The compliance content
is the relative path plus the SPDX id; the drive letter never was.

These tests guard both directions, because a guard that has only ever been observed agreeing
has not been tested:
  - the shipped artifact contains no absolute path, AND
  - _rel() actually converts one (a test that only checks the current file would keep passing
    if _rel were replaced with `str`, since the file could simply be stale).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

INVENTORY = ROOT / "assurance" / "licenses" / "license_inventory.json"

_ABSOLUTE_MARKERS = (":\\", ":/", "\\\\")


def _looks_absolute(value: str) -> bool:
    if value.startswith("/"):
        return True
    return any(m in value for m in _ABSOLUTE_MARKERS)


@pytest.mark.skipif(not INVENTORY.exists(), reason="inventory not generated in this checkout")
def test_published_inventory_has_no_absolute_paths() -> None:
    rows = json.loads(INVENTORY.read_text(encoding="utf-8"))["rows"]
    assert rows, "an empty inventory would pass this test without proving anything"

    offenders = [
        (i, k, v)
        for i, row in enumerate(rows)
        for k, v in row.items()
        if isinstance(v, str) and _looks_absolute(v)
    ]
    assert not offenders, (
        f"{len(offenders)} field(s) in the published licence inventory carry an absolute "
        f"path, which publishes this machine's filesystem layout. First few: "
        f"{offenders[:3]}"
    )


@pytest.mark.skipif(not INVENTORY.exists(), reason="inventory not generated in this checkout")
def test_inventory_still_has_real_content() -> None:
    """Stripping paths must not have stripped the compliance data with them."""
    data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    rows = data["rows"]
    assert len(rows) > 100, f"only {len(rows)} rows -- the scan lost its inputs"
    assert all(r.get("path") for r in rows), (
        "a row with no path at all is not portable, it is empty"
    )
    assert any(r.get("spdx_id") for r in rows), "no SPDX ids -> this is not a licence inventory"
    assert "blocked_count" in data


def test_rel_actually_converts_an_absolute_path() -> None:
    """NEGATIVE CONTROL: feed _rel a known-absolute path and prove it does the work.

    Without this, replacing _rel with `str` would leave both tests above green for as long as
    nobody regenerated the file.
    """
    from security.license_scan import ROOT as SCAN_ROOT
    from security.license_scan import _rel

    inside = SCAN_ROOT / ".venv" / "Lib" / "site-packages" / "example-1.0.dist-info"
    out = _rel(inside)
    assert not _looks_absolute(out), f"_rel returned an absolute path: {out!r}"
    assert out == ".venv/Lib/site-packages/example-1.0.dist-info"

    # Something genuinely outside the checkout must degrade to a basename, never to an
    # absolute path -- an inventory row is worth less than leaking where the repo sits.
    outside = _rel(Path(SCAN_ROOT).anchor + "somewhere/else/pkg-2.0.dist-info")
    assert not _looks_absolute(outside), f"outside-root path leaked: {outside!r}"
    assert outside == "pkg-2.0.dist-info"

    # Non-path values pass through untouched.
    assert _rel("classifier") == "classifier"
    assert _rel("") == ""
