"""Quality presets. Draft uses the distilled Hunyuan3D-2mini-turbo DiT (0.6B),
standard/high use the full Hunyuan3D-2 DiT. Image sizes follow SDXL-Turbo's
sweet spots (512 at 1 step; 768 needs 4 steps to stay clean).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    # text -> image
    image_size: int
    image_steps: int
    # image -> shape
    shape_repo: str
    shape_subfolder: str
    shape_steps: int
    octree_resolution: int
    guidance_scale: float
    num_chunks: int
    # mesh post
    target_faces: int        # decimation target for the game-ready GLB
    print_target_faces: int  # decimation target for the print STL


PRESETS: dict[str, Preset] = {
    "draft": Preset(
        name="draft",
        image_size=512,
        image_steps=1,
        shape_repo="tencent/Hunyuan3D-2mini",
        shape_subfolder="hunyuan3d-dit-v2-mini-turbo",
        shape_steps=8,
        octree_resolution=256,
        guidance_scale=5.0,
        num_chunks=8000,
        target_faces=30_000,
        print_target_faces=150_000,
    ),
    "standard": Preset(
        name="standard",
        image_size=768,
        image_steps=4,
        shape_repo="tencent/Hunyuan3D-2",
        shape_subfolder="hunyuan3d-dit-v2-0",
        shape_steps=30,
        octree_resolution=384,
        guidance_scale=7.5,
        num_chunks=20_000,
        target_faces=60_000,
        print_target_faces=300_000,
    ),
    "high": Preset(
        name="high",
        image_size=1024,
        image_steps=4,
        shape_repo="tencent/Hunyuan3D-2",
        shape_subfolder="hunyuan3d-dit-v2-0",
        shape_steps=50,
        octree_resolution=512,
        guidance_scale=7.5,
        num_chunks=20_000,
        target_faces=120_000,
        print_target_faces=500_000,
    ),
}

# Style suffix appended to user prompts: Hunyuan3D wants a single centered
# object on a clean background, so we steer SDXL-Turbo toward that.
PROMPT_STYLE_SUFFIX = (
    ", single object, centered, 3/4 view, plain light gray background, "
    "studio product photo, sharp focus, no text, no watermark"
)

NEGATIVE_HINT = "blurry, cropped, multiple objects, busy background, text, watermark"

MATERIAL_PRESETS = {
    "clay":    {"baseColorFactor": [0.78, 0.55, 0.45, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9},
    "plastic": {"baseColorFactor": [0.85, 0.85, 0.88, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.35},
    "metal":   {"baseColorFactor": [0.83, 0.83, 0.85, 1.0], "metallicFactor": 1.0, "roughnessFactor": 0.4},
    "resin":   {"baseColorFactor": [0.45, 0.62, 0.78, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.2},
}
