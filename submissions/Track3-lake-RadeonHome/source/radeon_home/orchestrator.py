"""Closed-loop task orchestration shared by the dashboard and simulator.

This module executes no hidden robot motion.  It produces the explicit
perceive -> plan -> navigate -> grasp -> place state trace that a Genesis
runner can consume or update with physical outcomes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .language import parse_instruction
from .local_llm import plan_with_local_qwen, validated_task_plan
from .semantic_world import observe_room
from .spatial_tasks import (
    OBJECT_ALLOWED_SOURCES,
    OBJECT_ALLOWED_TARGETS,
    SEMANTIC_DOCKS,
    TransportTask,
    build_room_grid,
    plan_transport,
)


TARGET_ZONE_BY_ID = {"trash_bin": "trash_bin", "tray": "door_tray", "cup": "coffee_table"}


@dataclass(frozen=True)
class TaskEvent:
    phase: str
    status: str
    message: str
    details: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _source_for_object(object_id: str, observation: dict) -> str:
    for item in observation["objects"]:
        if item["object_id"] == object_id:
            return item["zone"]
    return OBJECT_ALLOWED_SOURCES[object_id][0]


def preview_task(
    instruction: str,
    *,
    start_xy: tuple[float, float] = (-2.5, -2.5),
    use_local_llm: bool = False,
) -> dict:
    """Create an auditable task trace and collision-aware navigation routes."""

    llm = plan_with_local_qwen(instruction) if use_local_llm else None
    plan = parse_instruction(instruction) if llm is None else validated_task_plan(
        instruction, llm["task_plan"]
    )
    observation = observe_room()
    grid = build_room_grid()
    events = [
        TaskEvent("perceive", "complete", "Virtual RGB-D semantic observation received.", {
            "source": observation["source"], "object_count": len(observation["objects"])
        })
    ]
    routes = []
    robot_xy = start_xy
    for index, step in enumerate(plan.steps, start=1):
        source_zone = _source_for_object(step.object_id, observation)
        if step.target_id:
            target_zone = TARGET_ZONE_BY_ID[step.target_id]
        else:
            target_zone = "bedside_table"
        task = TransportTask(
            seed=index,
            object_id=step.object_id,
            source_zone=source_zone,
            target_zone=target_zone,
            start_xy=robot_xy,
        )
        route = plan_transport(task, grid)
        routes.append({
            "step": index,
            "object_id": step.object_id,
            "source_zone": source_zone,
            "target_zone": target_zone,
            "pickup_path": [list(cell) for cell in route.pickup_path],
            "delivery_path": [list(cell) for cell in route.delivery_path],
            "distance_m": route.total_distance_m,
            "constraints": [asdict(item) for item in step.constraints],
        })
        events.extend((
            TaskEvent("navigate", "queued", f"Navigate to {source_zone} for {step.object_id}.", {"step": index}),
            TaskEvent("grasp", "queued", f"Physically grasp {step.object_id}; verify contacts and slip state.", {"step": index}),
            TaskEvent("place", "queued", f"Carry to {target_zone} and place with constraints.", {"step": index}),
        ))
        robot_xy = SEMANTIC_DOCKS[target_zone]
    return {
        "mode": "preview_only",
        "disclosure": "Routes and semantic observations are deterministic simulator adapters. Physical success is recorded only after a Genesis execution run.",
        "instruction": instruction,
        "language_backend": llm or {"backend": "deterministic_parser", "llm_available": False},
        "task_plan": plan.to_dict(),
        "observation": observation,
        "events": [event.to_dict() for event in events],
        "routes": routes,
    }
