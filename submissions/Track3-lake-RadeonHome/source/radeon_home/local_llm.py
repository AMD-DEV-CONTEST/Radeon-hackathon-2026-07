"""Optional local-Qwen task parser served by vLLM on the Radeon GPU.

The model is never allowed to command joints directly.  It can only return a
small task-plan JSON object; :mod:`radeon_home.language` and the navigation
layer remain the validation and execution boundary.
"""

from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from .language import parse_instruction
from .models import ActionType, SafetyConstraint, TaskPlan, TaskStep


DEFAULT_ENDPOINT = "http://127.0.0.1:8000/v1/chat/completions"
DEFAULT_MODEL = "Qwen/Qwen3-4B"


_PICK_TARGETS = {"trash": "trash_bin", "keys": "tray"}


def validated_task_plan(instruction: str, payload: dict) -> TaskPlan:
    """Convert model JSON into the small executable allow-list.

    Qwen may choose the supported semantic task, but it cannot invent objects,
    actions, targets, constraints, coordinates, or robot commands.
    """

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 3:
        raise ValueError("Qwen plan must contain one to three steps")
    steps: list[TaskStep] = []
    seen: set[str] = set()
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise ValueError("Each Qwen step must be an object")
        action = ActionType(raw.get("action"))
        object_id = raw.get("object_id")
        target_id = raw.get("target_id")
        reference_id = raw.get("reference_id")
        if (
            action is ActionType.PICK_AND_PLACE
            and object_id in _PICK_TARGETS
            and target_id == _PICK_TARGETS[object_id]
        ):
            # Optional fields that do not apply to this action are discarded.
            # They never become planner inputs or robot commands.
            target_id, reference_id = _PICK_TARGETS[object_id], None
        elif (
            action is ActionType.PLACE_NEAR
            and object_id == "medicine"
            and reference_id == "cup"
        ):
            target_id, reference_id = None, "cup"
        else:
            raise ValueError("Qwen step is outside the supported task allow-list")
        if object_id in seen:
            raise ValueError("Qwen plan contains a duplicate object task")
        seen.add(object_id)
        constraints: list[SafetyConstraint] = []
        for item in raw.get("constraints") or []:
            if not isinstance(item, dict):
                raise ValueError("Qwen constraint must be an object")
            clearance = float(item.get("minimum_clearance_m", 0.10))
            if (
                item.get("kind") != "avoid_contact"
                or item.get("object_id") != "cup"
                or not 0.05 <= clearance <= 0.25
            ):
                raise ValueError("Qwen constraint is outside the safety allow-list")
            constraints.append(SafetyConstraint("avoid_contact", "cup", clearance))
        steps.append(TaskStep(
            action=action,
            object_id=object_id,
            target_id=target_id,
            reference_id=reference_id,
            constraints=tuple(constraints),
        ))
    return TaskPlan(instruction=instruction, steps=steps)


def _json_object(text: str) -> dict:
    """Extract one JSON object while rejecting prose-only model output."""

    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Qwen did not return a JSON object")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Qwen response is not a JSON object")
    return value


def local_qwen_status(endpoint: str | None = None) -> dict:
    """Report availability without treating an unavailable model as an error."""

    endpoint = endpoint or os.getenv("RADEONHOME_LLM_ENDPOINT", DEFAULT_ENDPOINT)
    models_url = endpoint.removesuffix("/chat/completions") + "/models"
    try:
        with urlopen(models_url, timeout=1.5) as response:  # noqa: S310 - local endpoint
            payload = json.loads(response.read())
        return {"available": True, "endpoint": endpoint, "models": payload.get("data", [])}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return {"available": False, "endpoint": endpoint, "reason": str(error)}


def plan_with_local_qwen(instruction: str, endpoint: str | None = None) -> dict:
    """Ask local Qwen for a semantic plan, then enforce the executable allow-list."""

    endpoint = endpoint or os.getenv("RADEONHOME_LLM_ENDPOINT", DEFAULT_ENDPOINT)
    status = local_qwen_status(endpoint)
    if not status["available"]:
        return {
            "backend": "deterministic_fallback",
            "llm_available": False,
            "task_plan": parse_instruction(instruction).to_dict(),
            "disclosure": "Local Qwen is not running; deterministic validated parser used.",
        }
    prompt = """You are the semantic interpreter for a household robot. Return one JSON object only.
Schema: {"explanation":"one short Chinese sentence","steps":[{"action":"pick_and_place|place_near","object_id":"trash|keys|medicine","target_id":"trash_bin|tray|null","reference_id":"cup|null","constraints":[]}]}
Allowed tasks only: trash -> trash_bin using pick_and_place; keys -> tray using pick_and_place; medicine -> cup using place_near. If the user says not to touch the cup, add {"kind":"avoid_contact","object_id":"cup","minimum_clearance_m":0.10}. Never output coordinates, joint commands, code, or unsupported objects.
User request: """ + instruction
    body = json.dumps({
        "model": os.getenv("RADEONHOME_LLM_MODEL", DEFAULT_MODEL),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 96,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    raw_text = ""
    try:
        request = Request(endpoint, data=body, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - local endpoint
            reply = json.loads(response.read())
        raw_text = reply["choices"][0]["message"]["content"].strip()
        model_payload = _json_object(raw_text)
        plan = validated_task_plan(instruction, model_payload)
        explanation = str(model_payload.get("explanation", "已生成受约束的家庭任务计划。"))
        return {
            "backend": "local_qwen_validated_plan",
            "llm_available": True,
            "model": os.getenv("RADEONHOME_LLM_MODEL", DEFAULT_MODEL),
            "explanation": explanation,
            "plan_source": "qwen_json_accepted_by_allow_list",
            "task_plan": plan.to_dict(),
            "safety_boundary": "Qwen selects only allow-listed semantic tasks; deterministic validation, planning, and control remain authoritative.",
        }
    except (URLError, TimeoutError, OSError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        fallback = parse_instruction(instruction)
        return {
            "backend": "local_qwen_rejected_deterministic_fallback",
            "llm_available": True,
            "model": os.getenv("RADEONHOME_LLM_MODEL", DEFAULT_MODEL),
            "explanation": "Qwen output was rejected; the deterministic parser retained the safe task.",
            "plan_source": "deterministic_fallback_after_validation_failure",
            "validation_error": str(error),
            "raw_model_reply": raw_text,
            "task_plan": fallback.to_dict(),
            "safety_boundary": "Rejected model output never reaches navigation or robot control.",
        }
