"""Resolve language / spatial / attribute goals into concrete fruit targets.

After domain randomization, fruit poses change. L2 tasks refer to fruits by
spatial relations; L4 tasks expand attribute rules into ordered subgoals.
This module is the single place that maps abstract ``SubGoalSpec`` → concrete
object names for the expert, recorder, and evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from radeonvla.safety import entity_pos
from radeonvla.tasks import SubGoalSpec, TaskSpec

FRUITS = ("banana", "lemon", "plum", "apple", "orange")

# Visual / semantic attributes used by L4 rule tasks.
ATTRIBUTES: dict[str, frozenset[str]] = {
    "yellow": frozenset({"banana", "lemon"}),
    "purple": frozenset({"plum"}),
    "red": frozenset({"apple"}),
    "orange": frozenset({"orange"}),
    "curved": frozenset({"banana"}),
    "round": frozenset({"lemon", "plum", "apple", "orange"}),
}


@dataclass(frozen=True, slots=True)
class ResolvedGoal:
    object_name: str
    container: str


@dataclass(frozen=True, slots=True)
class ResolvedTask:
    task_id: str
    tier: str
    goals: tuple[ResolvedGoal, ...]
    instruction: str
    max_steps: int
    max_retries: int

    @property
    def target_object(self) -> str:
        return self.goals[0].object_name

    @property
    def target_container(self) -> str:
        return self.goals[0].container

    @property
    def is_multi_step(self) -> bool:
        return len(self.goals) > 1


def fruit_positions(bundle) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for name in FRUITS:
        if name in bundle.objects:
            out[name] = entity_pos(bundle.objects[name])
    return out


def _select_spatial(positions: dict[str, np.ndarray], grounding: str) -> str:
    if not positions:
        raise RuntimeError("No fruits available for spatial grounding.")
    # Table frame: +x away from robot base (base at x≈-0.1), +y left of robot facing +x.
    if grounding == "leftmost":
        return max(positions, key=lambda n: float(positions[n][1]))
    if grounding == "rightmost":
        return min(positions, key=lambda n: float(positions[n][1]))
    if grounding == "nearest_robot":
        # Robot base near (-0.10, 0.0); nearest ≈ smallest x among fruits on table.
        return min(positions, key=lambda n: float(positions[n][0]))
    if grounding == "farthest_robot":
        return max(positions, key=lambda n: float(positions[n][0]))
    raise ValueError(f"Unknown spatial grounding {grounding!r}")


def _expand_attribute_goals(goals: tuple[SubGoalSpec, ...]) -> list[SubGoalSpec]:
    """Expand L4 attribute markers into named single-fruit goals.

    Order: for each SubGoalSpec with an attribute, emit one goal per matching
    fruit in canonical FRUITS order (stable demos for BC).
    """
    expanded: list[SubGoalSpec] = []
    for g in goals:
        if g.attribute is None:
            expanded.append(g)
            continue
        if g.attribute not in ATTRIBUTES:
            raise ValueError(f"Unknown attribute {g.attribute!r}")
        matches = [f for f in FRUITS if f in ATTRIBUTES[g.attribute]]
        for fruit in matches:
            expanded.append(SubGoalSpec(object_name=fruit, container=g.container, grounding="named"))
    return expanded


def resolve_goals(bundle, task: TaskSpec) -> tuple[ResolvedGoal, ...]:
    positions = fruit_positions(bundle)
    specs = task.goals
    if task.tier == "L4":
        specs = tuple(_expand_attribute_goals(specs))

    resolved: list[ResolvedGoal] = []
    used: set[str] = set()
    for g in specs:
        if g.grounding == "named":
            if g.object_name is None:
                raise ValueError(f"Named goal missing object_name in task {task.task_id}")
            name = g.object_name
        else:
            # Spatial among remaining fruits when possible (avoid reusing same fruit).
            remaining = {k: v for k, v in positions.items() if k not in used}
            pool = remaining if remaining else positions
            name = _select_spatial(pool, g.grounding)
        if name not in positions:
            raise RuntimeError(f"Fruit {name!r} not in scene for task {task.task_id}")
        resolved.append(ResolvedGoal(object_name=name, container=g.container))
        used.add(name)
    return tuple(resolved)


def resolve_task(bundle, task: TaskSpec, *, instruction: str | None = None, train: bool = True) -> ResolvedTask:
    goals = resolve_goals(bundle, task)
    if instruction is None:
        pool = task.training_instructions if train else task.evaluation_instructions
        instruction = pool[0]
    return ResolvedTask(
        task_id=task.task_id,
        tier=task.tier,
        goals=goals,
        instruction=instruction,
        max_steps=task.max_steps,
        max_retries=task.max_retries,
    )


def check_resolved_success(
    bundle,
    resolved: ResolvedTask,
    *,
    success_tol: float = 0.06,
    strict: bool = False,
) -> dict:
    """Evaluate every subgoal; episode succeeds only if all are satisfied."""
    from radeonvla.safety import check_placement_success
    from radeonvla.tasks import SubGoalSpec
    from radeonvla.tasks import TaskSpec as _TS

    per_goal = []
    all_ok = True
    for g in resolved.goals:
        # Reuse single-goal spatial success via a tiny synthetic TaskSpec.
        synthetic = _TS(
            task_id=f"_goal_{g.object_name}_{g.container}",
            tier="L1",
            goals=(SubGoalSpec(object_name=g.object_name, container=g.container),),
            training_instructions=("",),
            evaluation_instructions=("",),
        )
        ok, obj_ok, tgt_ok = check_placement_success(
            bundle,
            synthetic,
            success_tol=success_tol,
            strict=strict,
        )
        per_goal.append(
            {
                "object": g.object_name,
                "container": g.container,
                "success": ok,
                "object_correct": obj_ok,
                "target_correct": tgt_ok,
            }
        )
        all_ok = all_ok and ok

    return {
        "success": all_ok,
        "n_goals": len(resolved.goals),
        "n_success": sum(1 for g in per_goal if g["success"]),
        "partial_success_rate": (sum(1 for g in per_goal if g["success"]) / max(1, len(per_goal))),
        "goals": per_goal,
        "object_correct": all(g["object_correct"] or g["success"] for g in per_goal),
        "target_correct": all(g["target_correct"] for g in per_goal),
        "strict_physics": strict,
    }
