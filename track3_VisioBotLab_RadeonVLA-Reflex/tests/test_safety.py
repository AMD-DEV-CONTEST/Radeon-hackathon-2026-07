import numpy as np

from radeonvla.protocol import GRIPPER_OPEN, clamp_action
from radeonvla.safety import (
    CommandSession,
    FailureDetector,
    FailureReason,
    RecoveryPolicy,
    SafetyMonitor,
    check_placement_success,
)
from radeonvla.tasks import get_task


class _FakeFranka:
    def __init__(self, finger_width: float):
        self.finger_width = finger_width

    def get_qpos(self):
        return [0.0] * 7 + [self.finger_width, self.finger_width]


class _FakeEntity:
    def __init__(self, pos, aabb):
        self._pos = np.asarray(pos, dtype=float)
        self._aabb = np.asarray(aabb, dtype=float)

    def get_pos(self):
        return self._pos

    def get_AABB(self):
        return self._aabb


def test_clamp_action_bounds() -> None:
    raw = [10.0, -10.0, 0.0, -4.0, 0.0, 5.0, 0.0, 1.0, -1.0]
    out = clamp_action(raw)
    assert out[0] <= 2.80
    assert out[1] >= -1.70
    assert 0.0 <= out[7] <= 0.04
    assert 0.0 <= out[8] <= 0.04


def test_command_session_versions_on_change() -> None:
    session = CommandSession(instruction="a", task_id="banana_white_left")
    assert session.version == 0
    v1 = session.set_command(instruction="b", task_id="banana_right", step=10)
    assert v1 == 1
    assert session.is_current(1)
    assert not session.is_current(0)
    assert session.events[-1]["type"] == "command_change"


def test_safety_monitor_invalidates_chunk_on_command_change() -> None:
    monitor = SafetyMonitor(max_joint_delta=0.5)
    action = [0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79, 0.0, 0.0]
    d0 = monitor.process(action, command_version=0)
    assert d0.accepted
    d1 = monitor.process(action, command_version=1)
    assert d1.invalidate_chunk
    assert d1.reason == "command_invalidated"
    assert d1.action[7] == GRIPPER_OPEN


def test_recovery_policy_limits_retries() -> None:
    policy = RecoveryPolicy(max_retries=1)
    assert policy.should_retry(0, FailureReason.EMPTY_GRASP)
    assert not policy.should_retry(1, FailureReason.EMPTY_GRASP)
    action = policy.recovery_action()
    assert len(action) == 9
    assert action[7] == GRIPPER_OPEN


def test_failure_detector_times_out_on_last_allowed_step() -> None:
    bundle = type("Bundle", (), {"objects": {}})()
    detector = FailureDetector(get_task("banana_white_left"), max_steps=3)
    open_gripper_action = [0.0] * 7 + [GRIPPER_OPEN, GRIPPER_OPEN]
    assert detector.observe_step(bundle, step=1, action=open_gripper_action) is None
    assert detector.observe_step(bundle, step=2, action=open_gripper_action) is FailureReason.TIMEOUT


def test_empty_grasp_uses_measured_finger_width_not_close_command() -> None:
    bundle = type("Bundle", (), {"objects": {}, "franka": _FakeFranka(GRIPPER_OPEN)})()
    detector = FailureDetector(get_task("banana_white_left"), max_steps=100)
    close_command = [0.0] * 9
    for step in range(20):
        assert detector.observe_step(bundle, step=step, action=close_command) is None


def test_strict_placement_rejects_fruit_outside_inner_bowl_footprint() -> None:
    task = get_task("banana_white_left")
    fruit = _FakeEntity([0.10, 0.0, 0.80], [[0.08, -0.02, 0.77], [0.12, 0.02, 0.83]])
    bowl = _FakeEntity([0.0, 0.0, 0.77], [[-0.08, -0.08, 0.74], [0.08, 0.08, 0.80]])
    bundle = type("Bundle", (), {"objects": {task.target_object: fruit, task.target_container: bowl}})()
    assert check_placement_success(bundle, task, strict=False)[0] is True
    assert check_placement_success(bundle, task, strict=True)[0] is False


def test_task_registry_language_disjoint() -> None:
    task = get_task("banana_white_left")
    assert set(task.training_instructions).isdisjoint(task.evaluation_instructions)
