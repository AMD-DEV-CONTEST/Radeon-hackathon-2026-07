import pytest

from radeon_home.local_llm import _json_object, validated_task_plan
from radeon_home.models import ActionType


def test_qwen_json_plan_is_converted_to_typed_allow_list() -> None:
    plan = validated_task_plan("把废弃包装收进废物容器", {
        "steps": [{
            "action": "pick_and_place",
            "object_id": "trash",
            "target_id": "trash_bin",
            "reference_id": None,
            "constraints": [],
        }],
    })
    assert plan.steps[0].action is ActionType.PICK_AND_PLACE
    assert plan.steps[0].object_id == "trash"
    assert plan.steps[0].target_id == "trash_bin"


def test_qwen_cannot_invent_robot_action_or_object() -> None:
    with pytest.raises(ValueError, match="allow-list"):
        validated_task_plan("打开冰箱", {
            "steps": [{
                "action": "pick_and_place",
                "object_id": "fridge",
                "target_id": "kitchen",
                "reference_id": None,
            }],
        })


def test_qwen_cannot_inject_unsafe_constraint() -> None:
    with pytest.raises(ValueError, match="safety allow-list"):
        validated_task_plan("把药放在杯子旁边", {
            "steps": [{
                "action": "place_near",
                "object_id": "medicine",
                "target_id": None,
                "reference_id": "cup",
                "constraints": [{
                    "kind": "disable_collision",
                    "object_id": "cup",
                }],
            }],
        })


def test_json_object_accepts_fenced_model_reply() -> None:
    assert _json_object('```json\n{"steps": []}\n```') == {"steps": []}
