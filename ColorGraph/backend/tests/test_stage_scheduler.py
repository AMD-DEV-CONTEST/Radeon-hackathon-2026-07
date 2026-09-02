from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import torch

import colorgraph.devices.stage_scheduler as stage_scheduler
from colorgraph.devices.stage_scheduler import release_pytorch_stage


class _CpuBackend:
    torch_device = torch.device("cpu")
    info = SimpleNamespace(runtime="cpu")

    def inference_context(self, *, mixed_precision: bool = True):
        return nullcontext()

    def empty_cache(self) -> None:
        return None

    def synchronize(self) -> None:
        return None


def test_cpu_stage_release_produces_explicit_zero_memory_evidence() -> None:
    evidence = release_pytorch_stage(
        _CpuBackend(),
        transition="analysis-to-ollama",
    )

    assert evidence.release_verified
    assert evidence.before.runtime == "cpu"
    assert evidence.after.allocated_bytes == 0
    assert evidence.after.reserved_bytes == 0
    assert evidence.after.model_cache_entries == 0


def test_stage_release_collects_unreachable_tensor_cycles(monkeypatch) -> None:
    collections = 0

    def collect() -> int:
        nonlocal collections
        collections += 1
        return 0

    monkeypatch.setattr(stage_scheduler.gc, "collect", collect)

    release_pytorch_stage(_CpuBackend(), transition="clip-to-semantic")

    assert collections == 1


def test_accelerator_release_clears_blas_workspaces(monkeypatch) -> None:
    clears = 0

    def clear_workspaces() -> None:
        nonlocal clears
        clears += 1

    monkeypatch.setattr(
        stage_scheduler.torch._C,
        "_cuda_clearCublasWorkspaces",
        clear_workspaces,
    )
    backend = SimpleNamespace(info=SimpleNamespace(runtime="rocm"))

    assert stage_scheduler._clear_accelerator_blas_workspaces(backend)
    assert clears == 1
