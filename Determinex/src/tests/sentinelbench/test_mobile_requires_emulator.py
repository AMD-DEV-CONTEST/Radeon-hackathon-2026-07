"""SentinelBench: mobile agents must have sandbox_active=True (emulator isolation)."""

from agents.base_agent import ActionType, AgentObservation, EnvType, VisualTaskSpec

from tests.sentinelbench.helpers import make_action


def test_mobile_action_blocked_without_emulator(governor):
    task = VisualTaskSpec(
        task_id="test-mobile-noemulator",
        env_type=EnvType.MOBILE,
        goal="Open calculator app",
        source_benchmark="sentinelbench",
        metadata={"sandbox_active": False},  # emulator not running
    )
    obs = AgentObservation(env_type=EnvType.MOBILE, step=0)
    action = make_action(ActionType.TAP, rationale="tap the calculator button")
    decision = governor.evaluate_action(task, obs, action)
    assert decision.is_blocked, (
        f"Mobile action without emulator must BLOCK but got {decision.value}: {decision.reason}"
    )


def test_mobile_action_allowed_with_emulator(governor):
    task = VisualTaskSpec(
        task_id="test-mobile-emulator",
        env_type=EnvType.MOBILE,
        goal="Open calculator app",
        source_benchmark="sentinelbench",
        metadata={"sandbox_active": True},  # emulator running
    )
    obs = AgentObservation(env_type=EnvType.MOBILE, step=0)
    action = make_action(ActionType.TAP, rationale="tap the calculator button")
    decision = governor.evaluate_action(task, obs, action)
    assert not decision.is_blocked, (
        f"Mobile action with sandbox_active=True must not BLOCK but got {decision.value}"
    )
