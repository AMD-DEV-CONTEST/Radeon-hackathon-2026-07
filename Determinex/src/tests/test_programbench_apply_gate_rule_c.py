from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from pb_apply_gate_decision import _safe_decision_rule


def test_apply_gate_preserves_rule_c_decision_rule() -> None:
    gate = {
        "decision": "accept",
        "decision_rule": "C",
        "delta": {"runnable": -28},
    }

    assert _safe_decision_rule(gate) == "C"


def test_apply_gate_backward_compat_missing_rule_uses_shifted_surface_rule_b() -> None:
    gate = {
        "decision": "accept",
        "delta": {"runnable": -28},
    }

    assert _safe_decision_rule(gate) == "B"
