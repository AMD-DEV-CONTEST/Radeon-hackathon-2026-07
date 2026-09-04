"""Deterministic cases used by the local three-agent experience.

The fixtures start after evidence reconstruction. They never pretend to be
real accident materials and do not invoke OCR, video processing, or a model.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.demo.multimodal_assets import (
    materialize_signal_fixture,
    materialize_video_fixture,
    scene_asset_path,
)
from app.evidence.workspace import CaseWorkspace
from app.schemas.evidence import (
    EvidenceConflict,
    EvidenceNode,
    Fact,
    FactStatus,
    SourceRole,
)


@dataclass(frozen=True)
class ExperienceScenario:
    scenario_id: str
    short_label: str
    title: str
    description: str
    expected_effect: str
    roles: tuple[SourceRole, ...]
    fact_rows: tuple[tuple[str, str, str, str], ...]
    conflicts: tuple[tuple[int, ...], ...] = ()

    def public_summary(self) -> dict[str, str]:
        return {
            "scenario_id": self.scenario_id,
            "short_label": self.short_label,
            "title": self.title,
            "description": self.description,
            "expected_effect": self.expected_effect,
        }


SHANGHAI = ZoneInfo("Asia/Shanghai")
SYNTHETIC_PDF_MARKER = b"Accident Rights Agent Synthetic Fixture v2"
DEMO_DELIVERY_DATE = "2026-08-06"
DEMO_EXPERIENCE_END = "2026-08-10T23:59:59+08:00"


SCENARIOS: dict[str, ExperienceScenario] = {
    "demo_a": ExperienceScenario(
        scenario_id="demo_a",
        short_label="A",
        title="材料较完整",
        description="路口碰撞，登记、鉴定、信号相位和车辆参数较完整。",
        expected_effect="可形成受限定的车辆属性判断和责任置信分布。",
        roles=(
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
        ),
        fact_rows=(
            ("事故发生时间为2026-07-20 08:30", "事故", "事故时间", "2026-07-20"),
            (
                "事故认定书送达日期为2026-08-06",
                "事故认定书",
                "送达日期",
                DEMO_DELIVERY_DATE,
            ),
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
            (
                "两轮车辆在进入路口前未让优先通行车辆",
                "两轮车辆",
                "让行义务",
                "未让行",
            ),
            (
                "机动车驾驶人在碰撞前疏于观察",
                "机动车驾驶人",
                "观察注意",
                "疏于观察",
            ),
            (
                "机动车采取制动且现场记录有刹车痕迹",
                "机动车驾驶人",
                "制动避让",
                "已制动",
            ),
            (
                "现场勘查图标注碰撞点位于路口机动车道内",
                "事故",
                "碰撞点",
                "机动车道内",
            ),
            (
                "两轮车辆登记类型为电动自行车",
                "两轮车辆",
                "登记类型",
                "电动自行车",
            ),
            (
                "车辆属性鉴定意见为非机动车",
                "两轮车辆",
                "车辆属性鉴定",
                "非机动车",
            ),
            (
                "两轮车辆最高设计车速为25 km/h",
                "两轮车辆",
                "最高设计车速",
                "25 km/h",
            ),
            (
                "两轮车辆整车质量为52 kg，使用锂离子电池",
                "两轮车辆",
                "整车质量",
                "52 kg",
            ),
            (
                "两轮车辆电机额定连续输出功率为400 W",
                "两轮车辆",
                "额定连续输出功率",
                "400 W",
            ),
            (
                "车辆合格证和CCC记录与实车车型一致",
                "两轮车辆",
                "产品合格证/CCC",
                "已核验",
            ),
            (
                "保险单记载已投保交强险及商业险",
                "机动车",
                "保险单",
                "交强险及商业险",
            ),
        ),
    ),
    "demo_b": ExperienceScenario(
        scenario_id="demo_b",
        short_label="B",
        title="车辆属性证据不足",
        description="只有认定书、现场照片和一项明显超标的速度参数。",
        expected_effect="技术超标不会直接定性为机动车，唯一责任结论被阻断。",
        roles=(
            SourceRole.ACCIDENT_DETERMINATION,
            SourceRole.SCENE_PHOTO,
        ),
        fact_rows=(
            ("事故发生时间为2026-07-20", "事故", "事故时间", "2026-07-20"),
            ("机动车与两轮车辆在路口发生碰撞", "事故", "碰撞位置", "路口"),
            (
                "两轮车辆最高设计车速为45 km/h",
                "两轮车辆",
                "最高设计车速",
                "45 km/h",
            ),
        ),
    ),
    "demo_c": ExperienceScenario(
        scenario_id="demo_c",
        short_label="C",
        title="材料相互冲突",
        description="登记类型和驶入方向在认定书、视频与照片之间互相矛盾。",
        expected_effect="车辆属性降置信度并进入 disputed，只保留多责任假设。",
        roles=(
            SourceRole.ACCIDENT_DETERMINATION,
            SourceRole.DASHCAM_VIDEO,
            SourceRole.SCENE_PHOTO,
            SourceRole.VEHICLE_REGISTRATION,
        ),
        fact_rows=(
            ("事故发生时间为2026-07-20", "事故", "事故时间", "2026-07-20"),
            (
                "认定书记载两轮车辆登记为电动自行车",
                "两轮车辆",
                "登记类型",
                "电动自行车",
            ),
            (
                "照片中的登记查询记录显示为普通摩托车",
                "两轮车辆",
                "登记类型",
                "普通摩托车",
            ),
            (
                "视频显示两轮车辆由支路驶入",
                "两轮车辆",
                "驶入方向",
                "由支路驶入",
            ),
            (
                "认定书记载两轮车辆由主路驶入",
                "两轮车辆",
                "驶入方向",
                "由主路驶入",
            ),
        ),
        conflicts=((2, 3), (4, 5)),
    ),
}


def list_experience_scenarios() -> list[dict[str, str]]:
    return [scenario.public_summary() for scenario in SCENARIOS.values()]


def seed_experience_case(
    workspace: CaseWorkspace,
    scenario_id: str,
    *,
    case_id: str | None = None,
) -> tuple[str, ExperienceScenario]:
    try:
        scenario = SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown experience scenario: {scenario_id}") from exc

    suffix = uuid.uuid4().hex[:8].upper()
    selected_case_id = case_id or f"CASE-EXP-{scenario.short_label}-{suffix}"
    workspace.create_case(selected_case_id)
    store = workspace.store(selected_case_id)
    now = datetime.now(SHANGHAI)
    store.audit(
        selected_case_id,
        "case_metadata_saved",
        {
            "case_id": selected_case_id,
            "accident_time": "2026-07-20T08:30:00+08:00",
            "location": f"合成体验 · {scenario.title}",
            "jurisdiction": "CN",
            "party_role": "insured_driver",
            "manual_delivery_date": (
                DEMO_DELIVERY_DATE if scenario_id == "demo_a" else None
            ),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        },
        "experience_fixture",
    )
    node_ids: list[str] = []
    generated_dir = (
        workspace.case_dir(selected_case_id) / "derived" / "experience_fixture"
    )

    for index, role in enumerate(scenario.roles, start=1):
        node_id = f"NODE-{selected_case_id}-{index:02d}"
        if role is SourceRole.SCENE_PHOTO:
            source = workspace.ingest_file(
                selected_case_id,
                scene_asset_path(scenario_id),
                role=role,
                original_name=f"{index:02d}-{role.value}-synthetic.jpg",
            )
            store.add_node(
                _image_node(
                    selected_case_id,
                    source.source_id,
                    node_id,
                    source.stored_path,
                )
            )
        elif role is SourceRole.ROAD_SIGNAL_EVIDENCE:
            signal_path = materialize_signal_fixture(
                generated_dir,
                scenario_id,
            )
            source = workspace.ingest_file(
                selected_case_id,
                signal_path,
                role=role,
                original_name=f"{index:02d}-{role.value}-synthetic.jpg",
            )
            store.add_node(
                _image_node(
                    selected_case_id,
                    source.source_id,
                    node_id,
                    source.stored_path,
                )
            )
        elif role is SourceRole.DASHCAM_VIDEO:
            video_path, frame_paths = materialize_video_fixture(
                generated_dir,
                scenario_id,
            )
            source = workspace.ingest_file(
                selected_case_id,
                video_path,
                role=role,
                original_name=f"{index:02d}-{role.value}-synthetic.mp4",
            )
            for frame_index, frame_path in enumerate(frame_paths, start=1):
                frame_node_id = (
                    node_id
                    if frame_index == 1
                    else f"{node_id}-FRAME-{frame_index:02d}"
                )
                store.add_node(
                    _video_frame_node(
                        workspace,
                        selected_case_id,
                        source.source_id,
                        frame_node_id,
                        frame_path,
                        frame_index,
                    )
                )
        else:
            fixture_bytes = synthetic_pdf_bytes(scenario_id, role, index)
            with tempfile.NamedTemporaryFile(suffix=".pdf") as fixture:
                fixture.write(fixture_bytes)
                fixture.flush()
                source = workspace.ingest_file(
                    selected_case_id,
                    fixture.name,
                    role=role,
                    original_name=f"{index:02d}-{role.value}-synthetic.pdf",
                )
            store.add_node(
                EvidenceNode(
                    node_id=node_id,
                    case_id=selected_case_id,
                    source_id=source.source_id,
                    node_type="document_text",
                    locator={"page": 1, "synthetic": True},
                    content=f"{role.value} 合成体验材料",
                    extraction_method="synthetic_experience_fixture",
                    metadata={
                        "synthetic": True,
                        "contains_personal_data": False,
                    },
                )
            )
        node_ids.append(node_id)

    for index, (statement, subject, predicate, value) in enumerate(
        scenario.fact_rows, start=1
    ):
        store.add_fact(
            Fact(
                fact_id=f"FACT-{selected_case_id}-{index:03d}",
                case_id=selected_case_id,
                statement=statement,
                subject=subject,
                predicate=predicate,
                value=value,
                source_node_ids=(node_ids[(index - 1) % len(node_ids)],),
                confidence=0.94,
                status=FactStatus.VERIFIED,
                extraction_method="synthetic_experience_fixture",
                uncertainty="合成案件，仅用于三个业务 Agent 的本地体验。",
            )
        )

    if scenario.conflicts:
        store.replace_conflicts(
            selected_case_id,
            [
                EvidenceConflict(
                    conflict_id=f"CONFLICT-{selected_case_id}-{index:02d}",
                    case_id=selected_case_id,
                    subject="两轮车辆",
                    predicate=("登记类型" if index == 1 else "驶入方向"),
                    fact_ids=tuple(
                        f"FACT-{selected_case_id}-{fact_index:03d}"
                        for fact_index in fact_indexes
                    ),
                    description=(
                        "不同案件材料对同一关键事实的记载冲突，"
                        "必须降置信度并等待人工核验。"
                    ),
                    severity="blocking",
                )
                for index, fact_indexes in enumerate(scenario.conflicts, start=1)
            ],
        )

    store.audit(
        selected_case_id,
        "synthetic_business_experience_ready",
        {
            "scenario_id": scenario_id,
            "fact_count": len(scenario.fact_rows),
            "source_count": len(scenario.roles),
            "synthetic": True,
        },
        "experience_fixture",
    )
    return selected_case_id, scenario


def synthetic_pdf_bytes(
    scenario_id: str,
    role: SourceRole,
    index: int,
) -> bytes:
    """Build a deterministic, portable one-page PDF without runtime extras."""

    scenario = SCENARIOS[scenario_id]
    scenario_labels = {
        "demo_a": "Complete evidence path",
        "demo_b": "Insufficient evidence boundary",
        "demo_c": "Conflicting evidence boundary",
    }
    material_name = role.value.replace("_", " ").title()
    text_rows = [
        ("F2", 22, 50, 780, "SYNTHETIC DEMO MATERIAL", "1 1 1"),
        ("F1", 10, 50, 758, "LOCAL-ONLY FIXTURE - NOT AN OFFICIAL RECORD", "1 1 1"),
        (
            "F2",
            15,
            50,
            690,
            f"Scenario: {scenario_labels[scenario_id]}",
            "0.08 0.22 0.17",
        ),
        ("F2", 14, 50, 652, f"Material: {material_name}", "0.08 0.22 0.17"),
        (
            "F1",
            11,
            50,
            625,
            f"Fixture index: {index:02d}  |  Scenario ID: {scenario.scenario_id}",
            "0.25 0.31 0.28",
        ),
        ("F2", 12, 50, 555, "Purpose", "0.08 0.39 0.29"),
        (
            "F1",
            11,
            50,
            528,
            "Demonstrates material intake, evidence linking, and rights workflow.",
            "0.18 0.24 0.21",
        ),
        (
            "F1",
            11,
            50,
            505,
            "Structured demo facts are stored separately in the local case database.",
            "0.18 0.24 0.21",
        ),
        ("F2", 12, 50, 445, "Safety notice", "0.62 0.25 0.06"),
        (
            "F1",
            11,
            50,
            418,
            "This document contains no real person, vehicle, or accident information.",
            "0.18 0.24 0.21",
        ),
        (
            "F1",
            11,
            50,
            395,
            "It is not issued by traffic police, a court, an insurer, or an appraiser.",
            "0.18 0.24 0.21",
        ),
        (
            "F1",
            11,
            50,
            372,
            "Do not submit it to any external authority.",
            "0.18 0.24 0.21",
        ),
        (
            "F1",
            9,
            50,
            72,
            "Accident Rights Agent | Synthetic data | Generated deterministically",
            "0.36 0.42 0.39",
        ),
    ]
    commands = [
        "0.965 0.975 0.968 rg 0 0 595 842 re f",
        "0.055 0.39 0.29 rg 0 735 595 107 re f",
        "0.92 0.95 0.93 rg 38 580 519 105 re f",
        "0.995 0.955 0.91 rg 38 345 519 125 re f",
    ]
    for font, size, x, y, value, color in text_rows:
        commands.append(
            f"BT /{font} {size} Tf {color} rg 1 0 0 1 {x} {y} Tm "
            f"({_pdf_escape(value)}) Tj ET"
        )
    stream = ("\n".join(commands) + "\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> "
            b"/Contents 6 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"endstream",
    ]
    document = bytearray(b"%PDF-1.4\n% " + SYNTHETIC_PDF_MARKER + b"\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{object_number} 0 obj\n".encode("ascii"))
        document.extend(body)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(document)


def is_complete_synthetic_pdf(content: bytes) -> bool:
    return (
        len(content) >= 512
        and content.startswith(b"%PDF-")
        and SYNTHETIC_PDF_MARKER in content
        and b"\nxref\n" in content
        and b"\ntrailer\n" in content
        and b"\nstartxref\n" in content
        and content.rstrip().endswith(b"%%EOF")
    )


def repair_experience_case_pdfs(
    workspace: CaseWorkspace,
    case_id: str,
    scenario_id: str,
) -> int:
    """Migrate corrupt early synthetic PDFs without touching real evidence."""

    repaired = 0
    sources = workspace.store(case_id).list_sources(case_id)
    for fallback_index, source in enumerate(sources, start=1):
        if not source.original_name.endswith("-synthetic.pdf"):
            continue
        try:
            index = int(source.original_name.split("-", 1)[0])
        except ValueError:
            index = fallback_index
        desired = synthetic_pdf_bytes(scenario_id, source.role, index)
        path = (workspace.case_dir(case_id) / source.stored_path).resolve()
        existing = path.read_bytes()
        existing_digest = hashlib.sha256(existing).hexdigest()
        if (
            is_complete_synthetic_pdf(existing)
            and existing_digest == source.sha256
            and len(existing) == source.size_bytes
        ):
            continue
        workspace.repair_declared_synthetic_pdf(source, desired)
        repaired += 1
    return repaired


def repair_existing_experience_cases(
    workspace: CaseWorkspace,
    case_ids: list[str],
) -> dict[str, int]:
    repaired: dict[str, int] = {}
    for case_id in case_ids:
        try:
            events = workspace.store(case_id).list_audit_events(case_id)
        except KeyError:
            continue
        scenario_id = next(
            (
                str(event.get("payload", {}).get("scenario_id"))
                for event in reversed(events)
                if event.get("event_type") == "synthetic_business_experience_ready"
            ),
            "",
        )
        if scenario_id not in SCENARIOS:
            continue
        count = repair_experience_case_pdfs(workspace, case_id, scenario_id)
        count += upgrade_experience_case_media(
            workspace,
            case_id,
            scenario_id,
        )
        if count:
            repaired[case_id] = count
    return repaired


def upgrade_experience_case_media(
    workspace: CaseWorkspace,
    case_id: str,
    scenario_id: str,
) -> int:
    """Upgrade legacy text placeholders for photo/video roles in place."""

    store = workspace.store(case_id)
    generated_dir = workspace.case_dir(case_id) / "derived" / "experience_fixture"
    upgraded = 0
    for source in store.list_sources(case_id):
        is_legacy_pdf = source.original_name.endswith("-synthetic.pdf")
        is_legacy_avi = (
            source.role is SourceRole.DASHCAM_VIDEO
            and source.original_name.endswith("-synthetic.avi")
        )
        if not (is_legacy_pdf or is_legacy_avi):
            continue
        if source.role is SourceRole.SCENE_PHOTO:
            replacement = scene_asset_path(scenario_id)
            original_name = source.original_name.removesuffix(".pdf") + ".jpg"
            refreshed = workspace.replace_declared_synthetic_fixture(
                source,
                replacement,
                original_name=original_name,
            )
            nodes = store.list_nodes(case_id, source.source_id)
            node_id = str(nodes[0]["node_id"])
            store.add_node(
                _image_node(
                    case_id,
                    refreshed.source_id,
                    node_id,
                    refreshed.stored_path,
                )
            )
            upgraded += 1
        elif source.role is SourceRole.ROAD_SIGNAL_EVIDENCE:
            replacement = materialize_signal_fixture(
                generated_dir,
                scenario_id,
            )
            original_name = source.original_name.removesuffix(".pdf") + ".jpg"
            refreshed = workspace.replace_declared_synthetic_fixture(
                source,
                replacement,
                original_name=original_name,
            )
            nodes = store.list_nodes(case_id, source.source_id)
            node_id = str(nodes[0]["node_id"])
            store.add_node(
                _image_node(
                    case_id,
                    refreshed.source_id,
                    node_id,
                    refreshed.stored_path,
                )
            )
            upgraded += 1
        elif source.role is SourceRole.DASHCAM_VIDEO:
            video_path, frame_paths = materialize_video_fixture(
                generated_dir,
                scenario_id,
            )
            original_name = str(Path(source.original_name).with_suffix(".mp4"))
            refreshed = workspace.replace_declared_synthetic_fixture(
                source,
                video_path,
                original_name=original_name,
            )
            nodes = store.list_nodes(case_id, source.source_id)
            node_id = str(nodes[0]["node_id"])
            for frame_index, frame_path in enumerate(frame_paths, start=1):
                frame_node_id = (
                    node_id
                    if frame_index == 1
                    else f"{node_id}-FRAME-{frame_index:02d}"
                )
                store.add_node(
                    _video_frame_node(
                        workspace,
                        case_id,
                        refreshed.source_id,
                        frame_node_id,
                        frame_path,
                        frame_index,
                    )
                )
            upgraded += 1
    if upgraded:
        store.audit(
            case_id,
            "synthetic_multimodal_fixture_ready",
            {
                "scenario_id": scenario_id,
                "upgraded_source_count": upgraded,
                "synthetic": True,
            },
            "experience_fixture_upgrade",
        )
    return upgraded


def migrate_demo_delivery_date(
    workspace: CaseWorkspace,
    case_id: str,
) -> bool:
    """Move only the Golden synthetic delivery date to the judging window."""

    store = workspace.store(case_id)
    changed = False
    for fact in store.list_facts(case_id):
        if (
            fact.get("predicate") != "送达日期"
            or fact.get("value") == DEMO_DELIVERY_DATE
            or fact.get("extraction_method") != "synthetic_experience_fixture"
        ):
            continue
        store.add_fact(
            Fact(
                fact_id=str(fact["fact_id"]),
                case_id=case_id,
                statement=f"事故认定书送达日期为{DEMO_DELIVERY_DATE}",
                subject=str(fact.get("subject") or "事故认定书"),
                predicate="送达日期",
                value=DEMO_DELIVERY_DATE,
                source_node_ids=tuple(fact.get("source_node_ids") or ()),
                confidence=float(fact.get("confidence") or 0.94),
                status=FactStatus(str(fact.get("status") or "verified")),
                extraction_method="synthetic_experience_fixture",
                uncertainty=str(fact.get("uncertainty") or ""),
            )
        )
        changed = True
    if changed:
        store.audit(
            case_id,
            "synthetic_delivery_fact_updated",
            {
                "manual_delivery_date": DEMO_DELIVERY_DATE,
                "synthetic": True,
            },
            "golden_fixture_deadline_migration",
        )
    events = store.list_audit_events(case_id)
    latest_metadata: dict[str, Any] = next(
        (
            event["payload"]
            for event in reversed(events)
            if event.get("event_type") == "case_metadata_saved"
        ),
        {},
    )
    if latest_metadata.get("manual_delivery_date") == DEMO_DELIVERY_DATE:
        return changed
    now = datetime.now(SHANGHAI).isoformat()
    store.audit(
        case_id,
        "case_metadata_saved",
        {
            **latest_metadata,
            "case_id": case_id,
            "manual_delivery_date": DEMO_DELIVERY_DATE,
            "updated_at": now,
        },
        "golden_fixture_deadline_migration",
    )
    store.audit(
        case_id,
        "synthetic_deadline_fixture_updated",
        {
            "manual_delivery_date": DEMO_DELIVERY_DATE,
            "experience_available_until": DEMO_EXPERIENCE_END,
            "expected_statutory_due_at": "2026-08-11T23:59:59+08:00",
            "synthetic": True,
        },
        "golden_fixture_deadline_migration",
    )
    return True


def _image_node(
    case_id: str,
    source_id: str,
    node_id: str,
    preview_path: str,
) -> EvidenceNode:
    return EvidenceNode(
        node_id=node_id,
        case_id=case_id,
        source_id=source_id,
        node_type="image",
        locator={"image_index": 1, "synthetic": True},
        content="合成事故现场图像，仅用于多模态演示。",
        extraction_method="synthetic_multimodal_fixture",
        metadata={
            "synthetic": True,
            "contains_personal_data": False,
            "preview_path": preview_path,
        },
    )


def _video_frame_node(
    workspace: CaseWorkspace,
    case_id: str,
    source_id: str,
    node_id: str,
    frame_path: Path,
    frame_index: int,
) -> EvidenceNode:
    return EvidenceNode(
        node_id=node_id,
        case_id=case_id,
        source_id=source_id,
        node_type="video_keyframe",
        locator={
            "timestamp_seconds": float(frame_index - 1),
            "synthetic": True,
        },
        content=f"合成行车记录仪关键帧 {frame_index}，仅用于多模态演示。",
        extraction_method="synthetic_multimodal_fixture",
        metadata={
            "synthetic": True,
            "contains_personal_data": False,
            "preview_path": str(frame_path.relative_to(workspace.case_dir(case_id))),
        },
    )


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
