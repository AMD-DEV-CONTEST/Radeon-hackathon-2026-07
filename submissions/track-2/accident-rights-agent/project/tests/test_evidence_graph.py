from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.evidence.conflicts import detect_conflicts
from app.evidence.database import EvidenceStore
from app.evidence.image_parser import parse_image
from app.evidence.workspace import CaseWorkspace
from app.schemas.evidence import Fact, SourceRole


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMOKE_IMAGE = PROJECT_ROOT / "data/smoke/single/synthetic_intersection.png"


class EvidenceGraphTests(unittest.TestCase):
    def test_fact_is_bound_to_existing_evidence_node(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = CaseWorkspace(Path(directory))
            case_id = workspace.create_case("CASE-GRAPH-001")
            source = workspace.ingest_file(
                case_id, SMOKE_IMAGE, role=SourceRole.SCENE_PHOTO
            )
            node = parse_image(source, workspace.resolve_source(source))
            store = workspace.store(case_id)
            store.add_node(node)
            fact = Fact(
                fact_id="FACT-001",
                case_id=case_id,
                statement="画面中可见一辆白色汽车。",
                subject="汽车",
                predicate="颜色",
                value="白色",
                source_node_ids=(node.node_id,),
                confidence=0.9,
            )
            store.add_fact(fact)
            exported = store.export_case(case_id)
            self.assertEqual(exported["facts"][0]["source_node_ids"], [node.node_id])

    def test_foreign_node_reference_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceStore(Path(directory) / "case.sqlite3")
            store.initialize("CASE-GRAPH-002")
            fact = Fact(
                fact_id="FACT-ORPHAN",
                case_id="CASE-GRAPH-002",
                statement="无来源事实",
                subject="车辆",
                predicate="颜色",
                value="白色",
                source_node_ids=("NODE-MISSING",),
                confidence=0.8,
            )
            with self.assertRaises(Exception):
                store.add_fact(fact)

    def test_detects_single_value_conflict(self) -> None:
        facts = [
            Fact(
                fact_id="FACT-A",
                case_id="CASE-1",
                statement="材料A记载信号灯为红灯",
                subject="事发方向信号灯",
                predicate="信号灯状态",
                value="红灯",
                source_node_ids=("NODE-A",),
                confidence=0.9,
            ),
            Fact(
                fact_id="FACT-B",
                case_id="CASE-1",
                statement="材料B显示信号灯为绿灯",
                subject="事发方向信号灯",
                predicate="信号灯状态",
                value="绿灯",
                source_node_ids=("NODE-B",),
                confidence=0.8,
            ),
        ]
        conflicts = detect_conflicts(facts)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(set(conflicts[0].fact_ids), {"FACT-A", "FACT-B"})


if __name__ == "__main__":
    unittest.main()
