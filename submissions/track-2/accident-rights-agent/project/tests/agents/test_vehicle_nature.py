from __future__ import annotations

import pytest

from app.agents.vehicle_nature import VehicleNatureAgent
from app.schemas.business import VehicleNatureClassification
from app.schemas.legal import LegalCitation


def _citations(retriever):
    return [
        LegalCitation.from_chunk(chunk, 1.0) for chunk in retriever.corpus.list_chunks()
    ]


def _fact(index: int, predicate: str, value: str, statement: str | None = None):
    return {
        "fact_id": f"FACT-VEHICLE-{index:03d}",
        "statement": statement or f"两轮车辆{predicate}为{value}",
        "subject": "两轮车辆",
        "predicate": predicate,
        "value": value,
        "source_node_ids": [f"NODE-VEHICLE-{index:03d}"],
        "confidence": 0.95,
        "status": "verified",
    }


@pytest.mark.parametrize(
    ("facts", "conflicts", "expected"),
    [
        (
            [
                _fact(1, "登记类型", "电动自行车"),
                _fact(2, "最高设计车速", "25 km/h"),
                _fact(3, "额定连续输出功率", "400 W"),
            ],
            [],
            VehicleNatureClassification.NON_MOTOR_VEHICLE,
        ),
        (
            [_fact(1, "最高设计车速", "45 km/h")],
            [],
            VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE,
        ),
        (
            [
                _fact(1, "登记类型", "电动自行车"),
                _fact(2, "是否改装", "存在改装并解除限速"),
            ],
            [],
            VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE,
        ),
        (
            [_fact(1, "车辆属性鉴定", "机动车", "鉴定意见将车辆认定为机动车")],
            [],
            VehicleNatureClassification.MOTOR_VEHICLE,
        ),
        (
            [
                _fact(1, "登记类型", "电动自行车"),
                _fact(2, "登记类型", "普通摩托车"),
            ],
            [
                {
                    "fact_ids": [
                        "FACT-VEHICLE-001",
                        "FACT-VEHICLE-002",
                    ]
                }
            ],
            VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE,
        ),
        (
            [],
            [],
            VehicleNatureClassification.INSUFFICIENT_EVIDENCE,
        ),
    ],
)
def test_vehicle_nature_six_boundary_cases(legal_retriever, facts, conflicts, expected):
    result = VehicleNatureAgent().run(
        facts=facts,
        legal_citations=_citations(legal_retriever),
        conflicts=conflicts,
    )
    assert result.classification is expected
    assert len(result.alternative_hypotheses) >= 2
    assert all(item.source_law_id for item in result.parameter_comparison)
    assert "不直接替代车辆法律属性判断" in result.warning
    if any("45 km/h" in item.get("value", "") for item in facts):
        assert result.classification is not VehicleNatureClassification.MOTOR_VEHICLE


def test_vehicle_nature_conflict_lowers_confidence(legal_retriever):
    facts = [
        _fact(1, "登记类型", "电动自行车"),
        _fact(2, "登记类型", "普通摩托车"),
    ]
    result = VehicleNatureAgent().run(
        facts=facts,
        legal_citations=_citations(legal_retriever),
        conflicts=[
            {
                "fact_ids": [
                    "FACT-VEHICLE-001",
                    "FACT-VEHICLE-002",
                ]
            }
        ],
    )
    assert result.conclusion_status == "disputed"
    assert result.confidence <= 0.52
