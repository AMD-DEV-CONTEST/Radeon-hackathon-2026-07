"""Language-conditioned task registry for RadeonVLA-Reflex.

Task tiers
----------
L1 Basic        — name a fruit + left/right bowl (single goal)
L2 Spatial      — grounding by spatial relation (leftmost / rightmost / nearest)
L3 Multi-step   — ordered multi-object sequences in one episode
L4 Rule-based   — attribute rules (e.g. yellow→left, purple→right)

The scripted expert and closed-loop policy execute a resolved goal list from
``radeonvla.grounding.resolve_task`` after each scene randomization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Grounding = Literal["named", "leftmost", "rightmost", "nearest_robot", "farthest_robot"]
Tier = Literal["L1", "L2", "L3", "L4"]


@dataclass(frozen=True, slots=True)
class SubGoalSpec:
    """One pick-and-place goal, possibly with deferred spatial grounding."""

    container: str  # white_left_bowl | blue_left_bowl | white_right_bowl | blue_right_bowl
    object_name: str | None = None  # concrete fruit when grounding == named
    grounding: Grounding = "named"
    # For rule-based expansion (L4): attribute filters applied at resolve time.
    attribute: str | None = None  # yellow | purple | curved | round


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    tier: Tier
    goals: tuple[SubGoalSpec, ...]
    training_instructions: tuple[str, ...]
    evaluation_instructions: tuple[str, ...]
    max_steps: int = 600
    max_retries: int = 1
    description: str = ""

    @property
    def target_object(self) -> str:
        """Return the first named goal or the backward-compatible fallback object."""
        g0 = self.goals[0]
        if g0.object_name is not None:
            return g0.object_name
        return f"@{g0.grounding}"

    @property
    def target_container(self) -> str:
        return self.goals[0].container

    @property
    def is_multi_step(self) -> bool:
        return len(self.goals) > 1 or self.tier in {"L3", "L4"}

    @property
    def n_goals(self) -> int:
        # L4 attribute rules expand at resolve time; upper bound used for logging.
        if self.tier == "L4":
            return 3
        return len(self.goals)


# Side keys map to container entity names via f"{side}_bowl".
# Left pair: white_left + blue_left; right pair: white_right + blue_right.
FRUIT_NAMES: tuple[str, ...] = ("banana", "lemon", "plum", "apple", "orange")
SIDE_NAMES: tuple[str, ...] = ("white_left", "blue_left", "white_right", "blue_right")

FRUIT_TRAIN_PHRASE: dict[str, str] = {
    "banana": "the banana",
    "lemon": "the lemon",
    "plum": "the plum",
    "apple": "the apple",
    "orange": "the orange",
}
FRUIT_EVAL_PHRASE: dict[str, str] = {
    "banana": "the yellow curved fruit",
    "lemon": "the yellow round fruit",
    "plum": "the purple fruit",
    "apple": "the red round fruit",
    "orange": "the orange citrus fruit",
}
SIDE_TRAIN_PHRASE: dict[str, str] = {
    "white_left": "the white bowl on the left",
    "blue_left": "the blue bowl on the left",
    "white_right": "the white bowl on the right",
    "blue_right": "the blue bowl on the right",
}
SIDE_EVAL_PHRASE: dict[str, str] = {
    "white_left": "the white container on the left",
    "blue_left": "the blue container on the left",
    "white_right": "the white container on the right",
    "blue_right": "the blue container on the right",
}


def _l1(fruit: str, side: str, training: tuple[str, ...], evaluation: tuple[str, ...]) -> TaskSpec:
    return TaskSpec(
        task_id=f"{fruit}_{side}",
        tier="L1",
        goals=(SubGoalSpec(object_name=fruit, container=f"{side}_bowl", grounding="named"),),
        training_instructions=training,
        evaluation_instructions=evaluation,
        max_steps=600,
        description=f"Pick {fruit} into {side} bowl.",
    )


def _l1_auto(fruit: str, side: str) -> TaskSpec:
    f_tr = FRUIT_TRAIN_PHRASE[fruit]
    f_ev = FRUIT_EVAL_PHRASE[fruit]
    s_tr = SIDE_TRAIN_PHRASE[side]
    s_ev = SIDE_EVAL_PHRASE[side]
    return _l1(
        fruit,
        side,
        (
            f"Pick {f_tr} and place it in {s_tr}.",
            f"Sort {f_tr} into {s_tr}.",
        ),
        (
            # L1 is the named-object benchmark. Keep the default held-out
            # instruction named as well; attribute descriptions belong to the
            # harder grounding stress test and remain available as variation 1.
            f"Put {f_tr} into {s_ev}.",
            f"Move {f_ev} to {s_ev}.",
        ),
    )


def _l2(
    task_id: str,
    grounding: Grounding,
    side: str,
    training: tuple[str, ...],
    evaluation: tuple[str, ...],
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        tier="L2",
        goals=(SubGoalSpec(object_name=None, container=f"{side}_bowl", grounding=grounding),),
        training_instructions=training,
        evaluation_instructions=evaluation,
        max_steps=700,
        description=f"Ground {grounding} fruit into {side} bowl.",
    )


def _l3(
    task_id: str,
    goals: tuple[SubGoalSpec, ...],
    training: tuple[str, ...],
    evaluation: tuple[str, ...],
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        tier="L3",
        goals=goals,
        training_instructions=training,
        evaluation_instructions=evaluation,
        max_steps=1400,
        description="Ordered multi-object sort.",
    )


def _l4(
    task_id: str,
    goals: tuple[SubGoalSpec, ...],
    training: tuple[str, ...],
    evaluation: tuple[str, ...],
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        tier="L4",
        goals=goals,
        training_instructions=training,
        evaluation_instructions=evaluation,
        max_steps=1800,
        description="Attribute rule-based multi-object sort.",
    )


# ---------------------------------------------------------------------------
# L1 — named fruit × container (5 fruits × 4 bowls = 20 tasks)
# ---------------------------------------------------------------------------
L1_TASKS: dict[str, TaskSpec] = {
    f"{fruit}_{side}": _l1_auto(fruit, side) for fruit in FRUIT_NAMES for side in SIDE_NAMES
}

# ---------------------------------------------------------------------------
# L2 — spatial grounding from the scene-relative layout after randomization.
# ---------------------------------------------------------------------------
L2_TASKS: dict[str, TaskSpec] = {
    "leftmost_to_white_left": _l2(
        "leftmost_to_white_left",
        "leftmost",
        "white_left",
        (
            "Pick the leftmost fruit on the table and put it in the white bowl on the left.",
            "Sort the fruit farthest left into the left white bowl.",
        ),
        (
            "Move the fruit closest to the left edge into the white container on the left.",
            "Place the leftmost fruit into the left white bowl.",
        ),
    ),
    "rightmost_to_white_right": _l2(
        "rightmost_to_white_right",
        "rightmost",
        "white_right",
        (
            "Pick the rightmost fruit on the table and put it in the white bowl on the right.",
            "Sort the fruit farthest right into the right white bowl.",
        ),
        (
            "Move the fruit closest to the right edge into the white container on the right.",
            "Place the rightmost fruit into the right white bowl.",
        ),
    ),
    "nearest_to_blue_left": _l2(
        "nearest_to_blue_left",
        "nearest_robot",
        "blue_left",
        (
            "Pick the fruit nearest to the robot and place it in the blue bowl on the left.",
            "Sort the closest fruit into the left blue bowl.",
        ),
        (
            "Move the nearest fruit into the blue container on the left.",
            "Place the closest reachable fruit into the left blue bowl.",
        ),
    ),
    "farthest_to_blue_right": _l2(
        "farthest_to_blue_right",
        "farthest_robot",
        "blue_right",
        (
            "Pick the fruit farthest from the robot and place it in the blue bowl on the right.",
            "Sort the most distant fruit into the right blue bowl.",
        ),
        (
            "Move the farthest fruit into the blue container on the right.",
            "Place the farthest fruit into the right blue bowl.",
        ),
    ),
    "leftmost_to_blue_left": _l2(
        "leftmost_to_blue_left",
        "leftmost",
        "blue_left",
        (
            "Pick the leftmost fruit and put it in the blue bowl on the left.",
            "Sort the left-most fruit into the left blue bowl.",
        ),
        (
            "Move the fruit farthest left into the blue container on the left.",
            "Place the leftmost fruit into the left blue bowl.",
        ),
    ),
}

# ---------------------------------------------------------------------------
# L3 — ordered multi-object sequences (long horizon)
# ---------------------------------------------------------------------------
L3_TASKS: dict[str, TaskSpec] = {
    "seq_banana_white_left_lemon_white_right": _l3(
        "seq_banana_white_left_lemon_white_right",
        (
            SubGoalSpec(object_name="banana", container="white_left_bowl"),
            SubGoalSpec(object_name="lemon", container="white_right_bowl"),
        ),
        (
            "First put the banana in the white bowl on the left, then the lemon in the white bowl on the right.",
            "Sort the banana into the left white bowl and the lemon into the right white bowl.",
        ),
        (
            (
                "Curved yellow fruit into the left white container, "
                "then round yellow fruit into the right white container."
            ),
            "Complete both white-bowl placements: banana then lemon.",
        ),
    ),
    "seq_plum_white_right_banana_white_left": _l3(
        "seq_plum_white_right_banana_white_left",
        (
            SubGoalSpec(object_name="plum", container="white_right_bowl"),
            SubGoalSpec(object_name="banana", container="white_left_bowl"),
        ),
        (
            "First put the plum in the white bowl on the right, then the banana in the white bowl on the left.",
            "Sort the plum into the right white bowl, then the banana into the left white bowl.",
        ),
        (
            "Purple fruit to the right white container, then the curved yellow fruit to the left white container.",
            "Complete both placements: plum then banana.",
        ),
    ),
    "seq_lemon_blue_left_plum_blue_left": _l3(
        "seq_lemon_blue_left_plum_blue_left",
        (
            SubGoalSpec(object_name="lemon", container="blue_left_bowl"),
            SubGoalSpec(object_name="plum", container="blue_left_bowl"),
        ),
        (
            "Put the lemon and then the plum into the blue bowl on the left.",
            "Sort both the lemon and the plum into the left blue bowl, lemon first.",
        ),
        (
            "Move the round yellow fruit and then the purple fruit into the left blue bowl.",
            "Both lemon and plum should end in the left blue container.",
        ),
    ),
    "seq_triple_sort": _l3(
        "seq_triple_sort",
        (
            SubGoalSpec(object_name="banana", container="white_left_bowl"),
            SubGoalSpec(object_name="lemon", container="blue_left_bowl"),
            SubGoalSpec(object_name="plum", container="white_right_bowl"),
        ),
        (
            (
                "Put the banana in the white left bowl, the lemon in the blue left bowl, "
                "and the plum in the white right bowl."
            ),
            "Left side: banana (white) then lemon (blue). Right white bowl: plum.",
        ),
        (
            "Yellow curved fruit to left white, yellow round fruit to left blue, purple fruit to right white.",
            "Complete the three-way sort across white and blue bowls.",
        ),
    ),
    "seq_apple_blue_left_orange_blue_right": _l3(
        "seq_apple_blue_left_orange_blue_right",
        (
            SubGoalSpec(object_name="apple", container="blue_left_bowl"),
            SubGoalSpec(object_name="orange", container="blue_right_bowl"),
        ),
        (
            "First put the apple in the blue bowl on the left, then the orange in the blue bowl on the right.",
            "Sort the apple into the left blue bowl and the orange into the right blue bowl.",
        ),
        (
            "Red fruit into the left blue container, then the citrus fruit into the right blue container.",
            "Complete both blue-bowl placements: apple then orange.",
        ),
    ),
    "seq_orange_white_right_plum_blue_left": _l3(
        "seq_orange_white_right_plum_blue_left",
        (
            SubGoalSpec(object_name="orange", container="white_right_bowl"),
            SubGoalSpec(object_name="plum", container="blue_left_bowl"),
        ),
        (
            "First put the orange in the white bowl on the right, then the plum in the blue bowl on the left.",
            "Sort the orange into the right white bowl, then the plum into the left blue bowl.",
        ),
        (
            "Citrus fruit to the right white container, then the purple fruit to the left blue container.",
            "Complete both steps: orange then plum.",
        ),
    ),
}

# ---------------------------------------------------------------------------
# L4 — attribute / rule-based sorting (expanded at resolve time)
# ---------------------------------------------------------------------------
L4_TASKS: dict[str, TaskSpec] = {
    "rule_yellow_white_left_purple_white_right": _l4(
        "rule_yellow_white_left_purple_white_right",
        (
            SubGoalSpec(container="white_left_bowl", grounding="named", attribute="yellow"),
            SubGoalSpec(container="white_right_bowl", grounding="named", attribute="purple"),
        ),
        (
            (
                "Put all yellow fruits into the white bowl on the left "
                "and the purple fruit into the white bowl on the right."
            ),
            "Sort by color: yellow→left white bowl, purple→right white bowl.",
        ),
        (
            "Move every yellow item into the left white container and the purple item into the right white container.",
            "Color rule on white bowls: yellow left, purple right.",
        ),
    ),
    "rule_curved_white_left_round_blue_right": _l4(
        "rule_curved_white_left_round_blue_right",
        (
            SubGoalSpec(container="white_left_bowl", grounding="named", attribute="curved"),
            SubGoalSpec(container="blue_right_bowl", grounding="named", attribute="round"),
        ),
        (
            (
                "Put the curved fruit into the white bowl on the left "
                "and the round fruits into the blue bowl on the right."
            ),
            "Shape rule: curved→left white bowl, round→right blue bowl.",
        ),
        (
            "Banana-like curved item into the left white container; spherical items into the right blue container.",
            "Sort by shape across white and blue bowls.",
        ),
    ),
    "rule_red_blue_left_orange_blue_right": _l4(
        "rule_red_blue_left_orange_blue_right",
        (
            SubGoalSpec(container="blue_left_bowl", grounding="named", attribute="red"),
            SubGoalSpec(container="blue_right_bowl", grounding="named", attribute="orange"),
        ),
        (
            "Put the red fruit into the blue bowl on the left and the orange fruit into the blue bowl on the right.",
            "Color rule: red→left blue bowl, orange→right blue bowl.",
        ),
        (
            "Red produce to the left blue container; orange produce to the right blue container.",
            "Sort by color into the blue bowls: red left, orange right.",
        ),
    ),
}

# Full registry (union). Suites select subsets.
TASKS: dict[str, TaskSpec] = {**L1_TASKS, **L2_TASKS, **L3_TASKS, **L4_TASKS}

SUITES: dict[str, tuple[str, ...]] = {
    # Baseline only (starter-comparable single-goal)
    "basic": tuple(sorted(L1_TASKS)),
    # Spatial + multi-step differentiators
    "advanced": tuple(sorted({*L2_TASKS, *L3_TASKS, *L4_TASKS})),
    # Competition default: mix for coverage and difficulty
    "full": tuple(sorted(TASKS)),
    # Long-horizon only (demo of hardness)
    "multistep": tuple(sorted(L3_TASKS)),
    "spatial": tuple(sorted(L2_TASKS)),
    "rules": tuple(sorted(L4_TASKS)),
}


def get_task(task_id: str) -> TaskSpec:
    try:
        return TASKS[task_id]
    except KeyError as exc:
        choices = ", ".join(sorted(TASKS))
        raise ValueError(f"Unknown task {task_id!r}. Expected one of: {choices}") from exc


def list_task_ids(suite: str | None = None) -> list[str]:
    if suite is None:
        return sorted(TASKS)
    if suite not in SUITES:
        raise ValueError(f"Unknown suite {suite!r}. Expected one of: {sorted(SUITES)}")
    return list(SUITES[suite])


def tasks_for_suite(suite: str = "full") -> dict[str, TaskSpec]:
    return {tid: TASKS[tid] for tid in list_task_ids(suite)}
