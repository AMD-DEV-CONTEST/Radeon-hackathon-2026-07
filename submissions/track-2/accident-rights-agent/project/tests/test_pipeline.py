from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.evidence.fact_extractor import ExtractionResult
from app.evidence.pipeline import EvidenceReconstructionPipeline
from app.evidence.workspace import CaseWorkspace
from app.schemas.evidence import Fact, SourceRole


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMOKE_IMAGE = PROJECT_ROOT / "data/smoke/single/synthetic_intersection.png"


class FakeExtractor:
    def extract_images(self, case_id, nodes_and_paths):
        node = nodes_and_paths[0][0]
        return ExtractionResult(
            facts=(
                Fact(
                    fact_id="FACT-PIPELINE-001",
                    case_id=case_id,
                    statement="画面中可见道路和车辆。",
                    subject="画面",
                    predicate="可见内容",
                    value="道路和车辆",
                    source_node_ids=(node.node_id,),
                    confidence=0.9,
                    model="fake-local",
                ),
            ),
            timeline_events=(),
            model="fake-local",
            latency_seconds=0.01,
            usage={},
            raw_response='{"observations":[],"timeline":[]}',
        )

    def extract_text(self, case_id, node):
        raise AssertionError("This image-only test must not call extract_text.")


class PipelineTests(unittest.TestCase):
    def test_image_case_runs_end_to_end_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = CaseWorkspace(Path(directory))
            case_id = workspace.create_case("CASE-PIPELINE-001")
            workspace.ingest_file(
                case_id, SMOKE_IMAGE, role=SourceRole.SCENE_PHOTO
            )
            summary = EvidenceReconstructionPipeline(
                workspace, FakeExtractor()
            ).reconstruct(case_id)
            self.assertEqual(summary.status, "passed")
            self.assertEqual(summary.node_count, 1)
            self.assertEqual(summary.fact_count, 1)
            exported = workspace.store(case_id).export_case(case_id)
            self.assertEqual(
                exported["facts"][0]["source_node_ids"],
                [exported["evidence_nodes"][0]["node_id"]],
            )


if __name__ == "__main__":
    unittest.main()
