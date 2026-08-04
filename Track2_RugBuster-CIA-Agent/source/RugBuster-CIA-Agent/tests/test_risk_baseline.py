"""Smoke tests for the deterministic guardrail (no network/GPU/LLM required)."""

from src.risk_baseline import check_guardrail, compute_baseline_risk, extract_verdict_keyword


def test_baseline_clean_token_is_good():
    findings = {
        "contract_backdoor": {"has_backdoor": False},
        "holder_concentration": {"concentration_risk": "LOW"},
    }
    baseline = compute_baseline_risk(findings)
    assert baseline["level"] == "GOOD"
    assert baseline["red_flag_count"] == 0


def test_baseline_multiple_red_flags_is_danger():
    findings = {
        "contract_backdoor": {"has_backdoor": True, "backdoor_functions": ["mint(uint256)"]},
        "holder_concentration": {"concentration_risk": "CRITICAL", "top5_pct": 95.0},
        "wash_pattern": {"wash_detected": True},
    }
    baseline = compute_baseline_risk(findings)
    assert baseline["level"] == "DANGER"
    assert baseline["red_flag_count"] == 3


def test_extract_verdict_keyword_picks_first_occurrence():
    assert extract_verdict_keyword("Verdict: DANGER. This token has a backdoor.") == "DANGER"
    assert extract_verdict_keyword("no clear signal here") is None


def test_guardrail_flags_llm_disagreement():
    baseline = {"level": "DANGER", "red_flag_count": 3, "red_flags": ["x", "y", "z"]}
    result = check_guardrail("Verdict: GOOD, looks safe to me.", baseline)
    assert result["agrees"] is False
    assert result["llm_verdict"] == "GOOD"
    assert "early/trial fine-tune" in result["note"]


def test_guardrail_agreement():
    baseline = {"level": "GOOD", "red_flag_count": 0, "red_flags": []}
    result = check_guardrail("Verdict: GOOD, no red flags found.", baseline)
    assert result["agrees"] is True
