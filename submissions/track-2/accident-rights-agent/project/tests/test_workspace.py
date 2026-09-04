from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.evidence.errors import InvalidCaseId, UnsupportedEvidence
from app.evidence.workspace import CaseWorkspace, sanitize_filename
from app.schemas.evidence import SourceKind, SourceRole


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMOKE_IMAGE = PROJECT_ROOT / "data/smoke/single/synthetic_intersection.png"


class WorkspaceTests(unittest.TestCase):
    def test_creates_case_and_deduplicates_immutable_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = CaseWorkspace(Path(directory))
            case_id = workspace.create_case("CASE-TEST-001")
            first = workspace.ingest_file(
                case_id, SMOKE_IMAGE, role=SourceRole.SCENE_PHOTO
            )
            second = workspace.ingest_file(
                case_id, SMOKE_IMAGE, role=SourceRole.OTHER
            )
            self.assertEqual(first.source_id, second.source_id)
            self.assertEqual(first.kind, SourceKind.IMAGE)
            self.assertEqual(first.role, SourceRole.SCENE_PHOTO)
            self.assertEqual(len(workspace.store(case_id).list_sources(case_id)), 1)
            self.assertTrue(workspace.resolve_source(first).is_file())

    def test_rejects_case_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = CaseWorkspace(Path(directory))
            with self.assertRaises(InvalidCaseId):
                workspace.create_case("../outside")

    def test_rejects_extension_signature_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "fake.pdf"
            fake.write_text("not a pdf", encoding="utf-8")
            workspace = CaseWorkspace(root / "cases")
            case_id = workspace.create_case("CASE-TEST-002")
            with self.assertRaises(UnsupportedEvidence):
                workspace.ingest_file(case_id, fake)

    def test_sanitizes_filename(self) -> None:
        self.assertEqual(sanitize_filename("../../事故 认定书?.pdf"), "事故_认定书_.pdf")

    def test_duplicate_can_upgrade_undeclared_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = CaseWorkspace(Path(directory))
            case_id = workspace.create_case("CASE-TEST-003")
            first = workspace.ingest_file(case_id, SMOKE_IMAGE)
            second = workspace.ingest_file(
                case_id, SMOKE_IMAGE, role=SourceRole.SCENE_PHOTO
            )
            self.assertEqual(first.source_id, second.source_id)
            self.assertEqual(second.role, SourceRole.SCENE_PHOTO)


if __name__ == "__main__":
    unittest.main()
