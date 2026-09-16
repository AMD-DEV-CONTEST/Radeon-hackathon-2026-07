#!/usr/bin/env python3
"""MiniMax H3 - Local Multimodal Video Studio (AMD Radeon).

Gradio web app exposing open-weights MiniMax H3 running locally on AMD Radeon
GPUs (ROCm) through ComfyUI's native nodes:
  - Text-to-Video (T2V): prompt -> video + stereo audio
  - Image-to-Video (I2V): prompt + first/last keyframe(s) -> video + audio
  - Reference-to-Video (R2V): prompt + reference images -> video + audio

Usage:
    python app/gradio_app.py --share          # public link
    python app/gradio_app.py --port 7860
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time
import urllib.request

import gradio as gr
import numpy as np

from comfy_client import generate, DEFAULT_MODELS, STEPS, SAMPLER, SCHEDULER, API_BASE

RESOLUTIONS = {
    "Fast preview (864x480)": (864, 480),
    "HD (1152x640)": (1152, 640),
    "Full 768p short edge (1344x768)": (1344, 768),
}

CLIP_OPTIONS = [
    "qwen3vl_32b_minimax_h3_int8_convrot.safetensors  (int8, recommended on ROCm)",
]


def _now_ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _comfy_online() -> bool:
    try:
        with urllib.request.urlopen(f"{API_BASE}/system_stats", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _find_output_mp4(outputs: dict) -> str | None:
    """Locate the saved mp4 in a ComfyUI history outputs payload."""
    for o in outputs.values():
        for g in o.get("images", []):
            if g.get("type") == "output":
                path = os.path.join("/opt/ComfyUI/output", g.get("subfolder", ""), g["filename"])
                if os.path.exists(path):
                    return path
    return None


def _run(prompt, mode, resolution, duration, seed, images, clip_choice, progress=gr.Progress()):
    w, h = RESOLUTIONS[resolution]
    clip_name = clip_choice.split("  (")[0]

    kwargs = dict(
        prompt=prompt, mode=mode, width=w, height=h,
        duration_s=duration, seed=int(seed), clip_name=clip_name,
    )

    if mode == "i2v" and images:
        if len(images) >= 1:
            kwargs["first_frame"] = np.array(images[0])
        if len(images) >= 2:
            kwargs["last_frame"] = np.array(images[1])
    if mode == "r2v" and images:
        kwargs["ref_images"] = [np.array(im) for im in images]

    if not _comfy_online():
        raise gr.Error("ComfyUI is not running — start it first (see README).")

    progress(0.02, desc="submitting to ComfyUI…")

    def _cb(elapsed, status):
        progress(elapsed, desc=f"{status} · {elapsed:.0f}s elapsed")

    result = generate(**kwargs, progress_cb=_cb)
    if result.get("status") != "success":
        raise gr.Error(f"Generation failed: {result.get('status')}")

    mp4 = _find_output_mp4(result.get("outputs", {}))
    if not mp4:
        raise gr.Error("output mp4 not found")

    ext = os.path.splitext(mp4)[1] or ".mp4"
    dst = os.path.join(tempfile.gettempdir(), f"minimax_h3_{_now_ts()}{ext}")
    shutil.copy(mp4, dst)
    progress(1.0, desc="done")
    return dst


def build_app() -> gr.Blocks:
    with gr.Blocks(title="MiniMax H3 · Local Multimodal Video Studio (AMD Radeon)") as demo:
        gr.Markdown(
            """
            # MiniMax H3 · Local Multimodal Video Studio
            **Open-weights omni-modal video model on AMD Radeon (ROCm).**
            Text, images → video with native stereo audio. Runs 100% locally on
            a single AMD GPU via ComfyUI + pruned int8 weights.
            """
        )

        with gr.Tab("Text → Video (T2V)"):
            t2v_prompt = gr.Textbox(label="Prompt", lines=6, value=(
                "Cinematic drone shot flying over a neon cyberpunk city at dusk, "
                "rain-slick streets reflecting holographic signs, volumetric fog, "
                "slow sweeping camera, subtle wind and distant traffic sound."
            ))
            with gr.Row():
                t2v_res = gr.Dropdown(list(RESOLUTIONS), value="Fast preview (864x480)", label="Resolution")
                t2v_dur = gr.Slider(2.0, 15.0, value=5.0, step=0.5, label="Duration (s)")
                t2v_seed = gr.Number(value=556589502035082, precision=0, label="Seed")
            t2v_clip = gr.Dropdown(CLIP_OPTIONS, value=CLIP_OPTIONS[0], label="Text encoder")
            t2v_btn = gr.Button("Generate", variant="primary")
            t2v_out = gr.Video(label="Result (video + stereo audio)")

        with gr.Tab("Image → Video (I2V)"):
            i2v_prompt = gr.Textbox(label="Prompt", lines=4, value=(
                "The camera slowly pushes in while the character turns to look at the sky, "
                "wind and a low ambient drone in the background."
            ))
            i2v_img = gr.Gallery(label="First / last frame (optional, up to 2)", columns=2, height=200)
            with gr.Row():
                i2v_res = gr.Dropdown(list(RESOLUTIONS), value="Fast preview (864x480)", label="Resolution")
                i2v_dur = gr.Slider(2.0, 15.0, value=5.0, step=0.5, label="Duration (s)")
                i2v_seed = gr.Number(value=556589502035082, precision=0, label="Seed")
            i2v_clip = gr.Dropdown(CLIP_OPTIONS, value=CLIP_OPTIONS[0], label="Text encoder")
            i2v_btn = gr.Button("Generate", variant="primary")
            i2v_out = gr.Video(label="Result (video + stereo audio)")

        with gr.Tab("Reference → Video (R2V)"):
            gr.Markdown(
                "Lock identity / style from reference images. Use `<Picture 1>` (and so on) "
                "in the prompt to reference each connected image in order. Requires the "
                "ref2va model (`minimax_h3_ref2va_pruned_int8_convrot.safetensors`)."
            )
            r2v_prompt = gr.Textbox(label="Prompt", lines=4, value=(
                "Using <Picture 1> as the character reference, show the character running "
                "through a rainy alley, camera following behind, footsteps and rain sounds."
            ))
            r2v_img = gr.Gallery(label="Reference images (up to 9)", columns=3, height=200)
            with gr.Row():
                r2v_res = gr.Dropdown(list(RESOLUTIONS), value="Fast preview (864x480)", label="Resolution")
                r2v_dur = gr.Slider(2.0, 15.0, value=5.0, step=0.5, label="Duration (s)")
                r2v_seed = gr.Number(value=556589502035082, precision=0, label="Seed")
            r2v_clip = gr.Dropdown(CLIP_OPTIONS, value=CLIP_OPTIONS[0], label="Text encoder")
            r2v_btn = gr.Button("Generate", variant="primary")
            r2v_out = gr.Video(label="Result (video + stereo audio)")

        t2v_btn.click(
            _run,
            [t2v_prompt, gr.State("t2v"), t2v_res, t2v_dur, t2v_seed, gr.State([]), t2v_clip],
            t2v_out,
        )
        i2v_btn.click(
            _run,
            [i2v_prompt, gr.State("i2v"), i2v_res, i2v_dur, i2v_seed, i2v_img, i2v_clip],
            i2v_out,
        )
        r2v_btn.click(
            _run,
            [r2v_prompt, gr.State("r2v"), r2v_res, r2v_dur, r2v_seed, r2v_img, r2v_clip],
            r2v_out,
        )

        gr.Markdown(
            "---\n**Hardware:** AMD Radeon PRO (gfx1100, RDNA3, 48 GB) · ROCm 7.2.4 · "
            f"ComfyUI · pruned int8 diffusion + int8 Qwen3-VL-32B text encoder · "
            f"sampler `{SAMPLER}` / `{SCHEDULER}` / {STEPS} steps."
        )
    return demo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--share", action="store_true")
    args = ap.parse_args()

    demo = build_app()
    demo.launch(server_name=args.host, server_port=args.port, share=args.share,
                allowed_paths=["/tmp"], inbrowser=False, ssl_verify=False)


if __name__ == "__main__":
    main()
