"""Normalize VLM photography directions into a stable execution-card schema."""

from __future__ import annotations

from typing import Any


POSE_SCHEMA = {
    "body_pose": ("body_rotation", "shoulder", "head_direction"),
    "hands": ("object", "position"),
    "gaze": ("direction", "expression"),
    "photographer": (
        "distance",
        "angle",
        "height",
        "background",
        "purpose",
    ),
}


def _text(value: Any, *, limit: int = 160) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit]


def normalize_pose_fields(value: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Keep only declared nested string fields from untrusted model JSON."""
    normalized: dict[str, dict[str, str]] = {}
    for section, fields in POSE_SCHEMA.items():
        raw = value.get(section)
        raw = raw if isinstance(raw, dict) else {}
        normalized[section] = {field: _text(raw.get(field)) for field in fields}
    return normalized


def pose_schema_complete(value: dict[str, Any]) -> bool:
    normalized = normalize_pose_fields(value)
    return all(
        normalized[section][field]
        for section, fields in POSE_SCHEMA.items()
        for field in fields
    )


class PoseAnalyzer:
    """Build the renderer contract without making an image-generation call."""

    @staticmethod
    def _action(analysis: dict[str, Any], anchor: str) -> str:
        for label in analysis.get("action_labels") or []:
            if isinstance(label, dict) and label.get("anchor") == anchor:
                text = _text(label.get("text"))
                if text:
                    return text
        return ""

    @staticmethod
    def _prop_role(props: list[str]) -> str:
        joined = ", ".join(props)
        lowered = joined.lower()
        roles: list[str] = []
        if any(word in lowered for word in ("phone", "smartphone", "mobile")):
            roles.append("The phone gives the hands a natural task and reduces the posed feeling")
        if any(
            word in lowered
            for word in ("backpack", "bag", "luggage", "suitcase")
        ):
            roles.append("The personal item reinforces a travel or city-story context")
        return "; ".join(roles) or (
            joined + " gives the subject a natural action" if joined else "No prop is required"
        )

    def build(
        self,
        analysis: dict[str, Any],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        pose = normalize_pose_fields(analysis)
        subject_plan = plan.get("subject_instruction") or {}
        camera_plan = plan.get("photographer_instruction") or {}
        why_plan = plan.get("why_this_photo_works") or {}
        raw_complete = pose_schema_complete(analysis)

        pose["body_pose"]["body_rotation"] = (
            _text(subject_plan.get("body_pose"))
            or pose["body_pose"]["body_rotation"]
            or self._action(analysis, "body")
        )
        pose["body_pose"]["shoulder"] = "Lower both shoulders slightly instead of lifting them toward the ears"
        pose["body_pose"]["head_direction"] = (
            _text(subject_plan.get("head_direction"))
            or pose["body_pose"]["head_direction"]
            or self._action(analysis, "head")
        )
        pose["hands"]["object"] = (
            pose["hands"]["object"]
            or _text(", ".join(analysis.get("visible_props") or []))
            or "No visible prop"
        )
        pose["hands"]["position"] = (
            _text(subject_plan.get("hand_action"))
            or pose["hands"]["position"]
            or self._action(analysis, "hands")
        )
        pose["gaze"]["direction"] = (
            _text(subject_plan.get("eye_direction"))
            or pose["gaze"]["direction"]
            or self._action(analysis, "head")
        )
        pose["gaze"]["expression"] = (
            _text(subject_plan.get("interaction"))
            or pose["gaze"]["expression"]
        )
        pose["photographer"]["distance"] = (
            _text(camera_plan.get("distance"))
            or pose["photographer"]["distance"]
        )
        pose["photographer"]["angle"] = (
            _text(camera_plan.get("angle"))
            or pose["photographer"]["angle"]
            or "Keep the camera level"
        )
        pose["photographer"]["height"] = (
            _text(camera_plan.get("height"))
            or pose["photographer"]["height"]
        )
        pose["photographer"]["background"] = (
            _text(camera_plan.get("background_control"))
            or pose["photographer"]["background"]
            or _text(analysis.get("composition"))
        )
        pose["photographer"]["purpose"] = (
            _text(plan.get("photo_intent"))
            or pose["photographer"]["purpose"]
            or _text(analysis.get("relationship"))
        )

        return {
            **pose,
            "why_beautiful": {
                "atmosphere": _text(
                    why_plan.get("atmosphere") or analysis.get("scene"), limit=140
                ),
                "relationship": _text(
                    why_plan.get("subject_environment_relationship")
                    or analysis.get("relationship"),
                    limit=140,
                ),
                "composition": _text(
                    why_plan.get("composition_reason")
                    or analysis.get("composition"),
                    limit=140,
                ),
                "prop_role": _text(
                    why_plan.get("prop_usage")
                    or self._prop_role(analysis.get("visible_props") or []),
                    limit=140,
                ),
            },
            "source": "planner+vlm" if raw_complete else "planner+vlm_fallback",
        }
