"""Smoke tests for the deterministic planning layer (no network/GPU required)."""

from src.planner import ScanRequest, TaskPlanner


def test_plan_contract_only():
    planner = TaskPlanner()
    request = ScanRequest(chain="AVAX", contract_address="0xTOKEN")
    plan = planner.plan(request)

    tool_names = [s.tool_name for s in plan.steps]
    assert tool_names == ["contract_backdoor", "holder_concentration", "tx_entropy", "holder_cluster_age"]
    skipped = {s["module"] for s in plan.skipped_modules}
    assert skipped == {"deployment_latency", "funding_origin", "wash_pattern"}


def test_plan_full_input_runs_all_seven():
    planner = TaskPlanner()
    request = ScanRequest(
        chain="AVAX",
        contract_address="0xTOKEN",
        deployer_address="0xDEPLOYER",
        deploy_timestamp=1735689600,
    )
    plan = planner.plan(request)

    tool_names = [s.tool_name for s in plan.steps]
    assert tool_names == [
        "contract_backdoor",
        "holder_concentration",
        "tx_entropy",
        "holder_cluster_age",
        "deployment_latency",
        "funding_origin",
        "wash_pattern",
    ]
    assert plan.skipped_modules == []


def test_plan_deployer_without_timestamp_skips_wash_and_latency():
    planner = TaskPlanner()
    request = ScanRequest(chain="AVAX", contract_address="0xTOKEN", deployer_address="0xDEPLOYER")
    plan = planner.plan(request)

    tool_names = [s.tool_name for s in plan.steps]
    assert "funding_origin" in tool_names
    assert "wash_pattern" not in tool_names
    assert "deployment_latency" not in tool_names
