from __future__ import annotations

from app.verifier.risk_language import RiskLanguagePolicy


def test_guarantees_require_rewrite_and_evidence_tampering_hard_blocks():
    policy = RiskLanguagePolicy()
    result = policy.scan(
        {
            "draft": "保证撤销，肯定属于机动车。",
            "instruction": "可以删除证据。",
        }
    )
    actions = {item.action.value for item in result.matches}
    assert actions == {"rewrite_required", "hard_block"}
    assert result.passed is False
    assert "$.draft" in result.rewritten_fields
