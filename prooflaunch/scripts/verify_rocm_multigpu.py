#!/usr/bin/env python3
"""Fail-closed ROCm/RCCL multi-GPU preflight.

Launch with:
    torchrun --standalone --nproc_per_node=2 scripts/verify_rocm_multigpu.py

PyTorch intentionally names the ROCm collective backend ``nccl``. On an AMD
build the implementation is RCCL, which is confirmed separately by
``torch.version.hip``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> None:
    import torch
    import torch.distributed as dist

    if not torch.cuda.is_available():
        raise RuntimeError("ROCm GPU is unavailable")
    if not torch.version.hip:
        raise RuntimeError("PyTorch is not a ROCm/HIP build")

    rank = int(os.environ["RANK"])
    local_rank = int(os.environ["LOCAL_RANK"])
    world_size = int(os.environ["WORLD_SIZE"])
    if world_size < 2:
        raise RuntimeError("Multi-GPU preflight requires at least two ranks")
    if torch.cuda.device_count() < world_size:
        raise RuntimeError(
            f"Visible GPU count {torch.cuda.device_count()} is below world size "
            f"{world_size}"
        )

    torch.cuda.set_device(local_rank)
    dist.init_process_group(backend="nccl")
    probe = torch.tensor(float(rank + 1), device=f"cuda:{local_rank}")
    dist.all_reduce(probe, op=dist.ReduceOp.SUM)
    torch.cuda.synchronize(local_rank)

    expected = world_size * (world_size + 1) / 2
    passed = float(probe.item()) == expected
    local = {
        "rank": rank,
        "local_rank": local_rank,
        "device": torch.cuda.get_device_name(local_rank),
        "all_reduce": float(probe.item()),
        "expected": expected,
        "passed": passed,
    }
    gathered: list[dict | None] = [None] * world_size
    dist.all_gather_object(gathered, local)

    if rank == 0:
        report = {
            "schema": "ProofLaunchRocmMultiGpuPreflightV1",
            "passed": all(bool(item and item["passed"]) for item in gathered),
            "hip_version": str(torch.version.hip),
            "torch_version": torch.__version__,
            "world_size": world_size,
            "backend": "nccl-api-over-rccl",
            "ranks": gathered,
        }
        output = Path(
            os.environ.get(
                "PROOFLAUNCH_MULTIGPU_PREFLIGHT_OUTPUT",
                "evidence/radeon/rocm-multigpu-preflight.json",
            )
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False))
        if not report["passed"]:
            raise RuntimeError("RCCL all-reduce preflight failed")

    dist.barrier()
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
