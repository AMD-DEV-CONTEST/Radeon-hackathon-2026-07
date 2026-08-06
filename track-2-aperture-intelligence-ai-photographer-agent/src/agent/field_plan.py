"""Grounded, plain-language field plan contract for the photographer agent."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


PLANNER_PROMPT = """You are a professional photographer directing a real shoot.
Turn visual evidence into plain-English actions that an everyday user can perform immediately.
Explain why the photo works, how the photographer should control distance, angle, height, and background,
how the subjects should stand and interact, and how to prevent visible failure risks.
Do not replace actions with camera jargon. Reject vague instructions such as "adjust the camera" or "stand naturally."
Every avoid item must be grounded in the current image. Keep optional settings inside advanced_parameters.
Return exactly PHOTO_PLAN_SCHEMA without adding or omitting fields."""


PHOTO_PLAN_SCHEMA: dict[str, Any] = {
    "photo_intent": "",
    "why_this_photo_works": {
        "atmosphere": "",
        "subject_environment_relationship": "",
        "composition_reason": "",
        "prop_usage": "",
    },
    "photographer_instruction": {
        "distance": "",
        "angle": "",
        "height": "",
        "background_control": "",
        "avoid": ["", ""],
    },
    "subject_instruction": {
        "body_pose": "",
        "head_direction": "",
        "eye_direction": "",
        "hand_action": "",
        "interaction": "",
    },
    "shooting_sequence": ["", "", "", ""],
    "advanced_parameters": {
        "lens": "",
        "lighting": "",
        "exposure": "",
    },
}


def _text(value: Any, fallback: str = "") -> str:
    return " ".join(str(value or fallback).strip().split())


def _explanation(value: Any, fallback: str) -> str:
    """Turn a terse VLM label into a complete user-facing explanation."""
    text = _text(value)
    if len(text) >= 8:
        return text
    if text:
        return f"{text} sets the visual foundation. {fallback}"
    return fallback


def _context(analysis: dict[str, Any]) -> str:
    values: list[Any] = [
        analysis.get("scene"),
        analysis.get("subject"),
        analysis.get("environment"),
        analysis.get("relationship"),
        analysis.get("composition"),
        analysis.get("recommendation"),
    ]
    values.extend(analysis.get("visible_props") or [])
    return " ".join(_text(value).lower() for value in values if value)


def _flags(analysis: dict[str, Any]) -> dict[str, Any]:
    context = _context(analysis)
    local_geometry = analysis.get("_local_person_geometry")
    local_geometry = (
        local_geometry if isinstance(local_geometry, dict) else {}
    )
    people_count = int(
        local_geometry.get("people_count")
        or len(analysis.get("people_boxes") or [])
    )
    visible_props = " ".join(
        _text(item).lower() for item in analysis.get("visible_props") or []
    )
    return {
        "context": context,
        "people_count": people_count,
        "group": people_count >= 2,
        "graduation": any(word in context for word in ("graduation", "graduation gown", "mortarboard", "academic gown")),
        "family": any(word in context for word in ("family", "child", "parent", "mother", "father")),
        "couple": any(word in context for word in ("couple", "partner", "spouse")),
        "city": any(word in context for word in ("city", "street", "building", "glass facade", "urban")),
        "night": any(word in context for word in ("night", "evening", "neon", "street light")),
        "phone": any(
            word in visible_props for word in ("phone", "smartphone", "mobile")
        ),
    }


def shot_geometry_evidence(analysis: dict[str, Any]) -> dict[str, Any]:
    """Combine VLM categories with deterministic person-box measurements."""
    raw = analysis.get("shot_geometry")
    raw = raw if isinstance(raw, dict) else {}
    local = analysis.get("_local_person_geometry")
    local = local if isinstance(local, dict) else {}
    context = _context(analysis)
    boxes = analysis.get("people_boxes") or []
    largest_height = max(
        (
            max(0, int(box[3]) - int(box[1])) / 1000
            for box in boxes
            if isinstance(box, (list, tuple)) and len(box) == 4
        ),
        default=0.0,
    )
    framing = _text(raw.get("framing")).lower()
    if framing not in {
        "full_body", "three_quarter", "half_body", "closeup", "unknown"
    }:
        framing = "unknown"
    if any(word in context for word in ("full body", "head to toe", "feet visible")):
        framing = "full_body"
    elif local.get("full_body_candidate") is True:
        framing = "full_body"
    elif framing == "unknown" and largest_height >= 0.72 and any(
        word in context for word in ("legs", "feet", "shoes", "skirt")
    ):
        framing = "full_body"

    camera_height = _text(raw.get("camera_height")).lower()
    camera_tilt = _text(raw.get("camera_tilt")).lower()
    low_terms = (
        "low angle", "ground level", "upward", "camera near the ground",
    )
    explicit_low_angle = (
        camera_tilt == "up"
        or any(term in context for term in low_terms)
    )
    compatible_low_category = (
        framing == "full_body"
        and camera_height in {"ground", "knee", "waist"}
        and camera_tilt != "down"
    )
    low_angle = explicit_low_angle or compatible_low_category
    environmental = any(
        word in context
        for word in (
            "sky", "mountain", "sea", "environment", "open space",
            "building", "street", "landscape",
        )
    )
    return {
        "framing": framing,
        "camera_height": camera_height or "unknown",
        "camera_tilt": camera_tilt or "unknown",
        "subject_frame_height_ratio": largest_height,
        "local_person_height_ratio": float(
            local.get("largest_height_ratio") or 0.0
        ),
        "local_person_aspect_ratio": float(
            local.get("largest_aspect_ratio") or 0.0
        ),
        "low_angle": low_angle,
        "environmental": environmental,
    }


def _group_name(count: int) -> str:
    return {2: "two people", 3: "three people", 4: "four people"}.get(count, f"{count} people")


def _prop_names(analysis: dict[str, Any]) -> list[str]:
    """Exclude worn clothing from the user-facing handheld/interactive prop list."""
    clothing_terms = (
        "shirt", "t-shirt", "pants", "trousers", "skirt", "belt", "shoes",
        "socks", "jacket", "coat", "clothes", "top", "dress", "outfit",
        "tie", "bow tie", "watch",
    )
    thematic_exceptions = ("graduation gown", "academic gown", "mortarboard", "graduation cap")
    props: list[str] = []
    for item in analysis.get("visible_props") or []:
        text = _text(item)
        lowered = text.lower()
        if not text:
            continue
        if any(term in lowered for term in thematic_exceptions):
            props.append(text)
            continue
        if any(term in lowered for term in clothing_terms):
            continue
        props.append(text)
    return props


def _why(analysis: dict[str, Any], flags: dict[str, Any]) -> dict[str, str]:
    atmosphere = _explanation(
        analysis.get("scene"),
        "The real environment gives the photo a clear sense of place.",
    )
    relationship = _explanation(
        analysis.get("relationship"),
        "The subject remains the visual focus while the environment carries the story.",
    )
    composition = _explanation(
        analysis.get("composition"),
        "The subject is easy to read while the frame retains environmental depth.",
    )
    props = ", ".join(_prop_names(analysis))
    prop_usage = (
        f"{props} gives the hands a natural task and reduces the posed feeling."
        if props
        else "No extra prop is needed; a simple hand position keeps attention on the person."
    )

    if flags["graduation"]:
        name = _group_name(flags["people_count"])
        atmosphere = "The graduation setting and congratulatory banner give the image a clear commemorative purpose."
        relationship = f"The {name} form the visual center while the entrance and banner establish the graduation story."
        composition = f"The {name} create a stable central group, with enough architecture to keep the portrait spacious."
        prop_usage = "The graduation clothing and banner already communicate the theme, so the hands do not need another prop."
    elif flags["group"]:
        name = _group_name(flags["people_count"])
        relationship = f"The {name} stand close enough to form one visual center while the environment establishes the meeting place."
        composition = f"Small differences in spacing and height keep the {name} balanced without making the group rigid."
        prop_usage = (
            f"Use {props} only to support the interaction; do not let it block anyone's face or hands."
            if props
            else "No extra prop is needed; build the relationship through closer spacing and natural interaction."
        )
    elif flags["city"] and flags["night"]:
        atmosphere = "City lights and reflections create a candid street-photography mood."
        relationship = "The subject remains the visual center while the city provides a lived-in narrative background."
        composition = "A slightly angled half-body frame emphasizes expression while preserving urban depth."
        if flags["phone"]:
            prop_usage = "The phone gives the subject a natural action and makes the moment feel candid."

    return {
        "atmosphere": atmosphere,
        "subject_environment_relationship": relationship,
        "composition_reason": composition,
        "prop_usage": prop_usage,
    }


RISK_OBJECTS = (
    "subject", "person", "people", "bystander", "crowd", "background",
    "building", "banner", "glass", "reflection", "light", "head", "face",
    "hand", "foot", "feet", "frame edge", "phone", "tree", "sky",
)


def _avoid(analysis: dict[str, Any], flags: dict[str, Any]) -> list[str]:
    risks = [
        _text(item)
        for item in analysis.get("visual_risks") or []
        if _text(item) and any(term in _text(item) for term in RISK_OBJECTS)
    ]
    if flags["graduation"]:
        defaults = [
            "Keep background pedestrians from appearing between the three subjects.",
            "Keep the banner and building lines from crossing anyone's head.",
        ]
    elif flags["group"]:
        defaults = [
            "Do not let subjects block one another's faces or hands.",
            "Keep background clutter from intersecting anyone's head.",
        ]
    elif flags["city"]:
        defaults = [
            "Keep background pedestrians away from the subject's outline.",
            "Keep architectural lines from crossing the subject's head.",
        ]
    else:
        defaults = [
            "Keep background clutter from overlapping the subject's head.",
            "Keep both hands visible instead of hiding them behind the body or frame edge.",
        ]
    grounded = [
        risk if risk.lower().startswith(("avoid", "keep", "do not", "don't")) else f"Avoid {risk.rstrip('.')}."
        for risk in risks
    ]
    for fallback in defaults:
        if fallback not in grounded:
            grounded.append(fallback)
    return grounded[:2]


def _photographer(analysis: dict[str, Any], flags: dict[str, Any]) -> dict[str, Any]:
    raw = analysis.get("photographer") or {}
    geometry = shot_geometry_evidence(analysis)
    distance = _text(raw.get("distance"), "About 2 meters")
    angle = _text(raw.get("angle"), "Keep the camera level and preserve the subject-environment relationship")
    height = _text(raw.get("height"), "Close to the subject's eye level")
    background = _text(raw.get("background"), "Preserve environmental depth and exclude unrelated bystanders")

    if angle.lower() in {"level", "straight", "front", "front view"}:
        angle = "Keep the camera level and use a slight side angle instead of a flat ID-photo view"
    if height.lower() in {"waist", "chest", "shoulder", "head", "eye"}:
        height = f"Keep the camera near the subject's {height.lower()} level"

    if (
        not geometry["low_angle"]
        and any(unit in height.lower() for unit in ("meter", "metre"))
        and not any(word in height.lower() for word in ("eye", "chest", "shoulder", "waist", "knee", "ground"))
    ):
        height = "Close to the subject's eye level"
    if flags["group"]:
        distance = "About 2 to 3 meters"
        angle = "Keep the camera level so every person remains clearly visible"
        height = "Close to the center subject's eye level"
        background = "Preserve the setting while keeping unrelated pedestrians out of the group"
    elif geometry["framing"] in {"half_body", "closeup"} and not geometry["low_angle"]:
        distance = "About 1.5 to 2 meters"
        height = "Close to the subject's eye level"
        if flags["city"]:
            background = "Preserve the urban depth while keeping pedestrians clear of the subject's outline"
    elif geometry["framing"] == "three_quarter" and not geometry["low_angle"]:
        distance = "About 2 to 3 meters"
        height = "Between the subject's chest and eye level"
    if geometry["framing"] == "full_body":
        ratio = geometry["subject_frame_height_ratio"]
        if flags["group"]:
            distance = "About 4 to 6 meters"
        elif geometry["environmental"] and ratio <= 0.8:
            distance = "About 3 to 4 meters"
        else:
            distance = "About 2.5 to 3 meters"
    if geometry["low_angle"]:
        angle = "Aim the camera slightly upward"
        height = {
            "ground": "Place the camera near the ground and aim upward",
            "knee": "Lower the camera near knee height and aim slightly upward",
            "waist": "Keep the camera below waist height and aim slightly upward",
        }.get(
            geometry["camera_height"],
            "Lower the camera below knee height and aim slightly upward",
        )
        if "sky" in flags["context"]:
            background = "Keep the open sky above the subject and leave space at the top of the frame"
    if flags["graduation"]:
        background = "Keep the graduation banner and building entrance readable"

    return {
        "distance": distance,
        "angle": angle,
        "height": height,
        "background_control": background,
        "avoid": _avoid(analysis, flags),
    }


def _subject(analysis: dict[str, Any], flags: dict[str, Any]) -> dict[str, str]:
    body = analysis.get("body_pose") or {}
    hands = analysis.get("hands") or {}
    gaze = analysis.get("gaze") or {}
    body_pose = _text(body.get("body_rotation"), "Turn the body slightly toward the photographer")
    head = _text(body.get("head_direction"), "Turn the head gently toward the photographer")
    eyes = _text(gaze.get("direction"), "Look naturally toward the photographer")
    hand_action = _text(hands.get("position"), "Give both hands a simple task instead of letting them hang stiffly")
    interaction = "Make one small movement and pause so the photographer can capture the action as it happens."

    claimed_object = _text(hands.get("object")).lower()
    visible_prop_text = " ".join(
        _text(item).lower() for item in analysis.get("visible_props") or []
    )
    if claimed_object and claimed_object not in {"none", "no prop", "no visible prop", "hands"}:
        object_tokens = [token for token in claimed_object.split() if len(token) > 2]
        if object_tokens and not any(token in visible_prop_text for token in object_tokens):
            hand_action = "Give the hands a simple resting place at the sides or behind the body."

    if len(body_pose.split()) < 3 or body_pose.lower() in {"stand straight", "stand naturally", "relax the body", "relax the shoulders"}:
        body_pose = "Turn the body slightly toward the photographer to avoid a stiff ID-photo pose."
    elif not any(word in body_pose.lower() for word in ("because", "so that", "to avoid", "which keeps")):
        body_pose += " so the body line feels less rigid."
    if len(head.split()) < 3 or head.lower() in {"face the camera", "look at the camera", "keep the head natural"}:
        head = "Turn the head gently toward the photographer without forcing the pose."
    if len(eyes.split()) < 3 or eyes.lower() in {"face the camera", "look at the camera", "stare at the camera"}:
        eyes = "Look outside the frame first, then glance back toward the photographer."
    if flags["phone"]:
        hand_action = "Hold the phone naturally near the waist instead of presenting it to the camera."
        interaction = "Look up as if you have just finished checking the phone while the photographer captures the glance in a short burst."
    if flags["group"]:
        name = _group_name(flags["people_count"])
        body_pose = f"Bring the {name} close together and face the photographer so the group reads as one unit."
        head = "Lower each chin slightly and face the photographer without tilting everyone the same way."
        eyes = "Have everyone look toward the photographer at the same moment."
        hand_action = "Rest hands in front or at the sides; do not cross arms or block the person next to you."
        interaction = "Settle the group first, then prompt one another to relax while the photographer captures the shared smile."
    if flags["family"]:
        body_pose = "Stagger the adult and child slightly and turn them toward each other to avoid a lineup pose."
        head = "Have the adult look gently toward the child, then let the child look up in response."
        eyes = "Look at each other first, then look forward together."
        hand_action = "Hold hands naturally and keep the free hands relaxed."
        interaction = "Walk three to five slow steps together so the photographer can capture changing eye contact and movement."

    return {
        "body_pose": body_pose,
        "head_direction": head,
        "eye_direction": eyes,
        "hand_action": hand_action,
        "interaction": interaction,
    }


def _intent(flags: dict[str, Any]) -> str:
    if flags["graduation"]:
        return "Preserve the graduation setting and relationships in a commemorative group portrait that feels formal, not rigid."
    if flags["family"]:
        return "Preserve the family relationship and real setting through natural interaction rather than a lineup pose."
    if flags["group"]:
        return "Keep every person clearly visible while preserving the atmosphere of the gathering."
    if flags["city"]:
        return "Preserve the subject's relationship with the city and create a natural portrait with a clear sense of story."
    return "Highlight the subject's real state while using the environment to show where the moment takes place."


def _sequence(flags: dict[str, Any]) -> list[str]:
    if flags["group"]:
        return [
            "Confirm the distance and camera height, then check that every person is fully in frame.",
            "Bring the group closer and align their gaze and arm positions.",
            "Capture one safe frame with every subject and the setting clearly visible.",
            "Shoot a short burst as the group relaxes into a shared smile.",
        ]
    return [
        "Confirm the distance and camera height, then check the subject against the background.",
        "Set the body, hands, and gaze from the labels and make sure each action is comfortable.",
        "Capture one safe frame with both the subject and environment clearly visible.",
        "Ask for one small movement and shoot a short burst to catch the most natural moment.",
    ]


def _advanced(flags: dict[str, Any]) -> dict[str, str]:
    lens = "Start with the phone's 1x camera to include the setting; use 2x only if the subject appears too small."
    if flags["group"]:
        lens = "Use the phone's 1x camera and avoid standing too close, which can distort people at the edges."
    lighting = "Keep the main light toward the subjects' front or side so faces do not split into bright and dark halves."
    if flags["night"]:
        lighting = "Move the subject toward stable ambient light instead of relying only on a harsh overhead source."
    return {
        "lens": lens,
        "lighting": lighting,
        "exposure": "Keep faces clear without blowing out highlights, then preserve the important background details.",
    }


def build_field_plan(
    analysis: dict[str, Any],
    user_request: str,
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build exactly the public schema; intent remains outside this object."""
    del user_request, intent
    flags = _flags(analysis)
    return {
        "photo_intent": _intent(flags),
        "why_this_photo_works": _why(analysis, flags),
        "photographer_instruction": _photographer(analysis, flags),
        "subject_instruction": _subject(analysis, flags),
        "shooting_sequence": _sequence(flags),
        "advanced_parameters": _advanced(flags),
    }


def refine_field_plan(
    plan: dict[str, Any],
    issues: list[str],
    *,
    analysis: dict[str, Any],
    user_request: str,
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One bounded repair: replace only missing/invalid sections from evidence."""
    baseline = build_field_plan(analysis, user_request, intent)
    revised = deepcopy(plan) if isinstance(plan, dict) else {}
    for section, expected in baseline.items():
        current = revised.get(section)
        if isinstance(expected, dict):
            current = current if isinstance(current, dict) else {}
            revised[section] = {
                field: current.get(field) or fallback
                for field, fallback in expected.items()
            }
        elif isinstance(expected, list):
            revised[section] = current if isinstance(current, list) and len(current) >= len(expected) else expected
        else:
            revised[section] = current or expected
    if any(
        phrase in " ".join(issues)
        for phrase in ("camera height", "low angle", "full-body environmental portrait", "distance too close", "shooting angle")
    ):
        revised["photographer_instruction"] = baseline[
            "photographer_instruction"
        ]
    return {key: revised[key] for key in PHOTO_PLAN_SCHEMA}
