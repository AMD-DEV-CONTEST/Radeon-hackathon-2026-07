from __future__ import annotations

from pathlib import Path

import pytest

from app.evidence.workspace import CaseWorkspace
from app.rag.corpus import LegalCorpusStore, load_manifest
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.index import LegalVectorIndex
from app.rag.reranker import HeuristicReranker
from app.rag.retrieval import HybridLegalRetriever
from app.schemas.evidence import (
    EvidenceConflict,
    EvidenceNode,
    Fact,
    FactStatus,
    SourceRole,
)


@pytest.fixture
def legal_retriever(tmp_path: Path):
    documents, chunks = load_manifest("data/laws/source_manifest.json")
    corpus = LegalCorpusStore(tmp_path / "legal.sqlite3")
    corpus.replace(documents, chunks)
    index = LegalVectorIndex(tmp_path / "qdrant", HashEmbeddingProvider(dimension=128))
    index.rebuild(chunks)
    retriever = HybridLegalRetriever(
        corpus,
        index,
        reranker=HeuristicReranker("test fallback"),
    )
    try:
        yield retriever
    finally:
        retriever.close()


@pytest.fixture
def demo_case(tmp_path: Path):
    case_id = "CASE-TEST-ORCHESTRATOR"
    workspace = CaseWorkspace(tmp_path / "cases")
    workspace.create_case(case_id)
    fixture = tmp_path / "synthetic.pdf"
    fixture.write_bytes(b"%PDF-1.4\n% synthetic test fixture\n%%EOF\n")
    source = workspace.ingest_file(
        case_id,
        fixture,
        role=SourceRole.ACCIDENT_DETERMINATION,
    )
    node_id = "NODE-TEST-001"
    store = workspace.store(case_id)
    store.add_node(
        EvidenceNode(
            node_id=node_id,
            case_id=case_id,
            source_id=source.source_id,
            node_type="document_text",
            locator={"page": 1},
            content="合成测试材料",
            extraction_method="test_fixture",
        )
    )
    rows = (
        (
            "FACT-TEST-001",
            "事故认定书送达日期为2026-07-28",
            "事故认定书",
            "送达日期",
            "2026-07-28",
        ),
        (
            "FACT-TEST-002",
            "两轮车辆登记类型为电动自行车",
            "两轮车辆",
            "登记类型",
            "电动自行车",
        ),
        (
            "FACT-TEST-003",
            "两轮车辆最高设计时速为30 km/h",
            "两轮车辆",
            "最高设计时速",
            "30 km/h",
        ),
        (
            "FACT-TEST-004",
            "两轮车辆在机动车道逆行",
            "两轮车辆",
            "行驶行为",
            "机动车道逆行",
        ),
        (
            "FACT-TEST-005",
            "机动车驾驶人在碰撞前未充分观察",
            "机动车驾驶人",
            "驾驶行为",
            "未充分观察",
        ),
    )
    for fact_id, statement, subject, predicate, value in rows:
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
                extraction_method="test_fixture",
            )
        )
    return workspace, case_id


def _business_case(
    root: Path,
    *,
    case_id: str,
    roles: list[SourceRole],
    fact_rows: list[tuple[str, str, str, str]],
    conflicts: list[tuple[str, ...]] | None = None,
):
    workspace = CaseWorkspace(root / case_id)
    workspace.create_case(case_id)
    store = workspace.store(case_id)
    node_ids: list[str] = []
    for index, role in enumerate(roles, start=1):
        source_path = root / f"{case_id}-{index}.pdf"
        source_path.write_bytes(f"%PDF-1.4\n% {case_id} {index}\n%%EOF\n".encode())
        source = workspace.ingest_file(case_id, source_path, role=role)
        node_id = f"NODE-{case_id}-{index:02d}"
        store.add_node(
            EvidenceNode(
                node_id=node_id,
                case_id=case_id,
                source_id=source.source_id,
                node_type="document_text",
                locator={"page": 1},
                content=f"{role.value} synthetic fixture",
                extraction_method="test_fixture",
            )
        )
        node_ids.append(node_id)
    for index, (statement, subject, predicate, value) in enumerate(fact_rows, start=1):
        store.add_fact(
            Fact(
                fact_id=f"FACT-{case_id}-{index:03d}",
                case_id=case_id,
                statement=statement,
                subject=subject,
                predicate=predicate,
                value=value,
                source_node_ids=(node_ids[(index - 1) % len(node_ids)],),
                confidence=0.94,
                status=FactStatus.VERIFIED,
                extraction_method="test_fixture",
            )
        )
    if conflicts:
        store.replace_conflicts(
            case_id,
            [
                EvidenceConflict(
                    conflict_id=f"CONFLICT-{case_id}-{index}",
                    case_id=case_id,
                    subject="两轮车辆",
                    predicate="登记类型",
                    fact_ids=tuple(fact_ids),
                    description="登记材料与其他案件材料对车辆登记类型的记载冲突。",
                    severity="blocking",
                )
                for index, fact_ids in enumerate(conflicts, start=1)
            ],
        )
    return workspace, case_id


@pytest.fixture
def demo_case_a(tmp_path: Path):
    roles = [
        SourceRole.ACCIDENT_DETERMINATION,
        SourceRole.DELIVERY_INFORMATION,
        SourceRole.DASHCAM_VIDEO,
        SourceRole.SCENE_PHOTO,
        SourceRole.ROAD_SIGNAL_EVIDENCE,
        SourceRole.VEHICLE_REGISTRATION,
        SourceRole.VEHICLE_CERTIFICATE_CCC,
        SourceRole.VEHICLE_TECHNICAL_PARAMETERS,
        SourceRole.APPRAISAL_REPORT,
        SourceRole.INQUIRY_RECORD,
        SourceRole.MEDICAL_RECORD,
        SourceRole.INSURANCE_POLICY,
    ]
    rows = [
        ("事故发生时间为2026-07-20 08:30", "事故", "事故时间", "2026-07-20"),
        ("事故认定书送达日期为2026-07-28", "事故认定书", "送达日期", "2026-07-28"),
        (
            "两轮车辆碰撞前沿机动车道逆行进入路口",
            "两轮车辆",
            "行驶方向",
            "逆行进入路口",
        ),
        (
            "信号相位记录显示两轮车辆违反停止信号",
            "两轮车辆",
            "信号灯状态",
            "违反停止信号",
        ),
        ("两轮车辆在进入路口前未让优先通行车辆", "两轮车辆", "让行义务", "未让行"),
        ("机动车驾驶人在碰撞前疏于观察", "机动车驾驶人", "观察注意", "疏于观察"),
        ("机动车采取制动但现场记录有刹车痕迹", "机动车驾驶人", "制动避让", "已制动"),
        ("现场勘查图标注碰撞点位于路口机动车道内", "事故", "碰撞点", "机动车道内"),
        ("两轮车辆登记类型为电动自行车", "两轮车辆", "登记类型", "电动自行车"),
        ("车辆属性鉴定意见为非机动车", "两轮车辆", "车辆属性鉴定", "非机动车"),
        ("两轮车辆最高设计车速为25 km/h", "两轮车辆", "最高设计车速", "25 km/h"),
        ("两轮车辆整车质量为52 kg，使用锂离子电池", "两轮车辆", "整车质量", "52 kg"),
        (
            "两轮车辆电机额定连续输出功率为400 W",
            "两轮车辆",
            "额定连续输出功率",
            "400 W",
        ),
        ("车辆合格证和CCC记录与实车车型一致", "两轮车辆", "产品合格证/CCC", "已核验"),
        ("保险单记载已投保交强险及商业险", "机动车", "保险单", "交强险及商业险"),
    ]
    return _business_case(
        tmp_path,
        case_id="CASE-DEMO-A",
        roles=roles,
        fact_rows=rows,
    )


@pytest.fixture
def demo_case_b(tmp_path: Path):
    return _business_case(
        tmp_path,
        case_id="CASE-DEMO-B",
        roles=[
            SourceRole.ACCIDENT_DETERMINATION,
            SourceRole.SCENE_PHOTO,
        ],
        fact_rows=[
            ("事故发生时间为2026-07-20", "事故", "事故时间", "2026-07-20"),
            ("机动车与两轮车辆在路口发生碰撞", "事故", "碰撞位置", "路口"),
            ("两轮车辆最高设计车速为45 km/h", "两轮车辆", "最高设计车速", "45 km/h"),
        ],
    )


@pytest.fixture
def demo_case_c(tmp_path: Path):
    case_id = "CASE-DEMO-C"
    rows = [
        ("事故发生时间为2026-07-20", "事故", "事故时间", "2026-07-20"),
        ("认定书记载两轮车辆登记为电动自行车", "两轮车辆", "登记类型", "电动自行车"),
        ("照片中的登记查询记录显示为普通摩托车", "两轮车辆", "登记类型", "普通摩托车"),
        ("视频显示两轮车辆由支路驶入", "两轮车辆", "驶入方向", "由支路驶入"),
        ("认定书记载两轮车辆由主路驶入", "两轮车辆", "驶入方向", "由主路驶入"),
    ]
    return _business_case(
        tmp_path,
        case_id=case_id,
        roles=[
            SourceRole.ACCIDENT_DETERMINATION,
            SourceRole.DASHCAM_VIDEO,
            SourceRole.SCENE_PHOTO,
            SourceRole.VEHICLE_REGISTRATION,
        ],
        fact_rows=rows,
        conflicts=[
            (f"FACT-{case_id}-002", f"FACT-{case_id}-003"),
            (f"FACT-{case_id}-004", f"FACT-{case_id}-005"),
        ],
    )
