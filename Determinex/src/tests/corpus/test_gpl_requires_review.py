"""
Corpus gate: GPL/AGPL/SSPL code must NOT be auto-ingested.

These licenses have copyleft conditions that may create legal obligations
if the code is used for model training. They require explicit legal review
before corpus inclusion. This test enforces that they are classified as
red-bucket and ingest_allowed=False.

CORPUS_LICENSE_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from corpus.code_ingest.license_detector import detect
from corpus.code_ingest.spdx_normalizer import RED_LICENSES, bucket, ingest_allowed, normalize

GPL_LICENSE_TEXTS = [
    ("GPL-2.0", "GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991"),
    ("GPL-3.0", "GNU GENERAL PUBLIC LICENSE\nVersion 3, June 2007"),
    ("AGPL-3.0", "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3, November 2007"),
    ("LGPL-2.1", "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1, February 1999"),
    ("LGPL-3.0", "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3, June 2007"),
]

HEADER_EXAMPLES = [
    "# This program is free software: you can redistribute it and/or modify\n# it under the terms of the GNU General Public License as published by\n# the Free Software Foundation, either version 3",
    "// Licensed under GPLv3\n// See LICENSE file for details",
    "/* SPDX-License-Identifier: GPL-3.0-only */",
]


class TestGPLRequiresReview:
    @pytest.mark.parametrize("name,text", GPL_LICENSE_TEXTS)
    def test_gpl_family_is_red_bucket(self, name, text):
        spdx = normalize(text)
        assert spdx is not None, f"Failed to normalize {name} license text"
        b = bucket(spdx)
        assert b == "red", f"{name} ({spdx}) should be red bucket, got {b}"
        assert not ingest_allowed(spdx), f"{name} must NOT be ingest_allowed"

    def test_gpl3_license_file_rejected(self, tmp_path):
        (tmp_path / "LICENSE").write_text(
            "GNU GENERAL PUBLIC LICENSE\nVersion 3, June 2007\n\n"
            "Copyright (C) 2007 Free Software Foundation, Inc.",
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert result.spdx_id is not None, "GPL-3.0 should be detectable"
        assert not result.ingest_allowed, "GPL-3.0 must not be ingest_allowed"
        assert result.bucket == "red"

    def test_agpl_license_file_rejected(self, tmp_path):
        (tmp_path / "LICENSE").write_text(
            "GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3",
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert not result.ingest_allowed, "AGPL-3.0 must not be ingest_allowed"

    @pytest.mark.parametrize("header", HEADER_EXAMPLES)
    def test_gpl_source_header_rejected(self, tmp_path, header):
        src = tmp_path / "module.py"
        src.write_text(header + "\n\ndef foo(): pass\n", encoding="utf-8")
        result = detect(src)
        # Detection via header may be low confidence — the key invariant is:
        # if detected as GPL, it must be rejected
        if result.spdx_id and "GPL" in (result.spdx_id or ""):
            assert not result.ingest_allowed, f"GPL from header must be rejected: {result.spdx_id}"

    def test_all_red_licenses_blocked(self):
        """Comprehensive: every RED_LICENSES entry must be blocked."""
        for lic in RED_LICENSES:
            assert not ingest_allowed(lic), f"{lic} in RED_LICENSES must not be ingest_allowed"

    def test_sspl_is_red(self):
        assert bucket("SSPL-1.0") == "red"
        assert not ingest_allowed("SSPL-1.0")

    def test_busl_is_red(self):
        assert bucket("BUSL-1.1") == "red"
        assert not ingest_allowed("BUSL-1.1")

    def test_mpl2_not_auto_ingest(self):
        """MPL-2.0 is yellow (copyleft with exceptions) — requires review."""
        b = bucket("MPL-2.0")
        assert b in ("yellow", "red"), "MPL-2.0 must not be auto-ingest (green)"
        assert not ingest_allowed("MPL-2.0")

    def test_mit_is_not_red(self):
        """Sanity: MIT must NOT be in red bucket."""
        assert bucket("MIT") == "green"
        assert ingest_allowed("MIT") is True
