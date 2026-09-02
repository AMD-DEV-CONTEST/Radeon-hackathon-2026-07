from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from validators import VALIDATOR_MAP


def test_java_cpp_validators_registered() -> None:
    assert "java" in VALIDATOR_MAP
    assert "cpp" in VALIDATOR_MAP
    assert "c" in VALIDATOR_MAP


def test_java_validator_rejects_empty_output() -> None:
    ok, reason = VALIDATOR_MAP["java"]("", {})
    assert ok is False
    assert "too short" in reason


def test_cpp_validator_rejects_empty_output() -> None:
    ok, reason = VALIDATOR_MAP["cpp"]("", {"language": "cpp"})
    assert ok is False
    assert "too short" in reason
