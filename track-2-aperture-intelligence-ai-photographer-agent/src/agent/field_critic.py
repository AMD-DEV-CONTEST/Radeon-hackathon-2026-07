"""Critic contract for a grounded, field-executable photography plan."""

from __future__ import annotations

import re
from typing import Any

from src.agent.field_plan import PHOTO_PLAN_SCHEMA, shot_geometry_evidence


CRITIC_PROMPT = """Review the AI photographer's on-set guidance plan:
1. Does it explain why the reference photo works?
2. Does the photographer know the distance, angle, camera height, and background treatment?
3. Do the subjects know how to stand, move, and why each action helps?
4. Do angle, gaze, movement, or background instructions contradict one another?
5. Does the plan contain vague advice such as "adjust the camera" or "stand naturally"?
6. Is every avoid item grounded in a visible issue from the current image?
7. Are distance, height, and shooting angle physically consistent with framing and perspective evidence?
Return specific issues on failure. The Planner may revise the plan at most once."""


REQUIRED_ANALYSIS_FIELDS = (
    "scene",
    "subject",
    "environment",
    "relationship",
    "composition",
    "recommendation",
)

NESTED_SCHEMA = {
    "why_this_photo_works": (
        "atmosphere",
        "subject_environment_relationship",
        "composition_reason",
        "prop_usage",
    ),
    "photographer_instruction": (
        "distance",
        "angle",
        "height",
        "background_control",
        "avoid",
    ),
    "subject_instruction": (
        "body_pose",
        "head_direction",
        "eye_direction",
        "hand_action",
        "interaction",
    ),
    "advanced_parameters": ("lens", "lighting", "exposure"),
}

VAGUE_PHRASES = (
    "adjust the camera",
    "stand naturally",
    "keep it natural",
    "keep the head natural",
    "relax the body",
    "adjust the body",
    "adjust the gaze",
    "adjust the hands",
)

VISUAL_TERMS = (
    "subject", "person", "people", "crowd", "bystander", "background",
    "building", "banner", "glass", "reflection", "light", "head", "face",
    "hand", "foot", "feet", "frame edge", "graduation gown", "graduation cap",
    "phone", "tree", "sky",
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _missing_schema(plan: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if set(plan) != set(PHOTO_PLAN_SCHEMA):
        issues.append("Planner fields do not match the fixed schema.")
    if not _text(plan.get("photo_intent")):
        issues.append("The plan is missing a clear photo intent.")
    for section, fields in NESTED_SCHEMA.items():
        value = plan.get(section)
        if not isinstance(value, dict):
            issues.append(f"Missing structured section: {section}.")
            continue
        if set(value) != set(fields):
            issues.append(f"{section} does not match the fixed schema.")
        missing = [field for field in fields if not value.get(field)]
        if missing:
            issues.append(f"{section} is missing: {', '.join(missing)}.")
    sequence = plan.get("shooting_sequence")
    if not isinstance(sequence, list) or len(sequence) != 4 or not all(_text(item) for item in sequence):
        issues.append("The shooting sequence must contain four executable steps.")
    return issues


def _avoid_is_grounded(analysis: dict[str, Any], advice: str) -> bool:
    evidence = " ".join(
        _text(value)
        for value in (
            analysis.get("scene"),
            analysis.get("subject"),
            analysis.get("environment"),
            analysis.get("relationship"),
            analysis.get("composition"),
            " ".join(_text(item) for item in analysis.get("visible_props") or []),
            " ".join(_text(item) for item in analysis.get("visual_risks") or []),
        )
        if value
    )
    evidence_lower = evidence.lower()
    evidence_terms = {term for term in VISUAL_TERMS if term in evidence_lower}
    if analysis.get("people_boxes"):
        evidence_terms.update({"subject", "person", "people", "head", "face", "hand", "foot", "feet"})
    if any(analysis.get(field) for field in ("scene", "environment", "composition")):
        evidence_terms.update({"background", "frame edge"})
    if not evidence_terms and analysis.get("avoid_regions"):
        evidence_terms = {"background", "subject", "frame edge"}
    lowered_advice = advice.lower()
    lowered_advice = lowered_advice.replace("subjects", "subject").replace("people's", "people")
    return any(term in lowered_advice for term in evidence_terms)


def _minimum_distance_metres(value: str) -> float | None:
    numbers = re.findall(r"\d+(?:\.\d+)?", value)
    return min(map(float, numbers)) if numbers else None


class FieldPlanCritic:
    REQUIRED_ANALYSIS_FIELDS = REQUIRED_ANALYSIS_FIELDS
    CRITIC_PROMPT = CRITIC_PROMPT

    def review(self, analysis: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
        issues = _missing_schema(plan if isinstance(plan, dict) else {})
        missing_evidence = [field for field in self.REQUIRED_ANALYSIS_FIELDS if not analysis.get(field)]
        if missing_evidence:
            issues.append("Missing image evidence: " + ", ".join(missing_evidence) + ".")

        why = plan.get("why_this_photo_works") or {}
        if not all(len(_text(why.get(field))) >= 8 for field in NESTED_SCHEMA["why_this_photo_works"]):
            issues.append("The plan does not fully explain atmosphere, subject-environment relationship, composition, and prop use.")

        photographer = plan.get("photographer_instruction") or {}
        distance = _text(photographer.get("distance"))
        if not any(unit in distance.lower() for unit in ("meter", "metre", "step")):
            issues.append("The photographer distance must use meters or steps.")
        geometry = shot_geometry_evidence(analysis)
        height = _text(photographer.get("height"))
        angle = _text(photographer.get("angle"))
        if geometry["low_angle"]:
            if any(word in height.lower() for word in ("eye level", "near the eyes", "close to the subject's eye")):
                issues.append("The reference uses a low upward angle, but the plan recommends eye-level camera height.")
            if not any(word in angle.lower() for word in ("upward", "low angle", "aim up")):
                issues.append("The reference uses a low angle, but the plan does not tell the photographer to aim upward.")
        distance_metres = _minimum_distance_metres(distance)
        if (
            geometry["framing"] == "full_body"
            and geometry["environmental"]
            and distance_metres is not None
            and distance_metres < 2
        ):
            issues.append("The distance is too close for a full-body environmental portrait.")

        subject = plan.get("subject_instruction") or {}
        if not all(_text(subject.get(field)) for field in NESTED_SCHEMA["subject_instruction"]):
            issues.append("The subjects do not know how to stand, look, place their hands, or interact.")
        if not any(word in _text(subject.get("body_pose")).lower() for word in ("because", "so that", "to avoid", "which keeps", "so the")):
            issues.append("The body instruction does not explain why the action helps.")
        terse_actions = [
            field
            for field in ("body_pose", "head_direction", "eye_direction", "hand_action")
            if len(_text(subject.get(field)).split()) < 3
        ]
        if terse_actions:
            issues.append(
                "These subject instructions are too terse to perform: "
                + ", ".join(terse_actions)
                + "."
            )

        full_plan = " ".join(_text(value) for value in _flatten(plan)).lower()
        vague = sorted({phrase for phrase in VAGUE_PHRASES if phrase in full_plan})
        if vague:
            issues.append("The plan contains vague, non-executable advice: " + ", ".join(vague) + ".")

        background = _text(photographer.get("background_control"))
        intent = _text(plan.get("photo_intent"))
        if "environment" in intent.lower() and any(word in background.lower() for word in ("blur everything", "remove the environment")):
            issues.append("The intent preserves the environment, but the background instruction removes it.")

        avoid = photographer.get("avoid")
        if not isinstance(avoid, list) or len(avoid) < 2:
            issues.append("avoid must contain at least two visible failure risks from the current image.")
        else:
            ungrounded = [item for item in avoid[:2] if not _avoid_is_grounded(analysis, _text(item))]
            if ungrounded:
                issues.append("These avoid items are not grounded in the current image: " + "; ".join(map(_text, ungrounded)) + ".")

        return {
            "status": "pass" if not issues else "needs_review",
            "issues": issues,
            "checks_run": [
                "why the photo works",
                "executable distance, angle, height, and background control",
                "executable subject actions with reasons",
                "contradiction check",
                "vague-language check",
                "image-grounded avoid items",
                "physical consistency of framing and camera geometry",
            ],
        }


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, dict):
        flattened: list[Any] = []
        for item in value.values():
            flattened.extend(_flatten(item))
        return flattened
    if isinstance(value, list):
        flattened = []
        for item in value:
            flattened.extend(_flatten(item))
        return flattened
    return [value]
