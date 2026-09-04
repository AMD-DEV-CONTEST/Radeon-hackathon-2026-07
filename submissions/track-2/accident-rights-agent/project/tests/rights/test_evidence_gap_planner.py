from __future__ import annotations

from app.rights.evidence_gap import EvidenceGapPlanner


def test_gap_plan_has_lawful_methods_alternatives_and_counterfactuals():
    items = EvidenceGapPlanner().plan(
        gaps=[
            {
                "category": "vehicle_registration_plate",
                "reason": "缺少车辆登记、号牌和合格证",
                "required_for": ["车辆法律属性", "赔偿路径"],
                "priority": "P0",
            }
        ],
        deadlines=[],
    )
    item = items[0]
    assert item.lawful_collection_methods
    assert item.alternative_evidence
    assert len(item.counterfactual_impacts) == 2
    assert "不把技术参数超标自动等同为机动车" in item.fallback_if_unavailable


def test_gap_plan_deduplicates_the_same_business_gap():
    duplicate = {
        "category": "road_signal_evidence",
        "reason": "信号灯状态、相位或标志标线未知。",
        "required_for": ["信号控制义务", "路权"],
        "priority": "P0",
    }
    items = EvidenceGapPlanner().plan(
        gaps=[duplicate, dict(duplicate)],
        deadlines=[],
    )
    assert len(items) == 1
    assert len({item.gap_id for item in items}) == 1
