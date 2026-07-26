# -*- coding: utf-8 -*-
"""AI-Image-Studio (Radeon Edition) — all-in-one AI image & video studio
running locally on AMD Radeon GPU + ROCm.

Features: inpainting / outpainting / object & watermark removal / super-resolution /
style transfer (single & batch) / background removal & replace / face restoration /
asset splitting / poster batch / video super-resolution / e-commerce suite.

Run:  python app.py            → http://localhost:7860
      python app.py --share    → public gradio.live URL (use on cloud instances)
"""
from __future__ import annotations

import argparse
import inspect
import os

# Disable Gradio telemetry so startup never blocks on isolated GPU hosts.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr
from PIL import Image

from config import settings
from src.device import detect_device, free_vram_gb
from src.model_manager import ModelManager
from src.pipelines import (POSTER_SIZES, STYLE_PRESETS, run_background,
                           run_character_split, run_ecommerce, run_face_restore,
                           run_inpaint, run_outpaint, run_poster_batch, run_remove,
                           run_style, run_style_batch, run_upscale, run_video_upscale)
from src.utils import editor_to_image_mask

DEVICE_INFO = detect_device(settings.device, settings.dtype)
MANAGER = ModelManager(DEVICE_INFO, settings)

APP_TITLE = "AI-Image-Studio · Radeon Edition"


# ---------------------------------------------------------------- helpers

def _perf_md(info: dict) -> str:
    lines = ["| Metric | Value |", "| --- | --- |"]
    for k, v in info.items():
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _err(e: Exception):
    raise gr.Error(f"{type(e).__name__}: {e}")


def _status_md() -> str:
    loaded = MANAGER.loaded_models()
    lines = [
        "### Runtime",
        f"- Inference backend: **{DEVICE_INFO.summary()}**",
        f"- Low-VRAM mode: {'ON' if settings.low_vram else 'OFF'}",
        f"- Diffusion working resolution: {settings.max_diffusion_size}px (long edge)",
    ]
    if DEVICE_INFO.device.type == "cuda":
        lines.append(f"- Free VRAM now: {free_vram_gb():.2f} GB")
    lines += ["", "### Loaded models"]
    lines += [f"- {m}" for m in loaded] if loaded else ["- (none yet — models load lazily on first use)"]
    return "\n".join(lines)


def _editor(label: str, height: int = 420) -> gr.ImageEditor:
    return gr.ImageEditor(
        label=label, type="pil", sources=["upload", "clipboard"],
        transforms=(), layers=False, height=height,
        brush=gr.Brush(default_size=32, colors=["#FFFFFF"], color_mode="fixed"),
        eraser=gr.Eraser(default_size=32),
    )


def _perf_block():
    return gr.Markdown(elem_classes=["perf-table"])


# ---------------------------------------------------------------- callbacks
# (unchanged — thin wrappers around src/pipelines)

def cb_inpaint(editor, prompt, negative, expand, steps, guidance, strength, seed, fast):
    try:
        image, mask = editor_to_image_mask(editor, expand_px=int(expand))
        out, info, _ = run_inpaint(MANAGER, image, mask, prompt, negative,
                                   steps, guidance, strength, seed, fast)
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_outpaint(image, left, right, top, bottom, prompt, negative, steps, guidance, seed, fast):
    try:
        out, info, _ = run_outpaint(MANAGER, image, left, right, top, bottom,
                                    prompt, negative, steps, guidance, seed, fast)
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_remove(editor, expand):
    try:
        image, mask = editor_to_image_mask(editor, expand_px=int(expand))
        out, info = run_remove(MANAGER, image, mask)
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_upscale(image, quality, target_scale, tile):
    try:
        out, info = run_upscale(MANAGER, image, quality, float(target_scale), int(tile))
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_style(image, style, strength, custom_prompt, custom_negative, steps, guidance, seed,
             fast, lora_ref, lora_scale):
    try:
        out, info, _ = run_style(MANAGER, image, style, custom_prompt, custom_negative,
                                 strength, steps, guidance, seed, fast, lora_ref, lora_scale)
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_style_batch(files, style, strength, fast):
    try:
        images = [Image.open(p).convert("RGB") for p in (files or [])]
        if not images:
            raise ValueError("Please upload at least one image.")
        outs, summary = run_style_batch(MANAGER, images, style, "", "",
                                        strength, steps=25, guidance=7.5, fast=fast)
        return outs, _perf_md(summary)
    except Exception as e:
        _err(e)


def cb_background(image, mode, solid, gt, gb, ai_prompt):
    try:
        result, fg, info = run_background(MANAGER, image, mode, solid, gt, gb, ai_prompt)
        return result, fg, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_face_restore(image, also_upscale):
    try:
        out, info = run_face_restore(MANAGER, image, bool(also_upscale))
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_character_split(image, fill_bg, margin):
    try:
        character, background, psd_path, zip_path, info = run_character_split(
            MANAGER, image, bool(fill_bg), int(margin))
        files = [f for f in (psd_path, zip_path) if f]
        return character, background, files, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_poster(prompt, negative, size_name, title, subtitle, tag, layout,
              count, steps, guidance, seed, do_upscale, fast, lora_ref, lora_scale):
    try:
        posters, info = run_poster_batch(
            MANAGER, prompt, negative, size_name, title, subtitle, tag, layout,
            count, steps, guidance, seed, bool(do_upscale), fast, lora_ref, lora_scale)
        return posters, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_video(video_path, quality, scale, progress=gr.Progress()):
    try:
        out_path, info = run_video_upscale(MANAGER, video_path, quality, float(scale),
                                           progress_cb=lambda p, d: progress(p, desc=d))
        return out_path, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_ecommerce(image, scene_prompt, title, subtitle, size_name, scene_count, do_upscale, fast):
    try:
        images, info = run_ecommerce(MANAGER, image, scene_prompt, title, subtitle,
                                     size_name, scene_count, bool(do_upscale), fast)
        return images, _perf_md(info)
    except Exception as e:
        _err(e)


# ---------------------------------------------------------------- UI

CSS = """
.gradio-container {max-width: 1340px !important; margin: 0 auto !important; padding: 0 16px;}
#app-header {text-align: center; padding: 18px 0 4px;}
#app-header h1 {font-size: 30px; font-weight: 800; margin: 0; letter-spacing: -0.5px;}
#app-header h1 .accent {color: #ED1C24;}
#app-header p.sub {color: #666; margin: 6px auto 10px; max-width: 900px; font-size: 15px;}
#app-header .badge {
    display: inline-block; background: #111; color: #7CF29C; font-family: monospace;
    font-size: 13px; padding: 6px 14px; border-radius: 999px; margin-bottom: 8px;
}
.hint {color: #666; font-size: 14px; margin: 2px 0 10px;}
.perf-table table {font-size: 13px;}
footer {display: none !important;}
"""


def _theme():
    return gr.themes.Soft(
        primary_hue=gr.themes.colors.red,
        neutral_hue=gr.themes.colors.zinc,
    )


def _header():
    gr.HTML(f"""
    <div id="app-header">
      <h1>🎨 AI-Image-Studio <span class="accent">· Radeon Edition</span></h1>
      <p class="sub">All-in-one AI image &amp; video studio running locally on
      <b>AMD Radeon GPU + ROCm</b> — inpaint · outpaint · remove · upscale · style ·
      background · face restore · asset split · poster batch · video SR · e-commerce.
      LCM-LoRA turbo mode cuts diffusion from 25 steps to 4–8 (3–5× faster).</p>
      <div class="badge">⚙️ {DEVICE_INFO.summary()}</div>
    </div>""")


def build_demo() -> gr.Blocks:
    blocks_kwargs = dict(title=APP_TITLE)
    sig = inspect.signature(gr.Blocks.__init__).parameters
    if "css" in sig:
        blocks_kwargs["css"] = CSS      # Gradio 5
    if "theme" in sig and "theme" not in inspect.signature(gr.Blocks.launch).parameters:
        blocks_kwargs["theme"] = _theme()  # Gradio 5 (Gradio 6 takes theme in launch)
    with gr.Blocks(**blocks_kwargs) as demo:
        _header()

        with gr.Tabs():
            # ================= 1. Inpainting =================
            with gr.Tab("🖌️ Inpaint"):
                gr.Markdown("Upload an image → **brush the area to change** → describe the desired content "
                            "(e.g. *change the shirt to red, add a cat*).", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        ed = _editor("Image + brush mask")
                        prompt = gr.Textbox(label="Prompt (what to generate in the masked area)",
                                            placeholder="e.g. a red rose, crystal clear")
                        negative = gr.Textbox(label="Negative prompt",
                                              value="blurry, low quality, deformed, watermark, text")
                        with gr.Accordion("Advanced", open=False):
                            expand = gr.Slider(0, 40, 8, step=1, label="Mask expansion (px)")
                            steps = gr.Slider(10, 50, 25, step=1, label="Inference steps")
                            guidance = gr.Slider(1.0, 15.0, 7.0, step=0.5, label="Guidance scale (CFG)")
                            strength = gr.Slider(0.5, 1.0, 1.0, step=0.05, label="Denoising strength")
                            seed = gr.Number(-1, label="Seed (-1 = random)", precision=0)
                        fast = gr.Checkbox(value=False, label="⚡ LCM turbo mode (4–8 steps, 3–5× faster)")
                        btn = gr.Button("Run Inpainting", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        out = gr.Image(label="Result", type="pil", interactive=False, height=440)
                        perf = _perf_block()
                btn.click(cb_inpaint, [ed, prompt, negative, expand, steps, guidance, strength, seed, fast],
                          [out, perf])

            # ================= 2. Outpainting =================
            with gr.Tab("🔍 Outpaint"):
                gr.Markdown("Upload an image and set how many pixels to extend in each direction — "
                            "the AI seamlessly fills the new canvas.", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        img = gr.Image(label="Image", type="pil", sources=["upload", "clipboard"], height=300)
                        with gr.Row():
                            left = gr.Slider(0, 512, 0, step=32, label="Extend left (px)")
                            right = gr.Slider(0, 512, 256, step=32, label="Extend right (px)")
                        with gr.Row():
                            top = gr.Slider(0, 512, 0, step=32, label="Extend up (px)")
                            bottom = gr.Slider(0, 512, 0, step=32, label="Extend down (px)")
                        prompt = gr.Textbox(label="Prompt (describe the full extended scene)",
                                            placeholder="e.g. wide landscape, mountains and lake, golden hour")
                        negative = gr.Textbox(label="Negative prompt",
                                              value="blurry, low quality, seam, watermark, text")
                        with gr.Accordion("Advanced", open=False):
                            steps2 = gr.Slider(10, 50, 28, step=1, label="Inference steps")
                            guidance2 = gr.Slider(1.0, 15.0, 7.0, step=0.5, label="Guidance scale (CFG)")
                            seed2 = gr.Number(-1, label="Seed (-1 = random)", precision=0)
                        fast2 = gr.Checkbox(value=False, label="⚡ LCM turbo mode (4–8 steps)")
                        btn2 = gr.Button("Run Outpainting", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        out2 = gr.Image(label="Result", type="pil", interactive=False, height=440)
                        perf2 = _perf_block()
                btn2.click(cb_outpaint, [img, left, right, top, bottom, prompt, negative,
                                         steps2, guidance2, seed2, fast2], [out2, perf2])

            # ================= 3. Object / watermark removal =================
            with gr.Tab("🧽 Remove"):
                gr.Markdown("Brush over unwanted objects, passers-by or watermarks — one click removes them "
                            "(LaMa engine, no prompt needed).", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        ed3 = _editor("Image + brush over what to erase")
                        expand3 = gr.Slider(0, 40, 12, step=1, label="Mask expansion (px)")
                        btn3 = gr.Button("Remove", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        out3 = gr.Image(label="Result", type="pil", interactive=False, height=440)
                        perf3 = _perf_block()
                btn3.click(cb_remove, [ed3, expand3], [out3, perf3])

            # ================= 4. Super-resolution =================
            with gr.Tab("✨ Upscale"):
                gr.Markdown("Real-ESRGAN enhancement: deblur and upscale 2–4×, with tiled inference "
                            "for large images on limited VRAM.", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        img4 = gr.Image(label="Image", type="pil", sources=["upload", "clipboard"], height=300)
                        quality = gr.Radio([("Fast (x4v3, best for batches)", "fast"),
                                            ("High quality (x4plus)", "hq")],
                                           value="fast", label="Model tier")
                        scale4 = gr.Slider(1.5, 4.0, 4.0, step=0.5, label="Scale factor")
                        tile = gr.Dropdown([("Off (plenty of VRAM)", 0), ("512px tiles", 512),
                                            ("256px tiles (large images / low VRAM)", 256)],
                                           value=0, label="Tiled inference")
                        btn4 = gr.Button("Upscale", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        out4 = gr.Image(label="Result", type="pil", interactive=False, height=440)
                        perf4 = _perf_block()
                btn4.click(cb_upscale, [img4, quality, scale4, tile], [out4, perf4])

            # ================= 5. Style transfer =================
            with gr.Tab("🎭 Style"):
                gr.Markdown("Restyle photos into anime, cyberpunk, watercolor, oil painting and more — "
                            "single fine-tuned mode and batch mode.", elem_classes=["hint"])
                with gr.Tabs():
                    with gr.Tab("Single image"):
                        with gr.Row():
                            with gr.Column(scale=5, min_width=340):
                                img5 = gr.Image(label="Image", type="pil", sources=["upload", "clipboard"],
                                                height=300)
                                style = gr.Dropdown(list(STYLE_PRESETS.keys()), value="日系动漫",
                                                    label="Style preset")
                                strength5 = gr.Slider(0.2, 0.95, 0.6, step=0.05,
                                                      label="Strength (higher = further from original)")
                                with gr.Accordion("Custom prompt (optional, overrides preset)", open=False):
                                    cp = gr.Textbox(label="Custom prompt",
                                                    placeholder="Leave empty to use the preset")
                                    cn = gr.Textbox(label="Custom negative prompt")
                                with gr.Accordion("Advanced", open=False):
                                    steps5 = gr.Slider(10, 50, 25, step=1, label="Inference steps")
                                    guidance5 = gr.Slider(1.0, 15.0, 7.5, step=0.5, label="Guidance scale (CFG)")
                                    seed5 = gr.Number(-1, label="Seed (-1 = random)", precision=0)
                                with gr.Accordion("Custom LoRA (optional)", open=False):
                                    lora5 = gr.Textbox(label="LoRA repo id or local .safetensors path",
                                                       placeholder="e.g. someone/my-style-lora")
                                    lora_scale5 = gr.Slider(0.0, 1.5, 0.8, step=0.05, label="LoRA weight")
                                fast5 = gr.Checkbox(value=False, label="⚡ LCM turbo mode (4–8 steps)")
                                btn5 = gr.Button("Restyle", variant="primary", size="lg")
                            with gr.Column(scale=6, min_width=380):
                                out5 = gr.Image(label="Result", type="pil", interactive=False, height=440)
                                perf5 = _perf_block()
                        btn5.click(cb_style, [img5, style, strength5, cp, cn, steps5, guidance5, seed5,
                                              fast5, lora5, lora_scale5], [out5, perf5])
                    with gr.Tab("Batch"):
                        with gr.Row():
                            with gr.Column(scale=5, min_width=340):
                                files = gr.File(label="Upload multiple images", file_count="multiple",
                                                file_types=["image"], type="filepath")
                                style_b = gr.Dropdown(list(STYLE_PRESETS.keys()), value="赛博朋克",
                                                      label="Style preset")
                                strength_b = gr.Slider(0.2, 0.95, 0.6, step=0.05, label="Strength")
                                fast6 = gr.Checkbox(value=True, label="⚡ LCM turbo mode (recommended for batch)")
                                btn6 = gr.Button("Run batch", variant="primary", size="lg")
                            with gr.Column(scale=6, min_width=380):
                                gallery = gr.Gallery(label="Batch results", columns=3, height=440)
                                perf6 = _perf_block()
                        btn6.click(cb_style_batch, [files, style_b, strength_b, fast6], [gallery, perf6])

            # ================= 6. Background =================
            with gr.Tab("🧑‍🎨 Background"):
                gr.Markdown("BiRefNet high-precision matting: export transparent PNG, swap in a solid / "
                            "gradient background, or generate a brand-new AI backdrop.", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        img7 = gr.Image(label="Image", type="pil", sources=["upload", "clipboard"], height=300)
                        mode = gr.Radio([("Transparent PNG", "透明 PNG"), ("Solid color", "纯色背景"),
                                         ("Gradient", "渐变背景"), ("AI-generated", "AI 生成背景")],
                                        value="透明 PNG", label="Output mode")
                        with gr.Accordion("Background options", open=True):
                            solid = gr.ColorPicker(value="#FFFFFF", label="Solid color")
                            with gr.Row():
                                gt = gr.ColorPicker(value="#89CFF0", label="Gradient top")
                                gb = gr.ColorPicker(value="#F0E68C", label="Gradient bottom")
                            ai_prompt = gr.Textbox(label="AI background prompt",
                                                   placeholder="e.g. sunset beach, bokeh studio backdrop")
                        btn7 = gr.Button("Process", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        with gr.Row():
                            out7 = gr.Image(label="Result", type="pil", interactive=False, height=420)
                            fg7 = gr.Image(label="Foreground (RGBA)", type="pil", interactive=False, height=420)
                        perf7 = _perf_block()
                btn7.click(cb_background, [img7, mode, solid, gt, gb, ai_prompt], [out7, fg7, perf7])

            # ================= 7. Face restoration =================
            with gr.Tab("😊 Face Restore"):
                gr.Markdown("GFPGAN blind face restoration: turn blurry / low-res / old portrait faces crisp. "
                            "Multi-face supported, optional whole-image 2× upscale.", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        img8 = gr.Image(label="Image with faces", type="pil",
                                        sources=["upload", "clipboard"], height=300)
                        up8 = gr.Checkbox(value=False, label="Also 2× upscale the whole image after restore")
                        btn8 = gr.Button("Restore", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        out8 = gr.Image(label="Result", type="pil", interactive=False, height=440)
                        perf8 = _perf_block()
                btn8.click(cb_face_restore, [img8, up8], [out8, perf8])

            # ================= 8. Asset splitting =================
            with gr.Tab("🧩 Asset Split"):
                gr.Markdown("Split one character illustration into a **transparent character layer + completed "
                            "background layer**, exported as a layered PSD + asset pack (Live2D prep, 2.5D).",
                            elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        img9 = gr.Image(label="Character image", type="pil",
                                        sources=["upload", "clipboard"], height=300)
                        fill9 = gr.Checkbox(value=True, label="AI-complete the background (erase + fill)")
                        margin9 = gr.Slider(0, 64, 16, step=4, label="Crop margin (px)")
                        btn9 = gr.Button("Split", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        with gr.Row():
                            chara9 = gr.Image(label="Character layer (transparent)", type="pil",
                                              interactive=False, height=290)
                            bg9 = gr.Image(label="Background layer", type="pil",
                                           interactive=False, height=290)
                        files9 = gr.File(label="Download layered files (PSD + asset pack)",
                                         file_count="multiple")
                        perf9 = _perf_block()
                btn9.click(cb_character_split, [img9, fill9, margin9],
                           [chara9, bg9, files9, perf9])

            # ================= 9. Poster batch =================
            with gr.Tab("🖼️ Poster"):
                gr.Markdown("txt2img → 2× upscale → template typesetting: batch-produce e-commerce covers, "
                            "campaign posters and content covers (pixel-accurate CJK text, no garbled glyphs).",
                            elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        prompt10 = gr.Textbox(label="Scene prompt", lines=2,
                                              placeholder="e.g. fresh oranges splashing juice, studio lighting, commercial photography")
                        negative10 = gr.Textbox(label="Negative prompt",
                                                value="blurry, low quality, watermark, text, logo")
                        with gr.Row():
                            size10 = gr.Dropdown(list(POSTER_SIZES.keys()),
                                                 value="竖版海报 2:3（1024×1536）", label="Size")
                            count10 = gr.Slider(1, 8, 2, step=1, label="Batch count")
                        with gr.Row():
                            title10 = gr.Textbox(label="Headline", placeholder="e.g. 夏日狂欢节")
                            subtitle10 = gr.Textbox(label="Sub-headline", placeholder="e.g. 全场五折起")
                        with gr.Row():
                            tag10 = gr.Textbox(label="Corner tag (optional)", placeholder="e.g. 限时特惠")
                            layout10 = gr.Radio([("Bottom banner", "底部横幅"), ("Top title", "顶部标题"),
                                                 ("Centered", "居中大标题")],
                                                value="底部横幅", label="Layout")
                        with gr.Accordion("Advanced", open=False):
                            steps10 = gr.Slider(10, 50, 25, step=1, label="Inference steps")
                            guidance10 = gr.Slider(1.0, 15.0, 7.5, step=0.5, label="Guidance scale (CFG)")
                            seed10 = gr.Number(-1, label="Seed (-1 = random, auto-increments)", precision=0)
                            up10 = gr.Checkbox(value=True, label="2× upscale after generation (recommended)")
                            fast10 = gr.Checkbox(value=False, label="⚡ LCM turbo mode (4–8 steps)")
                            lora10 = gr.Textbox(label="Custom LoRA (optional)",
                                                placeholder="HF repo id or local .safetensors path")
                            lora_scale10 = gr.Slider(0.0, 1.5, 0.8, step=0.05, label="LoRA weight")
                        btn10 = gr.Button("Generate posters", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        gallery10 = gr.Gallery(label="Posters", columns=2, height=500)
                        perf10 = _perf_block()
                btn10.click(cb_poster, [prompt10, negative10, size10, title10, subtitle10,
                                        tag10, layout10, count10, steps10, guidance10,
                                        seed10, up10, fast10, lora10, lora_scale10], [gallery10, perf10])

            # ================= 10. Video SR =================
            with gr.Tab("🎬 Video SR"):
                gr.Markdown("AI video enhancement: frame-by-frame super-resolution with the original audio "
                            "track preserved. For short clips (≤ 30 s, ≤ 720p by default).", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        video11 = gr.Video(label="Upload video (mp4 recommended)", sources=["upload"])
                        quality11 = gr.Radio([("Fast (recommended)", "fast"), ("High quality", "hq")],
                                             value="fast", label="SR tier")
                        scale11 = gr.Radio([("2×", 2.0), ("4×", 4.0)], value=2.0, label="Scale factor")
                        btn11 = gr.Button("Enhance video", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        out11 = gr.Video(label="Enhanced video", interactive=False)
                        perf11 = _perf_block()
                btn11.click(cb_video, [video11, quality11, scale11], [out11, perf11])

            # ================= 11. E-commerce suite =================
            with gr.Tab("🛒 E-Commerce"):
                gr.Markdown("One product photo → a complete asset set: **white-background main image + "
                            "AI scene images + typeset posters**.", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=340):
                        img12 = gr.Image(label="Product photo", type="pil",
                                         sources=["upload", "clipboard"], height=280)
                        scene12 = gr.Textbox(
                            label="Scene prompt", lines=2,
                            value="modern minimalist product photography, marble surface, soft studio lighting",
                            placeholder="Describe the shooting scene")
                        with gr.Row():
                            title12 = gr.Textbox(label="Poster headline", placeholder="e.g. 焕新上市")
                            subtitle12 = gr.Textbox(label="Poster sub-headline", placeholder="e.g. 匠心之作")
                        with gr.Row():
                            size12 = gr.Dropdown(list(POSTER_SIZES.keys()),
                                                 value="方形主图 1:1（1024×1024）", label="Size")
                            count12 = gr.Slider(1, 4, 2, step=1, label="Scene images")
                        with gr.Row():
                            up12 = gr.Checkbox(value=True, label="2× upscale (recommended)")
                            fast12 = gr.Checkbox(value=False, label="⚡ LCM turbo mode")
                        btn12 = gr.Button("Generate full asset set", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=380):
                        gallery12 = gr.Gallery(label="Assets (main / scenes / posters)", columns=3, height=500)
                        perf12 = _perf_block()
                btn12.click(cb_ecommerce, [img12, scene12, title12, subtitle12, size12,
                                           count12, up12, fast12], [gallery12, perf12])

            # ================= 12. System =================
            with gr.Tab("⚙️ System"):
                status = gr.Markdown(_status_md())
                with gr.Row():
                    refresh = gr.Button("🔄 Refresh status")
                    unload = gr.Button("Unload all models (free VRAM)", variant="stop")
                refresh.click(lambda: _status_md(), None, status)
                unload.click(lambda: (MANAGER.unload_all(), _status_md())[1], None, status)
        return demo


def main():
    parser = argparse.ArgumentParser(description="AI-Image-Studio · Radeon Edition")
    parser.add_argument("--host", default=settings.server_name)
    parser.add_argument("--port", type=int, default=settings.server_port)
    parser.add_argument("--share", action="store_true", default=settings.share)
    parser.add_argument("--preload", action="store_true", help="Preload the inpainting model at startup")
    parser.add_argument("--low-vram", action="store_true", help="Force low-VRAM mode")
    args = parser.parse_args()

    if args.low_vram:
        settings.low_vram = True
    if args.preload:
        print("Preloading inpainting pipeline...")
        MANAGER.get_inpaint_pipe()

    print(f"Inference backend: {DEVICE_INFO.summary()}")
    demo = build_demo()
    launch_kwargs = dict(server_name=args.host, server_port=args.port,
                         share=args.share, show_error=True)
    launch_sig = inspect.signature(gr.Blocks.launch).parameters
    if "css" in launch_sig:
        launch_kwargs["css"] = CSS      # Gradio 6 moved css to launch()
    if "theme" in launch_sig:
        launch_kwargs["theme"] = _theme()  # Gradio 6 moved theme to launch()
    demo.launch(**launch_kwargs)


if __name__ == "__main__":
    main()
