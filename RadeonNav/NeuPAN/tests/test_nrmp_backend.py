import warnings

import pytest
import torch

from neupan import configuration
from neupan.blocks import NRMP
from neupan.robot import robot


def make_robot(receding: int = 2) -> robot:
    return robot(
        receding=receding,
        step_time=0.1,
        kinematics="diff",
        max_speed=[1.0, 1.0],
        max_acce=[2.0, 2.0],
        length=0.70,
        width=0.40,
    )


def test_cpu_backend_remains_default():
    configuration.device = torch.device("cpu")
    layer = NRMP(2, 0.1, make_robot(), nrmp_max_num=0)

    assert layer.nrmp_backend_requested == "cvxpylayers_cpu"
    assert layer.nrmp_backend == "cvxpylayers_cpu"


def test_mpax_request_without_safe_launcher_falls_back(monkeypatch):
    configuration.device = torch.device("cpu")
    monkeypatch.delenv("RADEONNAV_MPAX_ROCM", raising=False)
    monkeypatch.delenv("LD_PRELOAD", raising=False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        layer = NRMP(
            2,
            0.1,
            make_robot(),
            nrmp_max_num=0,
            nrmp_backend="mpax_rocm",
        )

    assert layer.nrmp_backend_requested == "mpax_rocm"
    assert layer.nrmp_backend == "cvxpylayers_cpu"
    assert "RADEONNAV_MPAX_ROCM=1" in layer.nrmp_backend_reason
    assert any("falling back" in str(item.message) for item in caught)


def test_mpax_request_can_disable_fallback(monkeypatch):
    configuration.device = torch.device("cpu")
    monkeypatch.delenv("RADEONNAV_MPAX_ROCM", raising=False)

    with pytest.raises(RuntimeError, match="RADEONNAV_MPAX_ROCM=1"):
        NRMP(
            2,
            0.1,
            make_robot(),
            nrmp_max_num=0,
            nrmp_backend="mpax_rocm",
            nrmp_fallback=False,
        )
