from __future__ import annotations

import sys

import numpy as np
import pytest
import torch

from bridge import (
    ManeuverPhase,
    ManeuverWaypointGate,
    path_to_tsc_waypoints,
)
from unilab.algos.torch.cpp_loco import unilab_action_to_canonical_target
from unilab.algos.torch.quadrupedal_agility import (
    DEFAULT_AGILITY_BBC_CONTRACT,
    SOURCE_AGILITY_BBC_CONTRACT,
    SOURCE_TSC_COMMAND_HIGH,
    SOURCE_TSC_COMMAND_LOW,
    agility_action_to_unilab,
    build_agility_proprio,
    expand_source_tsc_command,
    resolve_student_actor_inputs,
)
from run_frame_sanity import SourceFrameTerrainCfg, frame_delta_yaw
from run_source_task import (
    POLICY_PROFILES,
    SOURCE_LOW_CHECKPOINT,
    _preprocess_source_depth,
    _run_id,
    parse_args,
)


def test_waypoint_adapter_and_commit_gate() -> None:
    pose = np.array([0.0, 0.0, 0.0])
    straight = path_to_tsc_waypoints(
        np.array([[0.2, 0.0, 0.0], [0.4, 0.0, 0.0], [0.8, 0.0, 0.0]]),
        pose,
    )
    assert straight.current_xy == (0.4, 0.0)
    assert straight.next_xy == (0.8, 0.0)
    assert straight.delta_yaw == 0.0

    detour = path_to_tsc_waypoints(np.array([[0.2, 0.2], [0.4, 0.6], [0.8, 0.8]]), pose)
    assert detour.yaw_clipped
    assert detour.delta_yaw == pytest.approx(0.6)

    gate = ManeuverWaypointGate()
    assert gate.apply(straight, ManeuverPhase.NORMAL) == straight
    assert gate.apply(detour, ManeuverPhase.COMMITTED) == straight
    assert gate.apply(detour, ManeuverPhase.RECOVERY) == straight
    assert gate.apply(detour, ManeuverPhase.RECOVERY, recovered=True) == detour

    with pytest.raises(ValueError):
        path_to_tsc_waypoints(np.zeros((2, 2)), pose, 0.7, 0.35)
    with pytest.raises(ValueError):
        path_to_tsc_waypoints(np.zeros((3, 11)), pose)


def test_agility_bbc_observation_and_target_contract() -> None:
    proprio = build_agility_proprio(
        np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        np.array([[0.4, -0.8, 1.2]], dtype=np.float32),
        np.array([[0.0, 0.9, -1.8] * 4], dtype=np.float32),
        np.zeros((1, 12), dtype=np.float32),
        np.arange(12, dtype=np.float32).reshape(1, 12) / 10.0,
        np.array([[1.0, 0.0, 1.0, 0.0]], dtype=np.float32),
    )
    assert proprio.shape == (1, 57)
    np.testing.assert_allclose(proprio[0, :5], [0.0, 0.0, 0.1, -0.2, 0.3])
    np.testing.assert_allclose(proprio[0, 29:41], np.arange(12) / 10.0)
    np.testing.assert_allclose(proprio[0, 41:45], [0.5, -0.5, 0.5, -0.5])

    source_action = np.arange(12, dtype=np.float32).reshape(1, 12) / 10.0
    target = unilab_action_to_canonical_target(agility_action_to_unilab(source_action))
    expected_scale = np.full(12, 0.25, dtype=np.float32)
    expected_scale[[0, 3, 6, 9]] *= (
        DEFAULT_AGILITY_BBC_CONTRACT.source_hip_scale_reduction
    )
    expected = (
        np.asarray(DEFAULT_AGILITY_BBC_CONTRACT.source_default_dof, dtype=np.float32)
        + source_action * expected_scale
    )
    np.testing.assert_allclose(target, expected, atol=1.0e-6)

    source_target = unilab_action_to_canonical_target(
        agility_action_to_unilab(source_action, SOURCE_AGILITY_BBC_CONTRACT)
    )
    source_scale = np.full(12, 0.25, dtype=np.float32)
    source_scale[[0, 3, 6, 9]] *= 0.5
    np.testing.assert_allclose(
        source_target,
        np.asarray(SOURCE_AGILITY_BBC_CONTRACT.source_default_dof)
        + source_action * source_scale,
        atol=1.0e-6,
    )
    command_low = np.asarray(SOURCE_TSC_COMMAND_LOW)
    command_high = np.asarray(SOURCE_TSC_COMMAND_HIGH)
    assert command_low.shape == command_high.shape == (3, 5)
    np.testing.assert_allclose(command_low[:, 0], [0.5, 0.8, 0.8])
    np.testing.assert_allclose(command_high[:, 0], [1.5, 2.5, 2.0])
    expanded = expand_source_tsc_command(
        torch.tensor([[0.8, 0, 0, 0, 0.3, 0, 1, 0, 0]])
    )
    assert tuple(expanded.shape) == (1, 11)
    torch.testing.assert_close(expanded[0, 6:], torch.tensor([0.0, 0.0, 1.0, 0.0, 0.0]))


def test_source_task_policy_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    deployment = POLICY_PROFILES["deployment3"]
    assert deployment.low_checkpoint.name == "model.pt"
    assert deployment.low_checkpoint.parent.name == "3_model"
    assert deployment.low_mode_count == 3
    assert deployment.command_dim == 9
    assert deployment.bbc_input_dim == 669
    assert deployment.low_contract.source_hip_scale_reduction == 0.3

    source = POLICY_PROFILES["source5"]
    assert source.low_checkpoint == SOURCE_LOW_CHECKPOINT
    assert source.low_mode_count == 5
    assert source.command_dim == 11
    assert source.bbc_input_dim == 671
    assert source.low_contract.source_hip_scale_reduction == 0.5

    monkeypatch.setattr(sys, "argv", ["run_source_task.py", "--task", "tire_jump"])
    assert parse_args().policy_profile == "deployment3"


def test_student_actor_input_overrides() -> None:
    predicted_yaw = torch.tensor([[0.25, -0.5]], dtype=torch.float16)
    probabilities = torch.tensor(
        [[0.1, 0.6, 0.1, 0.1, 0.05, 0.05]], dtype=torch.float16
    )

    yaw, one_hot = resolve_student_actor_inputs(
        predicted_yaw, probabilities, None, None
    )
    assert yaw is predicted_yaw
    assert one_hot.dtype == torch.float16
    torch.testing.assert_close(one_hot, torch.eye(6, dtype=torch.float16)[[1]])

    yaw, one_hot = resolve_student_actor_inputs(
        predicted_yaw,
        probabilities,
        np.array([[0.1, 0.2]], dtype=np.float32),
        4,
    )
    assert yaw.dtype == torch.float16
    torch.testing.assert_close(
        yaw, torch.tensor([[0.1, 0.2]], dtype=torch.float16)
    )
    torch.testing.assert_close(one_hot, torch.eye(6, dtype=torch.float16)[[4]])

    with pytest.raises(ValueError):
        resolve_student_actor_inputs(
            predicted_yaw, probabilities, np.zeros((1, 3), dtype=np.float32), None
        )
    with pytest.raises(ValueError):
        resolve_student_actor_inputs(predicted_yaw, probabilities, None, 6)


def test_student_injection_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_source_task.py",
            "--task",
            "frame",
            "--high-branch",
            "student",
            "--precision",
            "float16",
            "--yaw-source",
            "waypoint",
            "--onehot-source",
            "gt",
        ],
    )
    args = parse_args()
    assert _run_id(args) == "NAG-210F-S16-WY-GO"
    assert args.output_dir.name == "NAG-210F-S16-WY-GO"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_source_task.py",
            "--task",
            "tire_jump",
            "--high-branch",
            "student",
            "--precision",
            "float16",
            "--yaw-source",
            "waypoint",
        ],
    )
    assert _run_id(parse_args()) == "NAG-210R-S16-WY"

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_source_task.py", "--task", "frame", "--yaw-source", "waypoint"],
    )
    with pytest.raises(SystemExit):
        parse_args()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_source_task.py",
            "--task",
            "frame",
            "--high-branch",
            "student",
            "--precision",
            "float16",
            "--onehot-source",
            "gt",
            "--perception-only",
        ],
    )
    with pytest.raises(SystemExit):
        parse_args()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_source_task.py",
            "--task",
            "bar_jump",
            "--high-branch",
            "student",
            "--precision",
            "float16",
            "--yaw-source",
            "waypoint",
            "--diagnostic",
        ],
    )
    with pytest.raises(SystemExit):
        parse_args()


def test_source_depth_preprocessing_contract() -> None:
    raw = np.full((60, 106), 2.15, dtype=np.float32)
    raw[1, 10] = 0.0
    raw[-2, -10] = 10.0
    depth = _preprocess_source_depth(raw)
    assert depth.shape == (58, 87)
    assert depth.dtype == np.float32
    assert depth[0, 0] == pytest.approx(-0.5)
    assert depth[-1, -1] == pytest.approx(0.5)
    assert depth[1, 1] == pytest.approx(0.0, abs=1.0e-6)


def test_source_frame_heightfield_contract() -> None:
    terrain = SourceFrameTerrainCfg(size=(8.0, 8.0)).function(
        0.0, np.random.default_rng(7)
    )
    heights = terrain.heightfield.physical_heights_xy()
    assert heights.shape == (40, 40)
    assert np.max(heights) == pytest.approx(0.33)
    assert np.count_nonzero(heights[:, 20]) > 0
    assert np.count_nonzero(heights[:, 18]) == 0

    source_terrain = SourceFrameTerrainCfg(
        size=(8.0, 8.0), horizontal_scale=0.05
    ).function(0.0, np.random.default_rng(7))
    source_heights = source_terrain.heightfield.physical_heights_xy()
    assert source_heights.shape == (160, 160)
    assert np.max(source_heights) == pytest.approx(0.33)

    delta, goal_index, timer = frame_delta_yaw(
        np.asarray([[-2.1625, 0.0, 0.3]], dtype=np.float32),
        np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        0,
        0,
    )
    assert goal_index == 0
    assert timer == 1
    np.testing.assert_allclose(delta, 0.0, atol=1.0e-6)

    _, goal_index, timer = frame_delta_yaw(
        np.asarray([[-2.15, 0.0, 0.3]], dtype=np.float32),
        np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        goal_index,
        timer,
    )
    delta, goal_index, timer = frame_delta_yaw(
        np.asarray([[-2.15, 0.0, 0.3]], dtype=np.float32),
        np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        goal_index,
        timer,
    )
    assert goal_index == 1
    assert timer == 0

    delta, _, _ = frame_delta_yaw(
        np.asarray([[-2.0, 0.2, 0.3]], dtype=np.float32),
        np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        1,
        0,
    )
    assert np.all(delta < 0.0)
