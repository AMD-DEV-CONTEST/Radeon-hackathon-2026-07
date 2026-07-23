"""
LTX Video image-to-video payload builder for Replicate.

Instead of patching a ComfyUI node graph, we build the JSON input payload
for Replicate's lightricks/ltx-video model. The payload structure matches
the model's input schema on Replicate:

    image  — data URI or public URL of the source frame
    prompt — text description of desired motion/content
    num_frames, fps — timing parameters
    width, height — output resolution (LTX requires 32n+1 dimensions)
    seed — reproducibility seed
"""

import base64
from pathlib import Path
from typing import Optional

from app.core.config import settings


class WorkflowTemplateMissing(Exception):
    """No longer used but kept for backward-compat imports."""


def build_i2v_payload(
    *,
    image_path: Path,
    full_prompt: str,
    width: int,
    height: int,
    frame_count: int,
    frame_rate: int,
    seed: int,
    negative_prompt: str = "blurry, low quality, distorted, watermark, text overlay",
) -> dict:
    """
    Build the Replicate prediction input for lightricks/ltx-video.

    Returns a dict ready to pass as the `input` field of a Replicate
    POST /predictions request. The image is encoded as a data URI.
    """
    # Encode the source image as a base64 data URI so Replicate can
    # consume it directly from the JSON payload.
    mime = "image/png"
    suffix = image_path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    image_data_uri = f"data:{mime};base64,{b64}"

    payload: dict = {
        "image": image_data_uri,
        "prompt": full_prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "num_frames": frame_count,
        "fps": frame_rate,
        "seed": seed,
    }

    return payload


def get_model_id() -> str:
    """Return the Replicate model ID from settings."""
    return settings.REPLICATE_MODEL
