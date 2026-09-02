import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.validate_pr_title import OFFICIAL_PR_TITLE, validate_title
from scripts.validate_specs import check_spec


class ValidatePrTitleTests(unittest.TestCase):
    def test_accepts_fixed_official_title(self) -> None:
        self.assertIsNone(validate_title(OFFICIAL_PR_TITLE))

    def test_rejects_non_official_title(self) -> None:
        self.assertIsNotNone(validate_title("feat: add agent"))

    def test_rejects_empty_required_field(self) -> None:
        self.assertIsNotNone(validate_title("Track 2, , ProjectPack Office Agent"))

    def test_rejects_other_track_team_or_application(self) -> None:
        self.assertIsNotNone(validate_title("Track 2, Other Team, ProjectPack Office Agent"))


class ValidateSpecsTests(unittest.TestCase):
    def test_ignores_non_spec_support_directory(self) -> None:
        with TemporaryDirectory() as directory:
            self.assertEqual(check_spec(Path(directory)), [])

    def test_requires_report_for_verified_s2_spec(self) -> None:
        with TemporaryDirectory() as directory:
            spec_dir = Path(directory)
            (spec_dir / "PRODUCT.md").write_text("# Product\n", encoding="utf-8")
            (spec_dir / "TECH.md").write_text(
                "# Technical\n\n- Level: S2\n- Status: verified\n",
                encoding="utf-8",
            )
            self.assertTrue(any("TEST_REPORT.md" in error for error in check_spec(spec_dir)))
