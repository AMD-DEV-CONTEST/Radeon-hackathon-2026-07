import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from nuclear_agent.security import PermissionDenied, PermissionPolicy
from nuclear_agent.memory import LocalMemoryStore


def test_permission_policy_allows_analysis_and_denies_control_or_network():
    policy = PermissionPolicy(role="analyst", local_only=True)

    policy.require("simulate_transport")
    policy.require("retrieve_local_knowledge")
    with pytest.raises(PermissionDenied, match="operational_control"):
        policy.require("operational_control")
    with pytest.raises(PermissionDenied, match="external_network"):
        policy.require("external_network")


def test_permission_policy_redacts_sensitive_fields_recursively():
    policy = PermissionPolicy(role="analyst", local_only=True)
    sanitized = policy.redact_payload(
        {
            "scenario_id": "safe-id",
            "operator_name": "Sensitive Name",
            "nested": {"exact_coordinates": "45.0, 9.0", "value": 3},
        }
    )

    assert sanitized["scenario_id"] == "safe-id"
    assert sanitized["operator_name"] == "[REDACTED]"
    assert sanitized["nested"]["exact_coordinates"] == "[REDACTED]"
    assert sanitized["nested"]["value"] == 3


def test_local_memory_is_persistent_session_scoped_and_redacted(tmp_path):
    store = LocalMemoryStore(tmp_path / "memory.jsonl")
    store.add_turn(
        "session-a",
        role="user",
        content="Compare the two potassium cases",
        metadata={"operator_name": "Sensitive Name", "scenario_id": "demo"},
    )
    store.add_turn("session-b", role="user", content="Other session")

    restored = LocalMemoryStore(tmp_path / "memory.jsonl")
    turns = restored.recent("session-a", limit=5)

    assert len(turns) == 1
    assert turns[0]["content"] == "Compare the two potassium cases"
    assert turns[0]["metadata"]["operator_name"] == "[REDACTED]"
    assert restored.recent("session-b", limit=5)[0]["content"] == "Other session"


def test_redact_payload_scans_free_text_for_secret_shapes():
    """Review finding: key-based redaction misses tokens embedded in prose."""
    policy = PermissionPolicy(role="analyst", local_only=True)
    sanitized = policy.redact_payload(
        {
            "note": "The api_key=sk-1234567890abcdef was used, plus ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "content": "Bearer abcdefghijklmnopqrstuvwxyz0123456789ABCDEF token here",
            "safe": "plain text with hash 0f5f1e1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a",
        }
    )
    assert "[REDACTED]" in sanitized["note"]
    assert "sk-1234567890abcdef" not in sanitized["note"]
    assert "ghp_AAAAAAAA" not in sanitized["note"]
    assert "[REDACTED]" in sanitized["content"]
    assert "Bearer abcdefghijklmnop" not in sanitized["content"]
    # a bare 40-hex hash is NOT a secret in this project (provenance digests)
    assert "0f5f1e1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a" in sanitized["safe"]
