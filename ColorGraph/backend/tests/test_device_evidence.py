from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import torch

from colorgraph.devices.evidence import (
    TorchStageEvidence,
    TorchStageEvidenceRecorder,
    require_amd_rocm_stage_evidence,
)


class _CpuBackend:
    torch_device = torch.device("cpu")
    info = SimpleNamespace(
        runtime="cpu",
        vendor="Generic",
        name="Unit Test CPU",
        torch_version=torch.__version__,
    )

    def inference_context(self, *, mixed_precision: bool = True):
        return nullcontext()

    def synchronize(self) -> None:
        return None


def test_cpu_stage_evidence_records_real_tensor_placement_and_fails_amd_gate() -> None:
    backend = _CpuBackend()
    model = torch.nn.Linear(2, 1)
    inputs = torch.ones((1, 2))
    recorder = TorchStageEvidenceRecorder(
        backend,
        stage="unit_test",
        model_id="unit/model",
        model=model,
        inputs=inputs,
    )

    output = model(inputs)
    evidence = recorder.finish(output)

    assert evidence.model_devices == ["cpu"]
    assert evidence.input_devices == ["cpu"]
    assert evidence.output_devices == ["cpu"]
    assert not evidence.accelerator_tensors_verified
    assert not evidence.amd_rocm_verified
    with pytest.raises(RuntimeError, match="runtime=cpu"):
        require_amd_rocm_stage_evidence(evidence)


def test_complete_amd_evidence_passes_fail_closed_gate() -> None:
    evidence = TorchStageEvidence(
        stage="clip_image_embedding",
        model_id="openai/clip-vit-base-patch32",
        runtime="rocm",
        vendor="AMD",
        device_name="AMD Radeon RX 7900 XTX",
        torch_device="cuda:0",
        torch_version="2.9.1+rocm7.2",
        hip_version="7.2.1",
        model_devices=["cuda:0"],
        input_devices=["cuda:0"],
        output_devices=["cuda:0"],
        allocated_bytes_at_start=1024,
        peak_allocated_bytes=2048,
        peak_reserved_bytes=4096,
        accelerator_tensors_verified=True,
        amd_rocm_verified=True,
    )

    require_amd_rocm_stage_evidence(evidence)
