"""Deterministic Golden Demo Case with real local image/video containers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.demo.business_cases import (
    DEMO_DELIVERY_DATE,
    DEMO_EXPERIENCE_END,
    migrate_demo_delivery_date,
    repair_experience_case_pdfs,
    seed_experience_case,
    upgrade_experience_case_media,
)
from app.evidence.database import EvidenceStore
from app.evidence.workspace import CaseWorkspace
from app.schemas.evidence import Fact, FactStatus, SourceRole, TimelineEvent

GOLDEN_CASE_ID = "CASE-GOLDEN-DEMO"


def seed_golden_case(
    workspace: CaseWorkspace,
    *,
    case_id: str = GOLDEN_CASE_ID,
) -> str:
    try:
        store = workspace.store(case_id)
    except KeyError:
        seed_experience_case(workspace, "demo_a", case_id=case_id)
        store = workspace.store(case_id)

    repair_experience_case_pdfs(workspace, case_id, "demo_a")
    upgrade_experience_case_media(workspace, case_id, "demo_a")
    migrate_demo_delivery_date(workspace, case_id)
    _ensure_golden_metadata(store, case_id)

    sources = {
        source.source_id: source for source in store.list_sources(case_id)
    }
    nodes = store.list_nodes(case_id)
    video_nodes = sorted(
        (
            node
            for node in nodes
            if node["node_type"] == "video_keyframe"
            and node["extraction_method"] == "synthetic_multimodal_fixture"
            and sources[node["source_id"]].role is SourceRole.DASHCAM_VIDEO
        ),
        key=lambda node: float(node["locator"].get("timestamp_seconds", 0)),
    )
    image_nodes = [
        node
        for node in nodes
        if node["node_type"] == "image"
        and node["extraction_method"] == "synthetic_multimodal_fixture"
        and sources[node["source_id"]].role is SourceRole.SCENE_PHOTO
    ]
    if len(video_nodes) < 3 or not image_nodes:
        raise RuntimeError("Golden multimodal fixture is incomplete.")
    image_node = image_nodes[0]

    extra_facts = (
        (
            f"FACT-{case_id}-TIMELINE-001",
            "合成关键帧显示两轮车辆在碰撞前由画面右侧驶近路口",
            "两轮车辆",
            "碰撞前轨迹",
            "由右侧驶近",
            video_nodes[0]["node_id"],
        ),
        (
            f"FACT-{case_id}-TIMELINE-002",
            "合成关键帧显示双方车辆在路口区域接近接触位置",
            "事故",
            "碰撞阶段",
            "路口接近接触位置",
            video_nodes[1]["node_id"],
        ),
        (
            f"FACT-{case_id}-TIMELINE-003",
            "合成关键帧显示双方车辆在路口区域停止",
            "事故",
            "碰撞后状态",
            "车辆停止",
            video_nodes[2]["node_id"],
        ),
    )
    for fact_id, statement, subject, predicate, value, node_id in extra_facts:
        store.add_fact(
            Fact(
                fact_id=fact_id,
                case_id=case_id,
                statement=statement,
                subject=subject,
                predicate=predicate,
                value=value,
                source_node_ids=(node_id,),
                confidence=0.99,
                status=FactStatus.VERIFIED,
                extraction_method="synthetic_golden_fixture",
                uncertainty="合成 Golden Case，仅用于端到端演示与回归。",
            )
        )
    store.replace_timeline(
        case_id,
        [
            TimelineEvent(
                event_id=f"EVENT-{case_id}-BEFORE",
                case_id=case_id,
                label="碰撞前：两轮车辆驶近路口",
                relative_order=1,
                source_node_ids=(video_nodes[0]["node_id"],),
                timestamp_seconds=0.0,
                confidence=0.99,
            ),
            TimelineEvent(
                event_id=f"EVENT-{case_id}-IMPACT",
                case_id=case_id,
                label="碰撞时：双方在路口区域接近接触位置",
                relative_order=2,
                source_node_ids=(
                    video_nodes[1]["node_id"],
                    image_node["node_id"],
                ),
                timestamp_seconds=1.0,
                confidence=0.99,
            ),
            TimelineEvent(
                event_id=f"EVENT-{case_id}-AFTER",
                case_id=case_id,
                label="碰撞后：车辆停止",
                relative_order=3,
                source_node_ids=(video_nodes[2]["node_id"],),
                timestamp_seconds=2.0,
                confidence=0.99,
            ),
        ],
    )

    ready = any(
        event["event_type"] == "golden_demo_case_ready"
        for event in store.list_audit_events(case_id)
    )
    if not ready:
        store.audit(
            case_id,
            "golden_demo_case_ready",
            {
                "synthetic": True,
                "video_source_id": video_nodes[0]["source_id"],
                "image_source_id": image_node["source_id"],
                "keyframe_node_ids": [item["node_id"] for item in video_nodes[:3]],
                "fact_ids": [item[0] for item in extra_facts],
                "manual_delivery_date": DEMO_DELIVERY_DATE,
                "experience_available_until": DEMO_EXPERIENCE_END,
                "expected_statutory_due_at": "2026-08-11T23:59:59+08:00",
            },
            "golden_fixture",
        )
    return case_id


def _ensure_golden_metadata(store: EvidenceStore, case_id: str) -> None:
    events = store.list_audit_events(case_id)
    metadata: dict[str, Any] = next(
        (
            event["payload"]
            for event in reversed(events)
            if event.get("event_type") == "case_metadata_saved"
        ),
        {},
    )
    if (
        metadata.get("location") == "合成路口 · Golden Demo"
        and metadata.get("manual_delivery_date") == DEMO_DELIVERY_DATE
    ):
        return
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    store.audit(
        case_id,
        "case_metadata_saved",
        {
            **metadata,
            "case_id": case_id,
            "accident_time": "2026-07-20T08:30:00+08:00",
            "location": "合成路口 · Golden Demo",
            "jurisdiction": "CN",
            "party_role": "insured_driver",
            "manual_delivery_date": DEMO_DELIVERY_DATE,
            "created_at": metadata.get("created_at") or now,
            "updated_at": now,
        },
        "golden_fixture",
    )
