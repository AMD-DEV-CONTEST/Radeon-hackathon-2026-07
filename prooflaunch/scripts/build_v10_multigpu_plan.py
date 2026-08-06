#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.v10_multigpu import build_multigpu_plan  # noqa: E402


PROGRAM = ROOT / "evidence" / "v10" / "program-manifest.json"
OUTPUT = ROOT / "evidence" / "v10" / "multigpu-execution-plan.json"


def main() -> None:
    program = json.loads(PROGRAM.read_text(encoding="utf-8"))
    plans = build_multigpu_plan(program["todos"])
    records = [item.to_dict() for item in plans]
    canonical = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    classes = Counter(record["execution_class"] for record in records)
    direct = sum(
        record["requires_direct_multigpu_observation"]
        for record in records
    )
    payload = {
        "schema": "ProofLaunchV10MultiGpuExecutionPlanV1",
        "truth_policy": (
            "A multi-GPU plan is not multi-GPU execution. Direct GPU work "
            "remains not_started until a >=2-GPU ROCm/RCCL run records every "
            "rank, shard, collective, checkpoint, equivalence, timing, and "
            "peak-VRAM receipt. Single-GPU fallback may preserve debugging "
            "progress but cannot satisfy a multi-GPU claim."
        ),
        "strategy_policy": {
            "minimum_physical_gpus_for_direct_work": 2,
            "backend_api": "nccl",
            "runtime_implementation": "RCCL on ROCm",
            "default_training_strategy": (
                "DDP only after per-rank memory-fit preflight"
            ),
            "memory_fallback": (
                "FSDP2 only after correctness/equivalence preflight"
            ),
            "forbidden_training_strategy": "device_map=auto",
            "stage_parallelism": (
                "Dependency-ordered stages remain sequential; ranks shard "
                "data, samples, seeds, or model state inside a stage."
            ),
            "state_owner": "rank 0 only, with atomic shared-stage commit",
            "world_size_policy": (
                "Freeze WORLD_SIZE at run start; abort on rank loss or "
                "silent elasticity."
            ),
        },
        "performance_admission": {
            "comparison": (
                "same immutable model/data revisions, global batch, steps, "
                "seeds, precision, warmup, and output contract"
            ),
            "repeats": 3,
            "two_gpu_minimum_speedup": 1.5,
            "minimum_parallel_efficiency": 0.70,
            "correctness_precedes_speed": True,
            "speedup_failure_effect": (
                "retain correctness evidence but do not promote fastest or "
                "efficient multi-GPU claims"
            ),
        },
        "stability_admission": {
            "cold_launch_trials": 3,
            "checkpoint_resume_trials": 2,
            "allowed_missing_ranks": 0,
            "allowed_duplicate_shards": 0,
            "allowed_collective_mismatches": 0,
            "allowed_nonfinite_gradients": 0,
        },
        "launch_contracts": {
            "collective_preflight": (
                "torchrun --standalone --nproc_per_node=<GPU_COUNT> "
                "scripts/verify_rocm_multigpu.py"
            ),
            "gemma_single_gpu_baseline": (
                "accelerate launch --config_file "
                "configs/accelerate/rocm_1gpu_baseline.yaml "
                "scripts/train_gemma4_emotion_multigpu.py "
                "--run-profile candidate --model-revision <40-char-sha> "
                "--dataset-revision <40-char-sha> "
                "--expected-world-size 1 --parallelism single "
                "--per-device-train-batch-size 2 "
                "--gradient-accumulation-steps 8 "
                "--expected-global-batch-size 16"
            ),
            "gemma_ddp_2gpu": (
                "accelerate launch --config_file "
                "configs/accelerate/rocm_2gpu_ddp.yaml "
                "scripts/train_gemma4_emotion_multigpu.py "
                "--run-profile candidate --model-revision <40-char-sha> "
                "--dataset-revision <40-char-sha> "
                "--expected-world-size 2 --parallelism ddp "
                "--expected-global-batch-size 16"
            ),
            "gemma_ddp_4gpu": (
                "accelerate launch --config_file "
                "configs/accelerate/rocm_4gpu_ddp.yaml "
                "scripts/train_gemma4_emotion_multigpu.py "
                "--run-profile final --model-revision <40-char-sha> "
                "--dataset-revision <40-char-sha> "
                "--expected-world-size 4 --parallelism ddp "
                "--per-device-train-batch-size 2 "
                "--gradient-accumulation-steps 2 "
                "--expected-global-batch-size 16"
            ),
            "gemma_fsdp2_2gpu": (
                "accelerate launch --config_file "
                "configs/accelerate/rocm_2gpu_fsdp2.yaml "
                "scripts/train_gemma4_emotion_multigpu.py "
                "--run-profile final --model-revision <40-char-sha> "
                "--dataset-revision <40-char-sha> "
                "--expected-world-size 2 --parallelism fsdp2 "
                "--expected-global-batch-size 16"
            ),
            "training_admission": (
                "python scripts/verify_multigpu_training_admission.py "
                "--single-manifest <single>/distributed-training-manifest.json "
                "--multi-manifest <repeat-1>/distributed-training-manifest.json "
                "--multi-manifest <repeat-2>/distributed-training-manifest.json "
                "--multi-manifest <repeat-3>/distributed-training-manifest.json "
                "--output evidence/v10/multigpu-training-admission.json"
            ),
        },
        "coverage": {
            "todo_count": len(records),
            "todos_with_program_multigpu_binding": sum(
                record["program_multigpu_binding"] for record in records
            ),
            "todos_requiring_direct_multigpu_observation": direct,
            "todos_program_bound_without_fake_gpu_work": (
                len(records) - direct
            ),
            "execution_class_counts": dict(sorted(classes.items())),
        },
        "todo_plan_sha256": hashlib.sha256(canonical).hexdigest(),
        "plans": records,
    }
    contract_canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["contract_sha256"] = hashlib.sha256(
        contract_canonical
    ).hexdigest()
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "coverage": payload["coverage"],
                "todo_plan_sha256": payload["todo_plan_sha256"],
                "contract_sha256": payload["contract_sha256"],
                "output": str(OUTPUT),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
