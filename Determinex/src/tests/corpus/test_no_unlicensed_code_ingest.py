"""
Corpus gate: unlicensed code must not be ingest_allowed.

Verifies that files and directories with no detectable license
are classified as bucket="unknown" and ingest_allowed=False.
This is the hard enforcement layer — no license = no corpus entry.

CORPUS_LICENSE_LOCK_001 partial coverage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from corpus.code_ingest.license_detector import detect
from corpus.code_ingest.spdx_normalizer import ingest_allowed


class TestNoUnlicensedIngest:
    def test_file_without_license_header_rejected(self, tmp_path):
        """A source file with no SPDX header and no LICENSE file must be rejected."""
        src = tmp_path / "utility.py"
        src.write_text(
            "def calculate(x, y):\n    return x + y\n",
            encoding="utf-8",
        )
        result = detect(src)
        assert not result.ingest_allowed, (
            f"File without license must not be ingest_allowed, got bucket={result.bucket}"
        )

    def test_directory_without_license_file_rejected(self, tmp_path):
        """A directory with no LICENSE file and no SPDX headers must be rejected."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.java").write_text(
            "public class Main { public static void main(String[] args) {} }",
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert not result.ingest_allowed, "Directory without LICENSE file must be rejected"

    def test_unlicensed_npm_package_rejected(self, tmp_path):
        """A package.json with no license field must be rejected."""
        (tmp_path / "package.json").write_text(
            json.dumps({"name": "mystery-pkg", "version": "0.1.0"}),
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert not result.ingest_allowed, "npm package without license field must be rejected"

    def test_unknown_license_string_rejected(self, tmp_path):
        """A license string that doesn't normalize to a known SPDX ID must be rejected."""
        (tmp_path / "LICENSE").write_text(
            "PROPRIETARY AND CONFIDENTIAL. All rights reserved.",
            encoding="utf-8",
        )
        result = detect(tmp_path)
        assert not result.ingest_allowed, "Proprietary license must not be ingest_allowed"

    def test_empty_license_file_rejected(self, tmp_path):
        """An empty LICENSE file provides no useful signal."""
        (tmp_path / "LICENSE").write_text("", encoding="utf-8")
        result = detect(tmp_path)
        assert not result.ingest_allowed, "Empty LICENSE file must not be ingest_allowed"

    def test_ingest_allowed_only_true_for_green(self):
        """ingest_allowed() must only return True for green-bucket SPDX IDs."""
        assert ingest_allowed("MIT") is True
        assert ingest_allowed("Apache-2.0") is True
        assert ingest_allowed("GPL-3.0-only") is False
        assert ingest_allowed("MPL-2.0") is False
        assert ingest_allowed(None) is False
        assert ingest_allowed("") is False
        assert ingest_allowed("UNKNOWN") is False

    def test_creative_commons_sa_not_ingest_allowed(self):
        """CC-BY-SA is yellow (share-alike creates derivative work issues)."""
        assert ingest_allowed("CC-BY-SA-4.0") is False

    def test_cc0_is_ingest_allowed(self):
        """CC0 (public domain dedication) is green."""
        assert ingest_allowed("CC0-1.0") is True
