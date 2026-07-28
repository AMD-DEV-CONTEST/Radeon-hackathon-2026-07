"""
Unit tests for Aetheris CLI skill manifests and auto-config plan generation logic.
Verifies endpoint engine mapping, chat URL precedence policy, and plan state inspection.
"""

from aetheris_cli.commands.skill_manifest import (
    LEMONADE_ENDPOINT,
    VLLM_ENDPOINT,
    auto_config_change,
    auto_config_plan,
)


def test_auto_config_change_lemonade():
    change = auto_config_change(LEMONADE_ENDPOINT)
    assert change is not None
    assert change.default_engine == "lemonade"


def test_auto_config_change_vllm():
    change = auto_config_change(VLLM_ENDPOINT)
    assert change is not None
    assert change.default_engine == "vllm"


def test_auto_config_plan_preserves_configured_chat():
    plan = auto_config_plan(LEMONADE_ENDPOINT, chat_url_configured=True)
    assert plan.set_chat_url is None
    assert plan.set_default_engine == "lemonade"
    assert plan.kept_existing_chat is True
    assert plan.is_noop is False


def test_auto_config_plan_fills_unset_chat():
    plan = auto_config_plan(VLLM_ENDPOINT, chat_url_configured=False)
    assert plan.set_chat_url == VLLM_ENDPOINT
    assert plan.set_default_engine == "vllm"
    assert plan.kept_existing_chat is False


def test_auto_config_plan_noop_when_none():
    plan = auto_config_plan(None, chat_url_configured=False)
    assert plan.is_noop is True
