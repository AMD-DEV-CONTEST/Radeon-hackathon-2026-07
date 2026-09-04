from app.ui.view_models import liability_summary_html, liability_view


def test_vehicle_liability_and_compensation_are_consistent(golden_ui_runtime):
    view = liability_view(golden_ui_runtime.state)
    assert view["vehicle_nature"]["classification"] in {
        "non_motor_vehicle",
        "suspected_motor_vehicle",
        "motor_vehicle",
        "insufficient_evidence",
    }
    assert view["responsibility_probabilities"]
    assert (
        abs(sum(view["responsibility_probabilities"].values()) - 1.0)
        < 0.001
    )
    assert view["compensation_regime"] != ""
    assert view["insurance_payment_estimate"]["status"] == "insufficient_data"
    assert view["policy_gate"]["decision"] in {
        "pass",
        "pass_with_warnings",
        "block",
    }


def test_liability_summary_is_recording_friendly_and_compact(golden_ui_runtime):
    rendered = liability_summary_html(golden_ui_runtime.state)

    assert "车辆属性与技术参数" in rendered
    assert "设计最高车速" in rendered
    assert "冲突 / 缺失材料" in rendered
    assert "责任假设与概率" in rendered
    assert "88.6%" in rendered
    assert "三对象拆分" in rendered
    assert "材料不足，不生成金额" in rendered
    assert len(rendered) < 20_000
