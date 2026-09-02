"""Small deterministic language layer for the initial household task set."""

from __future__ import annotations

from .models import ActionType, SafetyConstraint, TaskPlan, TaskStep


DEFAULT_INSTRUCTION = (
    "清理桌面，把垃圾扔掉，把钥匙放进托盘，"
    "把药盒放在水杯旁边，不要碰倒水杯"
)


def parse_instruction(instruction: str) -> TaskPlan:
    """Convert supported Chinese/English household commands into a task plan.

    This deterministic parser is the reproducible baseline. A language model can
    later emit the same TaskPlan schema without changing the controller.
    """

    normalized = instruction.lower().replace("，", ",").replace("。", ".")
    steps: list[TaskStep] = []

    if any(word in normalized for word in ("垃圾", "trash", "rubbish")):
        steps.append(
            TaskStep(
                action=ActionType.PICK_AND_PLACE,
                object_id="trash",
                target_id="trash_bin",
            )
        )

    if any(word in normalized for word in ("钥匙", "key")):
        steps.append(
            TaskStep(
                action=ActionType.PICK_AND_PLACE,
                object_id="keys",
                target_id="tray",
            )
        )

    if any(word in normalized for word in ("药盒", "药品", "medicine")):
        protect_cup = any(
            phrase in normalized
            for phrase in (
                "不要碰倒水杯",
                "不要移动水杯",
                "don't touch the cup",
                "do not touch the cup",
            )
        )
        constraints = (
            (SafetyConstraint("avoid_contact", "cup", 0.10),)
            if protect_cup
            else ()
        )
        steps.append(
            TaskStep(
                action=ActionType.PLACE_NEAR,
                object_id="medicine",
                reference_id="cup",
                constraints=constraints,
            )
        )

    if not steps:
        raise ValueError(
            "No supported household task found. Mention trash, keys, or medicine."
        )

    return TaskPlan(instruction=instruction, steps=steps)

