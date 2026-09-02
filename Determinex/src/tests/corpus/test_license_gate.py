"""
Corpus license gate tests.

Verifies that the license detection and SPDX normalization pipeline
correctly classifies licenses into green/yellow/red/unknown buckets.

CORPUS_LICENSE_LOCK_001 partial coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from corpus.code_ingest.license_detector import detect
from corpus.code_ingest.spdx_normalizer import (
    GREEN_LICENSES,
    RED_LICENSES,
    bucket,
    ingest_allowed,
    normalize,
)

# ---------------------------------------------------------------------------
# SPDX normalizer unit tests
# ---------------------------------------------------------------------------


class TestSPDXNormalizer:
    def test_mit_normalized(self):
        assert normalize("MIT License") == "MIT"

    def test_mit_exact(self):
        assert normalize("MIT") == "MIT"

    def test_apache_2_normalized(self):
        result = normalize("Apache License, Version 2.0")
        assert result == "Apache-2.0"

    def test_apache_short(self):
        assert normalize("Apache-2.0") == "Apache-2.0"

    def test_bsd_3_normalized(self):
        result = normalize("BSD 3-Clause License")
        assert result == "BSD-3-Clause"

    def test_bsd_2_normalized(self):
        result = normalize("Simplified BSD License")
        assert result == "BSD-2-Clause"

    def test_isc_normalized(self):
        assert normalize("ISC") == "ISC"

    def test_gpl_3_normalized(self):
        result = normalize("GNU General Public License version 3")
        assert result == "GPL-3.0-only"

    def test_gpl_2_normalized(self):
        result = normalize("GNU General Public License v2")
        assert result == "GPL-2.0-only"

    def test_agpl_3_normalized(self):
        result = normalize("Affero General Public License v3")
        assert result == "AGPL-3.0-only"

    def test_spdx_header_extraction(self):
        # SPDX-License-Identifier in file header
        text = "// SPDX-License-Identifier: Apache-2.0\n// Copyright 2024"
        assert normalize(text) == "Apache-2.0"

    def test_unknown_returns_none(self):
        assert normalize("Some Proprietary License v99") is None

    def test_empty_returns_none(self):
        assert normalize("") is None


class TestBucketClassification:
    def test_mit_is_green(self):
        assert bucket("MIT") == "green"
        assert ingest_allowed("MIT") is True

    def test_apache_is_green(self):
        assert bucket("Apache-2.0") == "green"

    def test_bsd3_is_green(self):
        assert bucket("BSD-3-Clause") == "green"

    def test_isc_is_green(self):
        assert bucket("ISC") == "green"

    def test_gpl3_is_red(self):
        assert bucket("GPL-3.0-only") == "red"
        assert ingest_allowed("GPL-3.0-only") is False

    def test_agpl_is_red(self):
        assert bucket("AGPL-3.0-only") == "red"
        assert ingest_allowed("AGPL-3.0-only") is False

    def test_mpl2_is_yellow(self):
        assert bucket("MPL-2.0") == "yellow"
        assert ingest_allowed("MPL-2.0") is False  # yellow is not auto-ingest

    def test_unknown_is_unknown(self):
        assert bucket(None) == "unknown"
        assert ingest_allowed(None) is False

    def test_all_green_licenses_ingest_allowed(self):
        for lic in GREEN_LICENSES:
            assert ingest_allowed(lic), f"{lic} should be ingest_allowed"

    def test_all_red_licenses_blocked(self):
        for lic in RED_LICENSES:
            assert not ingest_allowed(lic), f"{lic} should NOT be ingest_allowed"


# ---------------------------------------------------------------------------
# License detector integration tests
# ---------------------------------------------------------------------------


class TestLicenseDetector:
    def test_mit_license_file(self, tmp_path):
        (tmp_path / "LICENSE").write_text(
            "MIT License\n\nCopyright (c) 2024 Test\n\nPermission is hereby granted...",
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert result.spdx_id == "MIT"
        assert result.bucket == "green"
        assert result.ingest_allowed is True

    def test_apache_license_file(self, tmp_path):
        (tmp_path / "LICENSE.txt").write_text(
            "Apache License\nVersion 2.0, January 2004",
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert result.spdx_id == "Apache-2.0"
        assert result.ingest_allowed is True

    def test_gpl_license_file_is_red(self, tmp_path):
        (tmp_path / "LICENSE").write_text(
            "GNU GENERAL PUBLIC LICENSE\nVersion 3, June 2007",
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert result.spdx_id == "GPL-3.0-only"
        assert result.bucket == "red"
        assert result.ingest_allowed is False

    def test_spdx_header_in_source_file(self, tmp_path):
        src = tmp_path / "main.py"
        src.write_text(
            "# SPDX-License-Identifier: MIT\n# Copyright 2024\n\ndef main(): pass\n",
            encoding="utf-8",
        )
        result = detect(src)
        assert result.spdx_id == "MIT"
        assert result.ingest_allowed is True

    def test_no_license_is_unknown(self, tmp_path):
        src = tmp_path / "code.py"
        src.write_text("def foo(): return 42\n", encoding="utf-8")
        result = detect(src)
        assert result.spdx_id is None
        assert result.bucket == "unknown"
        assert result.ingest_allowed is False

    def test_package_json_license_field(self, tmp_path):
        import json

        (tmp_path / "package.json").write_text(
            json.dumps({"name": "mylib", "version": "1.0.0", "license": "ISC"}),
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert result.spdx_id == "ISC"
        assert result.ingest_allowed is True

    def test_result_has_source_info(self, tmp_path):
        (tmp_path / "LICENSE").write_text("MIT License", encoding="utf-8")
        result = detect(tmp_path)
        assert result.source != ""
        assert result.confidence in ("high", "medium", "low")
