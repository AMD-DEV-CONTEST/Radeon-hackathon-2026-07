from __future__ import annotations

from app.agents.liability import LiabilityAgent
from app.agents.vehicle_nature import VehicleNatureAgent
from app.schemas.business import (
    CompensationRegime,
    ViolationStatus,
)
from app.schemas.legal import LegalCitation


def _citations(retriever):
    return [
        LegalCitation.from_chunk(chunk, 1.0) for chunk in retriever.corpus.list_chunks()
    ]


def _fact(index: int, subject: str, predicate: str, value: str, statement: str):
    return {
        "fact_id": f"FACT-LIABILITY-{index:03d}",
        "statement": statement,
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "source_node_ids": [f"NODE-LIABILITY-{index:03d}"],
        "confidence": 0.94,
        "status": "verified",
    }


def _complete_facts():
    return [
        _fact(1, "两轮车辆", "登记类型", "电动自行车", "两轮车辆登记为电动自行车"),
        _fact(2, "两轮车辆", "车辆属性鉴定", "非机动车", "鉴定意见支持非机动车属性"),
        _fact(3, "两轮车辆", "行驶方向", "逆行", "两轮车辆沿机动车道逆行进入路口"),
        _fact(4, "两轮车辆", "信号灯状态", "违反停止信号", "两轮车辆违反停止信号"),
        _fact(5, "两轮车辆", "让行义务", "未让行", "两轮车辆未让优先通行车辆"),
        _fact(
            6, "机动车驾驶人", "观察注意", "疏于观察", "机动车驾驶人在碰撞前疏于观察"
        ),
        _fact(7, "机动车驾驶人", "制动避让", "已制动", "机动车采取制动并留下刹车痕迹"),
        _fact(8, "事故", "碰撞点", "机动车道内", "碰撞点位于机动车道内"),
    ]


def test_liability_outputs_matrices_hypotheses_and_three_separate_objects(
    legal_retriever,
):
    facts = _complete_facts()
    citations = _citations(legal_retriever)
    vehicle = VehicleNatureAgent().run(
        facts=facts,
        legal_citations=citations,
        conflicts=[],
    )
    result = LiabilityAgent().run(
        facts=facts,
        legal_citations=citations,
        vehicle_nature=vehicle,
        conflicts=[],
    )

    assert len(result.violation_matrix) == 24
    wrong_way = next(
        item
        for item in result.violation_matrix
        if item.category == "wrong_way" and item.party.value == "two_wheeler"
    )
    assert wrong_way.status is ViolationStatus.POSSIBLE
    assert wrong_way.fact_ids and wrong_way.evidence_ids
    assert not wrong_way.law_citations
    right_of_way = next(
        item
        for item in result.violation_matrix
        if item.category == "right_of_way" and item.party.value == "two_wheeler"
    )
    assert right_of_way.status is ViolationStatus.CONFIRMED
    assert right_of_way.law_citations
    braking = next(
        item
        for item in result.violation_matrix
        if item.category == "braking_avoidance"
        and item.party.value == "motor_vehicle"
    )
    assert braking.status is ViolationStatus.REFUTED
    assert result.causation_matrix
    assert len(result.liability_hypotheses) == 3
    assert abs(sum(result.responsibility_probabilities.values()) - 1.0) < 1e-6
    assert (
        result.compensation_regime
        is CompensationRegime.MOTOR_VS_NON_MOTOR_OR_PEDESTRIAN
    )
    assert result.accident_responsibility.model_dump() != (
        result.civil_compensation_allocation.model_dump()
    )
    assert result.insurance_payment_estimate.status == "insufficient_data"
    assert result.insurance_payment_estimate.estimated_amount is None
    assert result.uncertainty.unique_conclusion_blocked is False


def test_vehicle_design_speed_is_not_treated_as_accident_speed_violation(
    legal_retriever,
):
    facts = _complete_facts() + [
        _fact(
            9,
            "两轮车辆",
            "最高设计车速",
            "25 km/h",
            "两轮车辆最高设计车速为25 km/h",
        )
    ]
    citations = _citations(legal_retriever)
    vehicle = VehicleNatureAgent().run(
        facts=facts,
        legal_citations=citations,
        conflicts=[],
    )
    result = LiabilityAgent().run(
        facts=facts,
        legal_citations=citations,
        vehicle_nature=vehicle,
        conflicts=[],
    )
    speed = next(
        item
        for item in result.violation_matrix
        if item.category == "speed" and item.party.value == "two_wheeler"
    )
    assert speed.status is ViolationStatus.UNKNOWN
    assert not speed.fact_ids
    assert not speed.law_citations


def test_missing_key_evidence_blocks_unique_responsibility(legal_retriever):
    facts = [
        _fact(1, "两轮车辆", "最高设计车速", "45 km/h", "两轮车辆最高设计车速45 km/h")
    ]
    citations = _citations(legal_retriever)
    vehicle = VehicleNatureAgent().run(
        facts=facts,
        legal_citations=citations,
        conflicts=[],
    )
    result = LiabilityAgent().run(
        facts=facts,
        legal_citations=citations,
        vehicle_nature=vehicle,
        conflicts=[],
    )
    assert result.uncertainty.unique_conclusion_blocked is True
    assert result.accident_responsibility.status == "multiple_hypotheses_only"
    assert result.accident_responsibility.selected_hypothesis_id is None
    assert len(result.liability_hypotheses) >= 2
