from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Mapping, Sequence


class MultiGpuPlanError(ValueError):
    pass


class ExecutionClass(str, Enum):
    CONTROLLER = "single_supervisor_multi_gpu_barrier"
    DATA = "distributed_data_preprocess"
    TRAINING = "ddp_then_fsdp2"
    EVALUATION = "rank_sharded_eval"
    MEDIA = "rank_sharded_inference"


TRAINING_WORKSTREAMS = frozenset(
    {4, 7, 8, 13, 14, 15, 16, 17, 18, 30, 31, 32, 33, 34}
)
EVALUATION_WORKSTREAMS = frozenset(
    {3, 5, 12, 21, 23, 25, 26, 29, 35, 36}
)
MEDIA_WORKSTREAMS = frozenset({19, 20, 27, 28})
DATA_WORKSTREAMS = frozenset({2, 9, 10, 11, 22})
CONTROLLER_WORKSTREAMS = frozenset({1, 6, 24})

DIRECT_MULTI_GPU_WORKSTREAMS = frozenset(
    TRAINING_WORKSTREAMS
    | EVALUATION_WORKSTREAMS
    | MEDIA_WORKSTREAMS
)

UNIVERSAL_GATES = (
    "official_program_compliance",
    "program_multigpu_binding",
    "immutable_gpu_inventory",
    "rccl_collective_preflight",
    "frozen_world_size",
    "rank_completeness",
    "unique_input_shards",
    "atomic_stage_commit",
    "single_gpu_equivalence",
    "per_rank_timing_and_peak_vram",
    "truthful_no_silent_fallback",
)


@dataclass(frozen=True)
class TodoMultiGpuPlan:
    todo_id: str
    workstream_id: int
    execution_wave: str
    dependency_workstreams: tuple[int, ...]
    execution_class: ExecutionClass
    program_multigpu_binding: bool
    requires_direct_multigpu_observation: bool
    minimum_world_size: int
    preferred_strategy: str
    fallback_strategy: str
    shard_key: str
    synchronization_boundary: str
    required_gates: tuple[str, ...]
    current_status: str

    def to_dict(self) -> dict:
        value = asdict(self)
        value["execution_class"] = self.execution_class.value
        value["dependency_workstreams"] = list(
            self.dependency_workstreams
        )
        value["required_gates"] = list(self.required_gates)
        return value


def execution_class_for(workstream_id: int) -> ExecutionClass:
    if workstream_id in TRAINING_WORKSTREAMS:
        return ExecutionClass.TRAINING
    if workstream_id in EVALUATION_WORKSTREAMS:
        return ExecutionClass.EVALUATION
    if workstream_id in MEDIA_WORKSTREAMS:
        return ExecutionClass.MEDIA
    if workstream_id in DATA_WORKSTREAMS:
        return ExecutionClass.DATA
    if workstream_id in CONTROLLER_WORKSTREAMS:
        return ExecutionClass.CONTROLLER
    raise MultiGpuPlanError(
        f"workstream {workstream_id} has no execution class"
    )


def _class_gates(execution_class: ExecutionClass) -> tuple[str, ...]:
    if execution_class is ExecutionClass.TRAINING:
        return (
            "global_batch_invariance",
            "optimizer_step_invariance",
            "gradient_finite_all_ranks",
            "checkpoint_resume_all_ranks",
            "ddp_or_fsdp2_memory_fit",
            "multimodal_frozen_parameter_fingerprint",
            "three_cold_launches",
            "two_resume_trials",
            "throughput_speedup_gate",
        )
    if execution_class is ExecutionClass.EVALUATION:
        return (
            "sample_id_partition_exact_once",
            "metric_reduce_reference_equivalence",
            "three_cold_launches",
            "throughput_speedup_gate",
        )
    if execution_class is ExecutionClass.MEDIA:
        return (
            "prompt_seed_partition_exact_once",
            "decoded_media_hash_binding",
            "four_k_output_gate",
            "three_cold_launches",
            "throughput_speedup_gate",
        )
    if execution_class is ExecutionClass.DATA:
        return (
            "source_hash_partition_exact_once",
            "deterministic_merge_order",
            "no_train_eval_leakage",
        )
    return (
        "single_state_owner",
        "dependency_barrier",
        "no_duplicate_side_effect",
    )


def plan_for(todo: Mapping[str, object]) -> TodoMultiGpuPlan:
    todo_id = str(todo["todo_id"])
    workstream_id = int(todo["workstream_id"])
    execution_class = execution_class_for(workstream_id)
    direct = workstream_id in DIRECT_MULTI_GPU_WORKSTREAMS
    if execution_class is ExecutionClass.TRAINING:
        preferred = "ddp_after_memory_fit_preflight"
        fallback = "fsdp2_after_equivalence_preflight"
    elif execution_class in {
        ExecutionClass.EVALUATION,
        ExecutionClass.MEDIA,
    }:
        preferred = execution_class.value
        fallback = "single_gpu_hold_multi_gpu_claim"
    elif execution_class is ExecutionClass.DATA:
        preferred = "deterministic_rank_sharded_preprocess"
        fallback = "controller_only_hold_speedup_claim"
    else:
        preferred = "rank_zero_state_owner_with_global_barriers"
        fallback = "controller_only_hold_multi_gpu_claim"
    return TodoMultiGpuPlan(
        todo_id=todo_id,
        workstream_id=workstream_id,
        execution_wave=str(todo["execution_wave"]),
        dependency_workstreams=tuple(
            int(item) for item in todo["dependency_workstreams"]
        ),
        execution_class=execution_class,
        program_multigpu_binding=True,
        requires_direct_multigpu_observation=direct,
        minimum_world_size=2 if direct else 1,
        preferred_strategy=preferred,
        fallback_strategy=fallback,
        shard_key=f"{todo_id}:stable_sample_or_seed_id",
        synchronization_boundary=(
            f"{todo['execution_wave']}:{workstream_id}:atomic_commit"
        ),
        required_gates=tuple(
            dict.fromkeys(
                (*UNIVERSAL_GATES, *_class_gates(execution_class))
            )
        ),
        current_status="not_started",
    )


def build_multigpu_plan(
    todos: Sequence[Mapping[str, object]],
) -> tuple[TodoMultiGpuPlan, ...]:
    plans = tuple(plan_for(todo) for todo in todos)
    ids = [item.todo_id for item in plans]
    if len(ids) != 1500 or ids != [
        f"{index:04d}" for index in range(1, 1501)
    ]:
        raise MultiGpuPlanError(
            "multi-GPU plan requires ordered TODOs 0001 through 1500"
        )
    if not all(item.program_multigpu_binding for item in plans):
        raise MultiGpuPlanError("every TODO must bind to the multi-GPU program")
    return plans
