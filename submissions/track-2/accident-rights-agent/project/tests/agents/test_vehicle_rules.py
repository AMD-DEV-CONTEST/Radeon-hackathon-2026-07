from __future__ import annotations

from app.schemas.business import TechnicalComparisonStatus
from app.tools.vehicle_rules import VehicleParameterRuleEngine


def _fact(index: int, predicate: str, value: str, statement: str | None = None):
    return {
        "fact_id": f"FACT-RULE-{index:03d}",
        "statement": statement or f"{predicate}为{value}",
        "subject": "两轮车辆",
        "predicate": predicate,
        "value": value,
        "source_node_ids": [f"NODE-RULE-{index:03d}"],
        "confidence": 0.95,
        "status": "verified",
    }


def test_parameter_tool_compares_all_required_fields_deterministically():
    facts = [
        _fact(1, "最高设计车速", "25 km/h"),
        _fact(2, "整车质量", "52 kg", "整车质量为52 kg，使用锂离子电池"),
        _fact(3, "额定连续输出功率", "400 W"),
        _fact(4, "蓄电池标称电压", "48 V"),
        _fact(5, "脚踏功能", "有脚踏", "电助力车型具备脚踏骑行能力"),
        _fact(6, "防篡改", "防篡改合格"),
        _fact(7, "车体宽度", "40 cm"),
        _fact(8, "产品合格证/CCC", "已核验"),
        _fact(9, "登记类型", "电动自行车"),
        _fact(10, "是否改装", "未改装"),
    ]
    comparisons = VehicleParameterRuleEngine().compare(facts)
    by_name = {item.parameter: item for item in comparisons}

    assert len(comparisons) == 10
    assert by_name["design_max_speed"].status is TechnicalComparisonStatus.COMPLIANT
    assert (
        by_name["complete_vehicle_mass"].status is TechnicalComparisonStatus.COMPLIANT
    )
    assert by_name["rated_motor_power"].status is TechnicalComparisonStatus.COMPLIANT
    assert by_name["vehicle_dimensions"].observed_value == 0.4
    assert (
        by_name["nominal_battery_voltage"].status is TechnicalComparisonStatus.UNKNOWN
    )
    assert all(item.source_law_id == "CN-GB-17761-2024" for item in comparisons)
    assert all(item.jurisdiction == "中华人民共和国" for item in comparisons)
    assert all(item.effective_date == "2025-09-01" for item in comparisons)


def test_parameter_tool_reports_non_compliance_without_legal_classification():
    comparisons = VehicleParameterRuleEngine().compare(
        [
            _fact(1, "最高设计车速", "45 km/h"),
            _fact(2, "额定连续输出功率", "1200 W"),
            _fact(3, "解除限速", "已剪线提速"),
        ]
    )
    non_compliant = {
        item.parameter
        for item in comparisons
        if item.status is TechnicalComparisonStatus.NON_COMPLIANT
    }
    assert {
        "design_max_speed",
        "rated_motor_power",
        "anti_tamper_speed_limiter",
        "vehicle_modification",
    } <= non_compliant
    assert all("法律属性" not in item.status.value for item in comparisons)


def test_parameter_tool_marks_disputed_fact_conflicting():
    comparison = VehicleParameterRuleEngine().compare(
        [_fact(1, "最高设计车速", "35 km/h")],
        disputed_fact_ids={"FACT-RULE-001"},
    )[0]
    assert comparison.status is TechnicalComparisonStatus.CONFLICTING
