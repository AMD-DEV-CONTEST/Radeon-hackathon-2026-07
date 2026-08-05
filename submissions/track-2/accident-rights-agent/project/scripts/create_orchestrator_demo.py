#!/usr/bin/env python3
"""Create an idempotent synthetic case after the evidence-reconstruction stage."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evidence.workspace import CaseWorkspace
from app.schemas.evidence import (
    EvidenceNode,
    Fact,
    FactStatus,
    SourceRole,
)


DEMO_FACTS = (
    ("FACT-DEMO-001", "事故认定书送达日期为2026-07-28", "事故认定书", "送达日期", "2026-07-28"),
    ("FACT-DEMO-002", "两轮车辆登记类型为电动自行车", "两轮车辆", "登记类型", "电动自行车"),
    ("FACT-DEMO-003", "两轮车辆最高设计时速为30 km/h", "两轮车辆", "最高设计时速", "30 km/h"),
    ("FACT-DEMO-004", "两轮车辆在机动车道逆行", "两轮车辆", "行驶行为", "机动车道逆行"),
    ("FACT-DEMO-005", "机动车驾驶人在碰撞前未充分观察", "机动车驾驶人", "驾驶行为", "未充分观察"),
    ("FACT-DEMO-006", "机动车车辆标识为沪A12345", "机动车", "车辆标识", "沪A12345"),
)


def create_demo(root: Path, case_id: str) -> str:
    workspace = CaseWorkspace(root)
    database = workspace.case_dir(case_id) / "case.sqlite3"
    if not database.exists():
        workspace.create_case(case_id)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fixture:
        fixture.write(
            b"%PDF-1.4\n% Synthetic orchestrator fixture; not a real case.\n%%EOF\n"
        )
        fixture.flush()
        source = workspace.ingest_file(
            case_id,
            fixture.name,
            role=SourceRole.ACCIDENT_DETERMINATION,
            original_name="synthetic-accident-determination.pdf",
        )
    node_id = "NODE-DEMO-DOCUMENT-001"
    store = workspace.store(case_id)
    store.add_node(
        EvidenceNode(
            node_id=node_id,
            case_id=case_id,
            source_id=source.source_id,
            node_type="document_text",
            locator={"page": 1, "section": "synthetic"},
            content="\n".join(item[1] for item in DEMO_FACTS),
            confidence=1.0,
            extraction_method="synthetic_demo_fixture",
            metadata={"synthetic": True, "contains_personal_data": False},
        )
    )
    for fact_id, statement, subject, predicate, value in DEMO_FACTS:
        store.add_fact(
            Fact(
                fact_id=fact_id,
                case_id=case_id,
                statement=statement,
                subject=subject,
                predicate=predicate,
                value=value,
                source_node_ids=(node_id,),
                confidence=0.95,
                status=FactStatus.VERIFIED,
                extraction_method="synthetic_demo_fixture",
                uncertainty="合成数据，仅用于状态图验收。",
            )
        )
    store.audit(
        case_id,
        "synthetic_orchestrator_demo_ready",
        {"fact_count": len(DEMO_FACTS), "source_id": source.source_id},
        "demo_fixture",
    )
    return case_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-root", type=Path, default=Path("data/cases"))
    parser.add_argument("--case-id", default="CASE-ORCHESTRATOR-DEMO")
    args = parser.parse_args()
    print(create_demo(args.case_root, args.case_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
