from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.rights.deadline import DeadlineCalculator
from app.rights.delivery_date import DeliveryDateExtractor
from app.rights.task_planner import RightsTaskPlanner


def test_due_soon_review_creates_critical_lawful_task():
    deadline = DeadlineCalculator().calculate(
        delivery=DeliveryDateExtractor().extract(
            facts=[], manual_date="2026-07-28"
        ),
        matter_type="accident_determination_review",
        rule_id="RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017",
        now=datetime(2026, 7, 31, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    tasks = RightsTaskPlanner().plan(
        missing_evidence=[
            {
                "category": "road_signal_evidence",
                "reason": "缺少路口监控和信号相位",
                "priority": "P0",
            }
        ],
        vehicle_result=None,
        liability_result=None,
        deadlines=[deadline],
        conflicts=[],
    )
    review = next(item for item in tasks if item.task_type == "prepare_accident_review")
    assert review.priority.value == "critical"
    assert review.status.value == "draft"
    assert review.human_approval_required is True
    assert any(item.task_type == "collect_scene_and_cctv" for item in tasks)
    assert not any("隐瞒" in " ".join(item.recommended_actions) for item in tasks)


def test_expired_deadline_uses_non_guaranteed_remedy_placeholder():
    deadline = DeadlineCalculator().calculate(
        delivery=DeliveryDateExtractor().extract(
            facts=[], manual_date="2026-07-28"
        ),
        matter_type="accident_determination_review",
        rule_id="RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017",
        now=datetime(2026, 8, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    task = next(
        item
        for item in RightsTaskPlanner().plan(
            missing_evidence=[],
            vehicle_result=None,
            liability_result=None,
            deadlines=[deadline],
            conflicts=[],
        )
        if item.task_type == "prepare_accident_review"
    )
    assert any("不保证" in action for action in task.recommended_actions)
