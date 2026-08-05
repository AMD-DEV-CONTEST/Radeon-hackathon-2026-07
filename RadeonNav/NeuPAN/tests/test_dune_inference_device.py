from pathlib import Path

import numpy as np
import pytest
import torch

from neupan import configuration, neupan
from neupan.blocks import DUNE
from neupan.robot import robot


NEUPAN_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = NEUPAN_ROOT / "example/model/go2_diff_070_040/model_2000.pth"


def _robot(receding: int = 2):
    return robot(
        receding=receding,
        step_time=0.1,
        kinematics="diff",
        max_speed=[2.0, 3.0],
        max_acce=[2.0, 3.0],
        length=0.70,
        width=0.40,
    )


def _dune_inputs(receding: int = 2, point_count: int = 8):
    generator = torch.Generator(device="cpu").manual_seed(11)
    point_flow = [
        torch.randn(2, point_count, generator=generator)
        for _ in range(receding + 1)
    ]
    rotations = [torch.eye(2) for _ in range(receding + 1)]
    obstacle_points = [
        torch.randn(2, point_count, generator=generator)
        for _ in range(receding + 1)
    ]
    return point_flow, rotations, obstacle_points


def _make_dune(inference_device=None):
    configuration.device = torch.device("cpu")
    return DUNE(
        receding=2,
        checkpoint=str(CHECKPOINT),
        robot=_robot(),
        dune_max_num=8,
        inference_device=inference_device,
        inference_dtype="float32",
    )


def _make_planner(dune_device: str):
    planner = neupan(
        receding=3,
        step_time=0.1,
        ref_speed=0.8,
        device="cpu",
        robot_kwargs={
            "kinematics": "diff",
            "max_speed": [2.0, 3.0],
            "max_acce": [2.0, 3.0],
            "length": 0.70,
            "width": 0.40,
        },
        ipath_kwargs={
            "waypoints": [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]],
            "curve_style": "line",
            "loop": False,
            "arrive_threshold": 0.2,
            "close_threshold": 0.1,
            "ind_range": 10,
            "arrive_index_threshold": 1,
        },
        pan_kwargs={
            "iter_num": 1,
            "dune_max_num": 16,
            "nrmp_max_num": 4,
            "dune_checkpoint": str(CHECKPOINT),
            "dune_device": dune_device,
            "dune_dtype": "float32",
        },
        adjust_kwargs={
            "q_s": 0.5,
            "p_u": 1.0,
            "eta": 15.0,
            "d_max": 1.0,
            "d_min": 0.1,
            "bk": 1.0,
            "solver": "ECOS",
        },
        train_kwargs={},
    )
    planner.update_initial_path_from_waypoints(planner.waypoints)
    return planner


def test_dune_defaults_to_planner_device_and_returns_planner_tensors():
    dune = _make_dune()
    outputs = dune(*_dune_inputs())

    assert dune.model_device.type == "cpu"
    assert dune.inference_dtype == torch.float32
    assert all(tensor.device.type == "cpu" for group in outputs for tensor in group)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA/ROCm is unavailable")
def test_dune_rocm_fp32_matches_cpu_and_preserves_cpu_boundary():
    cpu_dune = _make_dune("cpu")
    gpu_dune = _make_dune("cuda")
    inputs = _dune_inputs()

    cpu_outputs = cpu_dune(*inputs)
    gpu_outputs = gpu_dune(*inputs)

    assert gpu_dune.model_device.type == "cuda"
    for cpu_group, gpu_group in zip(cpu_outputs, gpu_outputs):
        for cpu_tensor, gpu_tensor in zip(cpu_group, gpu_group):
            assert gpu_tensor.device.type == "cpu"
            torch.testing.assert_close(gpu_tensor, cpu_tensor, rtol=1e-4, atol=1e-5)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA/ROCm is unavailable")
def test_hybrid_planner_keeps_nrmp_on_cpu_and_matches_cpu_action():
    cpu_planner = _make_planner("cpu")
    gpu_planner = _make_planner("cuda")
    state = np.array([[0.1], [0.0], [0.0]], dtype=np.float32)
    points = np.array(
        [[1.2, 1.4, 1.6, 1.8], [0.45, 0.55, 0.65, 0.75]], dtype=np.float32
    )

    cpu_action, _ = cpu_planner(state, points)
    gpu_action, gpu_info = gpu_planner(state, points)

    assert gpu_planner.pan.dune_layer.model_device.type == "cuda"
    assert gpu_planner.pan.nrmp_layer.G.device.type == "cpu"
    assert gpu_info["state_tensor"].device.type == "cpu"
    assert np.isfinite(gpu_action).all()
    np.testing.assert_allclose(gpu_action, cpu_action, rtol=1e-3, atol=1e-4)
