#!/usr/bin/env python3
"""MiniMax H3 local generation client (ComfyUI API wrapper).

Runs open-weights MiniMax H3 (omni-modal text->video+audio) locally on
AMD Radeon GPUs via ComfyUI's native MiniMax H3 nodes.

Three generation modes are supported:
  - T2V: text -> video + stereo audio
  - I2V: text + first/last keyframe image(s) -> video + stereo audio
  - R2V: text + reference image(s) -> video + stereo audio
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import numpy as np

API_BASE = "http://127.0.0.1:8188"

DEFAULT_MODELS = {
    "unet": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    "video_vae": "minimax_h3_video_vae_fp16.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
}

SAMPLER = "res_multistep"
SCHEDULER = "simple"
STEPS = 20


def _http_json(url: str, data=None, timeout: int = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:2000]}") from e


def build_prompt(
    prompt: str,
    mode: str = "t2v",
    width: int = 864,
    height: int = 480,
    duration_s: float = 5.0,
    seed: int = 556589502035082,
    first_frame: np.ndarray | None = None,
    last_frame: np.ndarray | None = None,
    ref_images: list[np.ndarray] | None = None,
    models: dict | None = None,
    clip_name: str | None = None,
    unet_name: str | None = None,
) -> dict:
    """Build a ComfyUI API prompt graph for MiniMax H3 generation."""
    text = prompt
    m = {**DEFAULT_MODELS, **(models or {})}
    if clip_name:
        m["clip"] = clip_name
    if unet_name:
        m["unet"] = unet_name

    length = _align_length(duration_s)

    prompt = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": m["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["clip"], "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["video_vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": m["audio_vae"]}},
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": text,
            "width": width, "height": height, "length": length}},
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "7": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["5", 0]}},
        "8": {"class_type": "BasicScheduler", "inputs": {
            "model": ["1", 0], "scheduler": SCHEDULER, "steps": STEPS, "denoise": 1.0}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": SAMPLER}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["6", 0], "guider": ["7", 0], "sampler": ["9", 0],
            "sigmas": ["8", 0], "latent_image": ["5", 1]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {
            "images": ["11", 0], "audio": ["12", 0], "fps": 24, "bit_depth": 8}},
        "14": {"class_type": "SaveVideo", "inputs": {
            "video": ["13", 0], "filename_prefix": "video/MiniMax_H3", "format": "auto", "codec": "auto"}},
    }

    # --- mode-specific conditioning ---
    cond_node = "5"
    if mode in ("t2v", "i2v"):
        if first_frame is not None:
            im = _upload_image(first_frame, "first_frame.png")
            img_node = "20"
            prompt[img_node] = {"class_type": "LoadImage", "inputs": {"image": im}}
            prompt["5"]["inputs"]["first_frame"] = [img_node, 0]
        if last_frame is not None:
            im = _upload_image(last_frame, "last_frame.png")
            img_node = "21"
            prompt[img_node] = {"class_type": "LoadImage", "inputs": {"image": im}}
            prompt["5"]["inputs"]["last_frame"] = [img_node, 0]
    elif mode == "r2v":
        # Reference-to-video needs the ref2va model + R2V conditioning node.
        prompt["1"] = {"class_type": "UNETLoader", "inputs": {
            "unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}}
        ref_img_links = []
        for i, img in enumerate(ref_images or []):
            im = _upload_image(img, f"ref_{i}.png")
            img_node = f"30_{i}"
            prompt[img_node] = {"class_type": "LoadImage", "inputs": {"image": im}}
            ref_img_links.append([img_node, 0])
        prompt["5"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0], "prompt": text,
            "width": width, "height": height, "length": length, "ref_image_size": "match"}}
        if ref_img_links:
            prompt["5"]["inputs"]["ref_images"] = ref_img_links
        cond_node = "5"

    return prompt


def _align_length(duration_s: float) -> int:
    """Snap duration to the model's 17k+5 frame grid at 24 fps."""
    n = max(5, round(duration_s * 24))
    while n % 17 != 5:
        n += 1
    return n


def _upload_image(img: np.ndarray, name: str) -> str:
    """Upload an RGB numpy image to ComfyUI input dir, return its filename."""
    from PIL import Image
    import os
    os.makedirs("/opt/ComfyUI/input", exist_ok=True)
    path = f"/opt/ComfyUI/input/{name}"
    Image.fromarray(img.astype(np.uint8)).save(path)
    return name


def queue_and_wait(prompt: dict, timeout: int = 3600, progress_cb=None) -> dict:
    """Submit a prompt graph, poll history, return outputs.

    progress_cb(elapsed_s, status) is called every poll tick with the
    current elapsed time so callers can render a progress bar / ETA.
    """
    pid = _http_json(f"{API_BASE}/prompt", {"prompt": prompt}, timeout=30)["prompt_id"]
    start = time.time()
    while time.time() - start < timeout:
        elapsed = time.time() - start
        try:
            history = _http_json(f"{API_BASE}/history/{pid}", timeout=30)
        except Exception:
            if progress_cb:
                progress_cb(elapsed, "waiting for server")
            time.sleep(5)
            continue
        if pid in history:
            entry = history[pid]
            st = entry.get("status", {})
            return {
                "prompt_id": pid,
                "status": st.get("status_str"),
                "completed": st.get("completed"),
                "outputs": entry.get("outputs", {}),
            }
        if progress_cb:
            progress_cb(elapsed, "generating")
        time.sleep(5)
    raise TimeoutError(f"generation timed out after {timeout}s")


def generate(**kwargs) -> dict:
    """One-shot convenience: build prompt, queue, wait, return result."""
    progress_cb = kwargs.pop("progress_cb", None)
    prompt = build_prompt(**kwargs)
    return queue_and_wait(prompt, progress_cb=progress_cb)
