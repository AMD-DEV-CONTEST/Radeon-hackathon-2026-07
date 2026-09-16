#!/usr/bin/env python3
"""Qwen-Image local inpainting / editing via ComfyUI (AMD ROCm).

Implements the "PS-style local repaint / text edit" workflow as a clean ComfyUI
API prompt graph, so a user can:
  1. upload an image + mask (or auto from region)
  2. describe the edit (e.g. change the text to "53297")
  3. get back an edited image

Then the edited image can feed straight into the I2V / R2V video modes to
complete the "edit image -> generate video" product loop.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

import numpy as np

from comfy_client import _http_json, API_BASE

EDIT_CHECKPOINT = "Qwen-Rapid-AIO-NSFW-v5.safetensors"
EDIT_LORA_MAIN = None  # optional LoRA filename in models/loras
EDIT_STEPS = 3
EDIT_CFG = 1.0
EDIT_SAMPLER = "lcm"
EDIT_SCHEDULER = "simple"

# Pruned-down defaults for InpaintCropImproved (keep it simple):
CROP_DEFAULTS = {
    "downscale_algorithm": "bilinear",
    "upscale_algorithm": "bicubic",
    "preresize": False,
    "preresize_mode": "ensure minimum resolution",
    "preresize_min_width": 1024,
    "preresize_min_height": 1024,
    "preresize_max_width": 16384,
    "preresize_max_height": 16384,
    "mask_fill_holes": True,
    "mask_expand_pixels": 1,
    "mask_invert": False,
    "mask_blend_pixels": 32,
    "mask_hipass_filter": 0.1,
    "extend_for_outpainting": False,
    "extend_up_factor": 1,
    "extend_down_factor": 1,
    "extend_left_factor": 1,
    "extend_right_factor": 1,
    "context_from_mask_extend_factor": 1.2,
    "output_resize_to_target_size": True,
    "output_target_width": 1024,
    "output_target_height": 1024,
    "output_padding": "16",
    "device_mode": "auto",
}


def _upload_image(img: np.ndarray, name: str) -> str:
    """Write an image into ComfyUI's input dir; return its filename."""
    from PIL import Image
    import os
    os.makedirs("/opt/ComfyUI/input", exist_ok=True)
    path = f"/opt/ComfyUI/input/{name}"
    Image.fromarray(img.astype(np.uint8)).save(path)
    return name


def _upload_mask(mask: np.ndarray, name: str) -> str:
    """Write a single-channel mask; return filename."""
    from PIL import Image
    import os
    os.makedirs("/opt/ComfyUI/input", exist_ok=True)
    path = f"/opt/ComfyUI/input/{name}"
    Image.fromarray(mask.astype(np.uint8)).save(path)
    return name


def build_edit_graph(
    image: np.ndarray,
    mask: np.ndarray,
    prompt_text: str,
    negative_prompt: str = "",
    seed: int = 502211856868836,
) -> dict:
    """Build the ComfyUI API prompt graph for Qwen-Image local editing.

    image: RGB uint8 array
    mask:  single-channel uint8 array (255 = edit region)
    prompt_text: instruction, e.g. '改为"53297"'
    """
    from PIL import Image

    img_name = _upload_image(image, "qwen_edit_image.png")
    mask_name = _upload_mask(mask, "qwen_edit_mask.png")

    crop = dict(CROP_DEFAULTS)
    crop["device_mode"] = "gpu (much faster)"

    graph = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": EDIT_CHECKPOINT}},
        "2": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "3": {"class_type": "LoadImage", "inputs": {"image": mask_name}},
        "4": {"class_type": "ImageToMask", "inputs": {"image": ["3", 0], "channel": "red"}},
        "5": {"class_type": "InpaintCropImproved", "inputs": {
            **crop,
            "image": ["2", 0],
            "mask": ["4", 0],
        }},
        "6": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
            "clip": ["1", 1], "prompt": prompt_text, "image1": ["5", 1],
        }},
        "7": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
            "clip": ["1", 1], "prompt": negative_prompt,
        }},
        "8": {"class_type": "InpaintModelConditioning", "inputs": {
            "positive": ["6", 0], "negative": ["7", 0], "vae": ["1", 2],
            "pixels": ["5", 1], "mask": ["5", 2], "noise_mask": True,
        }},
        "9": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 1], "vae": ["1", 2]}},
        "10": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["8", 0], "negative": ["8", 1],
            "latent_image": ["9", 0], "seed": seed, "steps": EDIT_STEPS,
            "cfg": EDIT_CFG, "sampler_name": EDIT_SAMPLER, "scheduler": EDIT_SCHEDULER,
            "denoise": 1.0,
        }},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["1", 2]}},
        "12": {"class_type": "InpaintStitchImproved", "inputs": {
            "stitcher": ["5", 0], "inpainted_image": ["11", 0],
        }},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "qwen_edit"}},
    }
    return graph


def run_edit(image, mask, prompt_text, negative_prompt="", seed=None, timeout=1200) -> dict:
    """One-shot: upload, queue, wait, return the edited image path."""
    seed = seed or 502211856868836
    graph = build_edit_graph(image, mask, prompt_text, negative_prompt, seed)
    pid = _http_json(f"{API_BASE}/prompt", {"prompt": graph}, timeout=30)["prompt_id"]
    start = time.time()
    while time.time() - start < timeout:
        try:
            history = _http_json(f"{API_BASE}/history/{pid}", timeout=30)
        except Exception:
            time.sleep(5)
            continue
        if pid in history:
            entry = history[pid]
            st = entry.get("status", {})
            outputs = entry.get("outputs", {})
            # SaveImage outputs go under node 13 -> "images"
            saved = []
            saved_paths = []
            for o in outputs.values():
                for im in o.get("images", []):
                    saved.append(im)
                    if im.get("type") == "output":
                        p = os.path.join("/opt/ComfyUI/output", im.get("subfolder", ""), im["filename"])
                        if os.path.exists(p):
                            saved_paths.append(p)
            return {
                "prompt_id": pid,
                "status": st.get("status_str"),
                "images": saved,
                "saved_paths": saved_paths,
            }
        time.sleep(5)
    raise TimeoutError(f"edit timed out after {timeout}s")
