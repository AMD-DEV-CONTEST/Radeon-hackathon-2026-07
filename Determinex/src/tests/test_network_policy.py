import os
import sys
import types
from unittest import mock

import pytest

from scripts.determinex_providers import NetworkPolicyViolation, _litellm_generator


def _install_fake_litellm(monkeypatch, content="test response"):
    fake = types.SimpleNamespace()
    fake.completion = mock.Mock(
        return_value=types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
        )
    )
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


def test_network_policy_online():
    # When online, external models should proceed (and hit litellm which we can mock or just check if it bypasses our check)
    with mock.patch.dict(os.environ, {"DETERMINEX_NETWORK_POLICY": "online"}):
        gen = _litellm_generator("openai/gpt-4o")
        with mock.patch("litellm.completion") as mock_litellm:
            mock_litellm.return_value.choices = [
                mock.Mock(message=mock.Mock(content="test response"))
            ]
            res = gen("hello", 0.7)
            assert res == "test response"
            mock_litellm.assert_called_once()


def test_network_policy_offline_blocks_cloud():
    # When offline, external models should raise NetworkPolicyViolation
    with mock.patch.dict(os.environ, {"DETERMINEX_NETWORK_POLICY": "offline"}):
        gen = _litellm_generator("openai/gpt-4o")
        with pytest.raises(NetworkPolicyViolation, match="Cannot use cloud model"):
            gen("hello", 0.7)


def test_network_policy_offline_allows_local():
    # When offline, local models should still be allowed
    with mock.patch.dict(os.environ, {"DETERMINEX_NETWORK_POLICY": "offline"}):
        gen = _litellm_generator("ollama/llama3")
        with mock.patch("litellm.completion") as mock_litellm:
            mock_litellm.return_value.choices = [
                mock.Mock(message=mock.Mock(content="local test response"))
            ]
            res = gen("hello", 0.7)
            assert res == "local test response"
            mock_litellm.assert_called_once()


def test_network_policy_invalid_value_fails_closed_for_cloud(monkeypatch):
    fake_litellm = _install_fake_litellm(monkeypatch)
    monkeypatch.setenv("DETERMINEX_NETWORK_POLICY", "banana")
    gen = _litellm_generator("openai/gpt-4o")

    with pytest.raises(NetworkPolicyViolation, match="Invalid DETERMINEX_NETWORK_POLICY"):
        gen("hello", 0.7)

    fake_litellm.completion.assert_not_called()


def test_network_policy_offline_does_not_allow_cloud_model_with_local_in_name(monkeypatch):
    fake_litellm = _install_fake_litellm(monkeypatch)
    monkeypatch.setenv("DETERMINEX_NETWORK_POLICY", "offline")
    gen = _litellm_generator("openai/local-proxy")

    with pytest.raises(NetworkPolicyViolation, match="Cannot use cloud model"):
        gen("hello", 0.7)

    fake_litellm.completion.assert_not_called()
