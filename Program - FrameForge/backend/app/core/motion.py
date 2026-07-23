"""
Motion presets -- describe the desired camera movement in natural language.

When driving a remote API (like Replicate's LTX Video), camera-motion LoRAs
are not directly可控. Instead we encode the desired motion as prompt text
that the model will follow.
"""

MOTION_PRESETS = {
    "static": {
        "label": "Static (no camera motion)",
        "prompt_fragment": "camera remains completely still, locked-off shot, no camera movement",
    },
    "dolly_in": {
        "label": "Dolly In",
        "prompt_fragment": "camera slowly dollies forward toward the subject, smooth push-in",
    },
    "dolly_out": {
        "label": "Dolly Out",
        "prompt_fragment": "camera slowly dollies backward away from the subject, smooth pull-out",
    },
    "dolly_left": {
        "label": "Dolly Left",
        "prompt_fragment": "camera dollies smoothly to the left, subject stays framed",
    },
    "dolly_right": {
        "label": "Dolly Right",
        "prompt_fragment": "camera dollies smoothly to the right, subject stays framed",
    },
    "jib_up": {
        "label": "Jib Up",
        "prompt_fragment": "camera rises smoothly on a jib, revealing more of the scene from above",
    },
    "jib_down": {
        "label": "Jib Down",
        "prompt_fragment": "camera descends smoothly on a jib, moving closer to ground level",
    },
    "orbit": {
        "label": "Orbit",
        "prompt_fragment": "camera slowly orbits around the subject, maintaining consistent framing",
    },
    "handheld": {
        "label": "Handheld",
        "prompt_fragment": "subtle handheld camera sway, natural documentary-style motion",
    },
    "custom": {
        "label": "Custom (write your own)",
        "prompt_fragment": "",
    },
}


def list_presets() -> list[dict]:
    """For the frontend's preset picker -- id + label + short preview text."""
    return [
        {"id": key, "label": preset["label"], "prompt_fragment": preset["prompt_fragment"]}
        for key, preset in MOTION_PRESETS.items()
    ]


def build_motion_prompt(
    preset_id: str,
    subject_prompt: str,
    custom_motion_prompt: str = "",
) -> dict:
    """
    Returns {full_prompt, uses_lora}.
    Raises KeyError if preset_id is unrecognized.
    """
    preset = MOTION_PRESETS[preset_id]

    motion_fragment = preset["prompt_fragment"]

    if preset_id == "custom":
        motion_fragment = custom_motion_prompt.strip()

    subject = subject_prompt.strip().rstrip(".")
    full_prompt = f"{subject}. {motion_fragment}." if motion_fragment else f"{subject}."

    return {
        "full_prompt": full_prompt,
        "uses_lora": False,
    }
