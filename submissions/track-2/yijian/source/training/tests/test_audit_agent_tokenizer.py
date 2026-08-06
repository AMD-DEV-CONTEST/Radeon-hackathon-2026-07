from __future__ import annotations

import sys
from pathlib import Path


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import audit_agent_tokenizer  # noqa: E402
from test_train_lora_rocm import FakeTokenizer, row  # noqa: E402


def test_audit_rows_preserves_all_assistant_tokens() -> None:
    result = audit_agent_tokenizer.audit_rows(FakeTokenizer(), [row(), row()], 128)
    assert result["examples"] == 2
    assert result["assistantLossTokens"] > 0
    assert result["silentTruncation"] is False
