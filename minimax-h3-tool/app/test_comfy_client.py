#!/usr/bin/env python3
"""Unit tests for the MiniMax H3 client (no GPU / no ComfyUI server required).

Run:
    python -m pytest app/test_comfy_client.py -v
    # or without pytest:
    python app/test_comfy_client.py
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from comfy_client import build_prompt, _align_length, DEFAULT_MODELS, STEPS, SAMPLER, SCHEDULER

MODES = ("t2v", "i2v", "r2v")
IMG = np.zeros((480, 864, 3), dtype=np.uint8)


def _base_kwargs(mode):
    kw = dict(prompt="test", mode=mode, width=864, height=480, duration_s=5.0, seed=42)
    if mode == "i2v":
        kw["first_frame"] = IMG
        kw["last_frame"] = IMG
    if mode == "r2v":
        kw["ref_images"] = [IMG]
    return kw


def test_align_length_grid():
    assert _align_length(2.0) == 56      # 48->56 (17k+5)
    assert _align_length(5.0) == 124     # 120->124
    assert _align_length(10.0) == 243    # 240->243 (17*14=238, +5)
    assert _align_length(0.1) == 5       # floor at 5
    for d in (1.0, 3.5, 7.0, 15.0):
        n = _align_length(d)
        assert n % 17 == 5, f"duration {d} -> {n} not on 17k+5 grid"


def test_build_all_modes():
    for mode in MODES:
        g = build_prompt(**_base_kwargs(mode))
        assert "1" in g and "5" in g and "14" in g
        assert g["5"]["inputs"]["width"] == 864
        assert g["5"]["inputs"]["height"] == 480
        assert g["5"]["inputs"]["length"] == 124
        # every node class present
        for n in g.values():
            assert n.get("class_type"), f"missing class_type in {n}"


def test_t2v_graph_structure():
    g = build_prompt(**_base_kwargs("t2v"))
    assert g["1"]["class_type"] == "UNETLoader"
    assert g["1"]["inputs"]["unet_name"] == DEFAULT_MODELS["unet"]
    assert g["2"]["class_type"] == "CLIPLoader"
    assert g["2"]["inputs"]["clip_name"] == DEFAULT_MODELS["clip"]
    assert g["2"]["inputs"]["type"] == "minimax"
    assert g["5"]["class_type"] == "MiniMaxH3ImageToVideo"
    # no image conditioning for pure T2V
    assert "first_frame" not in g["5"]["inputs"]
    assert "last_frame" not in g["5"]["inputs"]
    # sampler/scheduler wiring
    assert g["8"]["inputs"]["scheduler"] == SCHEDULER
    assert g["8"]["inputs"]["steps"] == STEPS
    assert g["9"]["inputs"]["sampler_name"] == SAMPLER
    # audio path present
    assert g["12"]["class_type"] == "VAEDecodeAudio"
    assert g["13"]["class_type"] == "CreateVideo"
    assert g["13"]["inputs"]["fps"] == 24


def test_i2v_wires_keyframes():
    g = build_prompt(**_base_kwargs("i2v"))
    assert g["5"]["class_type"] == "MiniMaxH3ImageToVideo"
    assert g["5"]["inputs"]["first_frame"] == ["20", 0]
    assert g["5"]["inputs"]["last_frame"] == ["21", 0]
    assert g["20"]["class_type"] == "LoadImage"
    assert g["21"]["class_type"] == "LoadImage"


def test_r2v_wires_refs_and_model():
    g = build_prompt(**_base_kwargs("r2v"))
    assert g["5"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert g["5"]["inputs"]["audio_vae"] == ["4", 0]
    assert g["5"]["inputs"]["ref_image_size"] == "match"
    # ref images are a list of node links
    assert g["5"]["inputs"]["ref_images"] == [["30_0", 0]]
    assert g["30_0"]["class_type"] == "LoadImage"
    # ref2va model is used
    assert g["1"]["inputs"]["unet_name"] == "minimax_h3_ref2va_pruned_int8_convrot.safetensors"


def test_prompt_text_not_circular():
    # regression: build_prompt must not embed the graph into itself
    g = build_prompt(**_base_kwargs("r2v"))
    import json
    json.dumps(g)  # raises if circular


def test_clip_and_unet_override():
    kw = _base_kwargs("t2v")
    kw["clip_name"] = "other_clip.safetensors"
    kw["unet_name"] = "other_unet.safetensors"
    g = build_prompt(**kw)
    assert g["1"]["inputs"]["unet_name"] == "other_unet.safetensors"
    assert g["2"]["inputs"]["clip_name"] == "other_clip.safetensors"


def test_r2v_multiple_refs():
    kw = _base_kwargs("r2v")
    kw["ref_images"] = [IMG, IMG, IMG]
    g = build_prompt(**kw)
    assert len(g["5"]["inputs"]["ref_images"]) == 3
    assert g["30_2"]["class_type"] == "LoadImage"


def test_image_editor_graph():
    from image_editor import build_edit_graph
    import json
    img = np.zeros((512, 512, 3), dtype=np.uint8)
    mask = np.zeros((512, 512), dtype=np.uint8)
    mask[100:200, 100:200] = 255
    g = build_edit_graph(img, mask, '改为 "53297"')
    json.dumps(g)  # no circular reference
    assert g["5"]["class_type"] == "InpaintCropImproved"
    assert g["6"]["class_type"] == "TextEncodeQwenImageEditPlus"
    assert g["12"]["class_type"] == "InpaintStitchImproved"
    assert g["5"]["inputs"]["device_mode"] == "gpu (much faster)"
    # checkpoint must be the Qwen edit model
    assert "Qwen-Rapid-AIO-NSFW-v5" in g["1"]["inputs"]["ckpt_name"]


def test_image_editor_mask_conversion():
    from image_editor import build_edit_graph
    img = np.zeros((256, 256, 3), dtype=np.uint8)
    mask = np.zeros((256, 256), dtype=np.uint8)
    mask[50:80, 50:80] = 255
    g = build_edit_graph(img, mask, "edit")
    # ImageToMask node converts IMAGE -> MASK
    assert g["4"]["class_type"] == "ImageToMask"
    assert g["5"]["inputs"]["mask"] == ["4", 0]


if __name__ == "__main__":
    import traceback
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{passed} tests passed")
    sys.exit(0 if passed >= 9 else 1)
