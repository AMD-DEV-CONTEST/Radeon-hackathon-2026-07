# -*- coding: utf-8 -*-
"""Textovid — Multimodal AI Comic Studio

AMD AI DevMaster Hackathon 2026 — Track 1 ($30K)
Powered by AMD ROCm 7.2 · Radeon RX 7900 XTX · SDXL · LTX Video · Qwen 35B

NOTE: Gradio 6.x requires theme/css inside launch(), NOT in Blocks().
"""

from __future__ import annotations

import os
import sys
import time
import gradio as gr

# ── Ensure we import from the project directory ─────────────────
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    GRADIO_SERVER_NAME,
    GRADIO_SERVER_PORT,
    OUTPUT_DIR,
    MAX_SEED,
    PANELS_PER_PAGE,
)
from gpu_utils import get_gpu_info
from story_engine import generate_panels
from image_engine import generate_panel_image
from comic_layout import assemble_comic_page
from uniqueness import panel_fingerprint

# Optional video import (may fail if LTX Video not downloaded)
try:
    from video_engine import animate_panel
    HAS_VIDEO = True
except ImportError:
    HAS_VIDEO = False


# ── Helper to read CSS file ──────────────────────────────────────
def _load_css() -> str:
    css_path = os.path.join(os.path.dirname(__file__), "style.css")
    if os.path.exists(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


# ── Main generation pipeline ────────────────────────────────────
def generate_comic(
    prompt: str,
    style: str = "superhero",
    seed: int = -1,
    use_highres: bool = True,
    enable_video: bool = False,
    progress=gr.Progress(),
):
    """Full pipeline: story → images → comic page.

    Returns (comic_page_path, gallery_images, fingerprint_info, log_text).
    """
    logs = []
    def log(msg):
        logs.append(msg)
        print(f"[Textovid] {msg}")

    t0 = time.time()
    log(f"Starting generation — prompt: \"{prompt[:80]}\"  style: {style}")

    # ── 0. GPU check ─────────────────────────────────────────────
    gpu = get_gpu_info()
    log(f"GPU: {gpu['name']}  |  VRAM: {gpu['vram_free_gb']}/{gpu['vram_total_gb']} GB")
    if not gpu["available"]:
        return None, [], "", "ERROR: No GPU detected. ROCm driver may not be loaded."

    # ── 1. Generate story panels ─────────────────────────────────
    progress(0.05, desc="Generating story panels …")
    panels = generate_panels(prompt, style)
    log(f"Story engine returned {len(panels)} panels")
    for p in panels:
        log(f"  Panel {p.get('panel','?')}: {p.get('image_prompt','')[:60]}…")

    # ── 2. Generate panel images ─────────────────────────────────
    images = []
    fingerprints = []
    for i, panel in enumerate(panels):
        pct = 0.1 + 0.55 * (i / len(panels))
        progress(pct, desc=f"Generating panel {i+1}/{len(panels)} …")

        s = (seed + i) if seed >= 0 else -1
        img_prompt = panel.get("image_prompt", "")

        # Inject style into prompt if not already there
        style_kw = f"{style}-style comic panel"
        if style_kw.lower() not in img_prompt.lower():
            img_prompt = f"{style_kw}. {img_prompt}"

        log(f"  Generating panel {i+1} image …")
        try:
            img, actual_seed = generate_panel_image(img_prompt, seed=s)
            images.append(img)
            fp = panel_fingerprint(panel, img)
            fingerprints.append(fp)
            log(f"  Panel {i+1} done  seed={actual_seed}  hash={fp['combined_hash'][:12]}…")
        except Exception as exc:
            log(f"  ERROR panel {i+1}: {exc}")
            # Create placeholder
            from PIL import Image
            ph = Image.new("RGB", (1024, 1024), (40, 40, 60))
            from PIL import ImageDraw
            d = ImageDraw.Draw(ph)
            d.text((200, 500), f"Panel {i+1} Error", fill="white")
            images.append(ph)
            fingerprints.append({"combined_hash": "error"})

    # ── 3. Assemble comic page ───────────────────────────────────
    progress(0.75, desc="Assembling comic page …")
    page_path = assemble_comic_page(panels, images)
    log(f"Comic page saved: {page_path}")

    # ── 4. Optional video animation ──────────────────────────────
    video_path = None
    if enable_video and HAS_VIDEO and len(images) > 0:
        progress(0.85, desc="Animating first panel …")
        try:
            video_path = animate_panel(
                panels[0].get("image_prompt", ""), images[0]
            )
            log(f"Animation saved: {video_path}")
        except Exception as exc:
            log(f"Video generation failed: {exc}")
    elif enable_video and not HAS_VIDEO:
        log("Video engine not available (LTX Video not installed)")

    elapsed = time.time() - t0
    log(f"Generation complete in {elapsed:.1f}s")

    # ── Build outputs ────────────────────────────────────────────
    fp_summary = "\n".join(
        f"Panel {i+1}: {fp['combined_hash']}"
        for i, fp in enumerate(fingerprints)
    )

    log_text = "\n".join(logs)
    print(log_text)

    gallery_imgs = [img for img in images if img is not None]

    return page_path, gallery_imgs, fp_summary, log_text


# ── GPU info helper for the UI ───────────────────────────────────
def refresh_gpu():
    gpu = get_gpu_info()
    if gpu["available"]:
        return (
            f"**{gpu['name']}**  \\-  "
            f"VRAM: {gpu['vram_free_gb']}/{gpu['vram_total_gb']} GB free  \\-  "
            f"{gpu['cuda_version']}"
        )
    return "No GPU detected. Check ROCm driver."


# ══════════════════════════════════════════════════════════════════
#  Build the Gradio interface
# ══════════════════════════════════════════════════════════════════

with gr.Blocks() as demo:
    gr.Markdown(
        "# **Textovid** — Multimodal AI Comic Studio\n"
        "*Powered by AMD ROCm 7.2 | SDXL | LTX Video | Qwen 35B*\n\n"
        "Enter a story idea and watch Textovid generate a full comic page "
        "with AI-generated panels, speech bubbles, SFX, and captions."
    )

    with gr.Row():
        gpu_info = gr.Markdown(refresh_gpu())

    with gr.Row():
        with gr.Column(scale=3):
            prompt_input = gr.Textbox(
                label="Story Prompt",
                placeholder="A superhero cat saves the city from a giant robot…",
                lines=3,
            )
            style_dropdown = gr.Dropdown(
                label="Visual Style",
                choices=["superhero", "manga", "noir", "watercolor", "pixel"],
                value="superhero",
            )
            with gr.Row():
                seed_input = gr.Number(
                    label="Seed (-1 = random)",
                    value=-1,
                    precision=0,
                )
                highres_toggle = gr.Checkbox(
                    label="High-Res Fix (~2048px)",
                    value=True,
                )
                video_toggle = gr.Checkbox(
                    label="Animate First Panel (LTX Video)",
                    value=False,
                )
            generate_btn = gr.Button(
                "Generate Comic Page", variant="primary", size="lg"
            )

        with gr.Column(scale=2):
            log_output = gr.Textbox(
                label="Generation Log",
                lines=12,
                interactive=False,
                max_lines=30,
            )
            fingerprint_output = gr.Textbox(
                label="Uniqueness Fingerprints (SHA-256)",
                lines=4,
                interactive=False,
            )

    with gr.Tabs():
        with gr.Tab("Comic Page"):
            comic_output = gr.Image(
                label="Assembled Comic Page",
                type="filepath",
                height=700,
            )
        with gr.Tab("Individual Panels"):
            panel_gallery = gr.Gallery(
                label="Generated Panels",
                columns=2,
                height=500,
            )
        with gr.Tab("Panel Animation"):
            video_output = gr.Video(label="Animated Panel")

    # ── Wire up events ────────────────────────────────────────────
    generate_btn.click(
        fn=generate_comic,
        inputs=[
            prompt_input,
            style_dropdown,
            seed_input,
            highres_toggle,
            video_toggle,
        ],
        outputs=[
            comic_output,
            panel_gallery,
            fingerprint_output,
            log_output,
        ],
    )


# ══════════════════════════════════════════════════════════════════
#  Launch — CRITICAL: theme & css go in launch() for Gradio 6.x
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("[Textovid] Launching Gradio interface …")
    demo.launch(
        server_name=GRADIO_SERVER_NAME,
        server_port=GRADIO_SERVER_PORT,
        share=True,  # creates a public share link via frpc
        css=_load_css(),
        theme=gr.themes.Soft(
            primary_hue="red",
            secondary_hue="slate",
        ),
    )
