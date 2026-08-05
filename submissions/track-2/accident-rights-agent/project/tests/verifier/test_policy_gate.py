from __future__ import annotations

from app.schemas.verification import (
    ComponentVerifierResult,
    RiskLanguageResult,
)
from app.verifier.policy_gate import FinalPolicyGate


def test_gate_passes_with_approval_warning_but_blocks_protected_field_loss():
    passed = ComponentVerifierResult(verifier="test", passed=True)
    risk = RiskLanguageResult(passed=True)
    pending = FinalPolicyGate().evaluate(
        evidence=passed,
        legal=passed,
        consistency=passed,
        risk_language=risk,
        protected_fields_valid=True,
        approval_state="pending",
    )
    blocked = FinalPolicyGate().evaluate(
        evidence=passed,
        legal=passed,
        consistency=passed,
        risk_language=risk,
        protected_fields_valid=False,
        approval_state="pending",
    )
    assert pending.decision.value == "pass_with_warnings"
    assert pending.approval_required is True
    assert blocked.decision.value == "block"
