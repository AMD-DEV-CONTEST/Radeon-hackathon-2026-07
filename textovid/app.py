"""
Textovid — AI Comic Studio
Main Gradio Application
Track 1: Multimodal Content Creation Tools — AMD AI DevMaster Hackathon 2026

Features:
  - Dual input modes (text prompt / category buttons)
  - Uniqueness Engine for guaranteed-original comics
  - High-Res Fix (2x SDXL refiner pass) for 4K-quality panels
  - Professional comic page layout with title page, speech bubbles, SFX
  - Optional LTX Video panel animation
  - Built-in AMD Radeon GPU benchmark
  - Sci-fi UI with 4K video background
"""

import os
import sys
import json
import time
import traceback
from pathlib import Path

import gradio as gr

# ── Ensure project root on sys.path ─────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config
import story_engine
import image_engine
import comic_layout
import gpu_utils

# ── Output directory ────────────────────────────────────────────────────
os.makedirs(config.OUTPUT_DIR, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════
#   CORE GENERATION PIPELINE
# ════════════════════════════════════════════════════════════════════════

def run_pipeline(
    mode: str,
    text_prompt: str = "",
    genre: str = "Sci-Fi",
    sub_genre: str = "Cyberpunk",
    art_style: str = "Western Comic (Marvel/DC style)",
    theme: str = "Discovery",
    mood: str = "Epic",
    length: str = "Short  (3 pages)",
    api_key: str = "",
    steps: int = 25,
    cfg_scale: float = 7.5,
    seed: int = -1,
    high_res: bool = True,
    enable_video: bool = False,
    progress=gr.Progress(),
):
    """Full pipeline: Story → Images → [Video] → Comic Pages."""
    t_start = time.time()

    # ── 0. API key ──────────────────────────────────────────────────────
    if api_key.strip():
        config.LLM_API_KEY = api_key.strip()
    if not config.LLM_API_KEY:
        raise gr.Error(
            "API Key required! Get your free key from:\n"
            "https://developer.amd.com.cn/radeon/modelapis → Token Factory"
        )

    # ── 1. Story Script ─────────────────────────────────────────────────
    progress(0.0, "Generating unique story script via LLM...")

    num_pages = config.LENGTHS.get(length, 3)

    if mode == "text":
        if not text_prompt.strip():
            raise gr.Error("Please enter a story premise in the text input.")
        script = story_engine.generate_from_text(
            user_text=text_prompt,
            num_pages=num_pages,
            panels_per_page=4,
            art_style=art_style,
            mood=mood,
        )
    else:
        from uniqueness import generate_unique_premise
        premise = generate_unique_premise(
            genre=genre, sub_genre=sub_genre, theme=theme, mood=mood
        )
        script = story_engine.generate_from_categories(
            genre=genre,
            sub_genre=sub_genre if sub_genre else None,
            art_style=art_style,
            theme=theme,
            mood=mood,
            num_pages=num_pages,
            uniqueness_premise=premise,
        )

    total_panels = story_engine.count_total_panels(script)
    progress(0.05, f"Script: '{script.get('title', 'Untitled')}' — "
                    f"{total_panels} panels, {num_pages} pages")

    # ── 2. Generate Panel Images ────────────────────────────────────────
    progress(0.05, "Loading SDXL on AMD Radeon GPU...")

    flat_panels = story_engine.flatten_panels(script)
    character_descs = [
        c.get("visual_description", "")
        for c in script.get("characters", [])
    ]

    def img_cb(frac, msg):
        progress(0.05 + 0.75 * frac, msg)

    panel_images = image_engine.generate_all_panels(
        flat_panels=flat_panels,
        art_style=art_style,
        mood=mood,
        character_descs=character_descs,
        steps=steps,
        cfg_scale=cfg_scale,
        high_res=high_res,
        progress_callback=img_cb,
    )

    # ── 3. Optional Video Animation ─────────────────────────────────────
    video_paths = []
    if enable_video and config.VIDEO_ENABLED:
        try:
            import video_engine
            if video_engine.is_available():
                progress(0.82, "Animating panels with LTX Video...")
                for i, (pi, img, _, s) in enumerate(panel_images[:3]):  # max 3 anims
                    scene = flat_panels[i][1].get("scene_description", "")
                    vp = video_engine.animate_panel(
                        image=img, prompt=scene,
                        progress_callback=img_cb,
                    )
                    if vp:
                        video_paths.append(vp)
        except Exception as e:
            print(f"[WARN] Video generation failed: {e}")

    # ── 4. Compose Comic Pages ──────────────────────────────────────────
    def layout_cb(frac, msg):
        progress(0.8 + 0.15 * frac, msg)

    page_images, metadata = comic_layout.assemble_full_comic(
        script=script,
        panel_images=panel_images,
        progress_callback=layout_cb,
    )

    # ── 5. Save outputs ─────────────────────────────────────────────────
    progress(0.96, "Saving comic pages...")
    timestamp = int(time.time())
    save_dir = os.path.join(config.OUTPUT_DIR, f"comic_{timestamp}")
    os.makedirs(save_dir, exist_ok=True)

    saved_paths = []
    for i, page_img in enumerate(page_images):
        if i == 0 and metadata.get("has_title_page"):
            path = os.path.join(save_dir, "page_00_cover.png")
        else:
            pn = i if not metadata.get("has_title_page") else i - 1
            path = os.path.join(save_dir, f"page_{pn+1:02d}.png")
        page_img.save(path, "PNG")
        saved_paths.append(path)

    # Save metadata
    meta_path = os.path.join(save_dir, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    total_time = time.time() - t_start

    # ── 6. Status report ────────────────────────────────────────────────
    gpu_info = gpu_utils.get_gpu_info()
    uniqueness_fp = script.get("_uniqueness", {}).get("fingerprint", "N/A")
    hr_label = "ON (2x refiner)" if high_res else "OFF"
    video_label = f"{len(video_paths)} clips" if video_paths else "OFF"

    status_lines = [
        f"**{metadata['title']}**",
        f"",
        f"> {metadata['synopsis']}",
        f"",
        f"### Generation Stats",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Pages | {metadata['total_pages']} (incl. cover) |",
        f"| Panels | {metadata['total_panels']} |",
        f"| Page Size | {metadata['page_size']} px |",
        f"| High-Res Fix | {hr_label} |",
        f"| Video Panels | {video_label} |",
        f"| Avg Panel Time | {metadata['avg_time_per_panel']}s |",
        f"| Total Time | {round(total_time, 1)}s |",
        f"| GPU | {gpu_info['device_name']} |",
        f"| VRAM Used | {gpu_info['vram_total_gb'] - gpu_info['vram_free_gb']:.1f} / {gpu_info['vram_total_gb']:.1f} GB |",
        f"| ROCm | {gpu_info['rocm_version']} |",
        f"| Uniqueness ID | `{uniqueness_fp}` |",
        f"| Art Style | {art_style} |",
        f"",
        f"Saved to: `{save_dir}`",
    ]

    progress(1.0, "Done!")
    return saved_paths, "\n".join(status_lines)


# ════════════════════════════════════════════════════════════════════════
#   BENCHMARK
# ════════════════════════════════════════════════════════════════════════

def run_benchmark(steps: int = 25, progress=gr.Progress()):
    progress(0, "Loading model for benchmark...")
    pipe = image_engine.load_pipeline(lambda f, m: progress(f * 0.5, m))

    progress(0.5, "Running benchmark (3 generations at 1024x1024)...")
    results = gpu_utils.benchmark_image_generation(
        pipeline=pipe,
        num_images=3,
        steps=steps,
        callback=lambda m: progress(0.6, m),
    )

    report = [
        "### AMD Radeon GPU — Benchmark Results",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Device | {results['device_name']} |",
        f"| Warm-up | {results['warmup_seconds']}s |",
        f"| Avg. inference | {results['avg_seconds']}s |",
        f"| Fastest | {results['min_seconds']}s |",
        f"| Slowest | {results['max_seconds']}s |",
        f"| Throughput | {results['throughput_img_per_min']} img/min |",
        f"| Peak VRAM | {results['peak_vram_gb']} GB |",
        f"| ROCm Version | {gpu_utils.get_gpu_info()['rocm_version']} |",
    ]

    return "\n".join(report)


# ════════════════════════════════════════════════════════════════════════
#   GRADIO UI
# ════════════════════════════════════════════════════════════════════════

def build_ui():
    css_path = os.path.join(PROJECT_ROOT, "style.css")
    with open(css_path, "r") as f:
        custom_css = f.read()

    with gr.Blocks(
        title="Textovid — AI Comic Studio",
        css=custom_css,
        theme=gr.themes.Soft(
            primary_hue="cyan",
            secondary_hue="purple",
            neutral_hue="slate",
        ),
    ) as demo:

        # Hidden state for active tab
        mode_state = gr.Text(value="text", visible=False)

        # ── 4K VIDEO BACKGROUND ──────────────────────────────────────────
        gr.HTML("""
        <video autoplay muted loop playsinline id="bg-video"
               style="position:fixed; top:0; left:0; width:100vw; height:100vh;
                      object-fit:cover; z-index:-1; opacity:0.12; filter:brightness(0.4) saturate(1.5);">
          <source src="https://cdn.pixabay.com/video/2020/05/25/40130-424930032_large.mp4" type="video/mp4">
        </video>
        <div style="position:fixed; top:0; left:0; width:100%; height:100%; z-index:-1;
                    background: radial-gradient(ellipse at center, transparent 0%, rgba(8,8,24,0.7) 100%);
                    pointer-events:none;"></div>
        """)

        # ── HEADER ──────────────────────────────────────────────────────
        gr.HTML("""
        <div style="text-align:center; padding: 24px 0 10px 0; position:relative; z-index:1;">
            <h1 style="font-size: 3em; margin:0; color:#00f0ff;
                        text-shadow: 0 0 30px rgba(0,240,255,0.6), 0 0 60px rgba(0,240,255,0.25),
                                     0 0 100px rgba(139,92,246,0.15);
                        letter-spacing: 14px; font-family: 'Orbitron', 'Rajdhani', sans-serif;
                        animation: titleGlow 3s ease-in-out infinite alternate;">
                T E X T O V I D
            </h1>
            <p style="font-size: 1.05em; color: #9999cc; letter-spacing: 5px;
                       margin-top: 6px; font-family: 'Rajdhani', sans-serif;">
                AI-POWERED COMIC UNIVERSE GENERATOR
            </p>
            <p style="font-size: 0.85em; color: #666699; letter-spacing: 3px;
                       margin-top: 2px; font-family: 'Rajdhani', sans-serif;">
                AMD RADEON GPU &nbsp;&middot;&nbsp; ROCm &nbsp;&middot;&nbsp; STABLE DIFFUSION XL
            </p>
            <div style="height:2px; margin: 18px auto; max-width:700px;
                        background: linear-gradient(90deg, transparent, rgba(0,240,255,0.5),
                                                     rgba(139,92,246,0.4), transparent);
                        animation: lineGlow 4s ease-in-out infinite alternate;"></div>
        </div>
        """)

        # ── MAIN LAYOUT ─────────────────────────────────────────────────
        with gr.Row():

            # ── LEFT SIDEBAR ────────────────────────────────────────────
            with gr.Column(scale=3, min_width=340):

                # API Key
                with gr.Group(elem_classes=["hud-corner"]):
                    gr.Markdown("### 🔑 API Configuration")
                    api_key_input = gr.Textbox(
                        label="Radeon Cloud API Key",
                        placeholder="Paste your Token Factory key here...",
                        type="password",
                        info="Get free key: developer.amd.com.cn/radeon/modelapis",
                    )

                # Mode Tabs
                with gr.Tabs() as mode_tabs:
                    with gr.Tab("📝 Text Input") as tab_text:
                        text_input = gr.Textbox(
                            label="Story Premise",
                            placeholder=(
                                "e.g. A time-traveling baker accidentally becomes a pharaoh "
                                "in ancient Egypt, but the pyramids are actually giant bread ovens..."
                            ),
                            lines=5,
                            info="Describe your comic idea. The AI will expand it into a full script.",
                        )

                    with gr.Tab("🎲 Category Mode") as tab_cat:
                        with gr.Row():
                            cat_genre = gr.Dropdown(
                                choices=config.GENRES, value="Sci-Fi",
                                label="Genre", allow_custom_value=True,
                            )
                            cat_subgenre = gr.Dropdown(
                                choices=config.SUB_GENRES, value="Cyberpunk",
                                label="Sub-Genre", allow_custom_value=True,
                            )
                        cat_artstyle = gr.Dropdown(
                            choices=config.ART_STYLES,
                            value="Western Comic (Marvel/DC style)",
                            label="Art Style",
                        )
                        with gr.Row():
                            cat_theme = gr.Dropdown(
                                choices=config.THEMES, value="Discovery",
                                label="Theme",
                            )
                            cat_mood = gr.Dropdown(
                                choices=config.MOODS, value="Epic",
                                label="Mood",
                            )
                        cat_length = gr.Dropdown(
                            choices=list(config.LENGTHS.keys()),
                            value="Short  (3 pages)",
                            label="Comic Length",
                        )

                tab_text.select(fn=lambda: "text", outputs=mode_state)
                tab_cat.select(fn=lambda: "category", outputs=mode_state)

                # Generate Button
                generate_btn = gr.Button(
                    "⚡  G E N E R A T E  C O M I C",
                    variant="primary",
                    size="lg",
                )

                # Advanced Settings
                with gr.Accordion("⚙️ Advanced Settings", open=False):
                    adv_steps = gr.Slider(
                        5, 50, value=25, step=1,
                        label="Inference Steps (higher = quality, slower)",
                    )
                    adv_cfg = gr.Slider(
                        1.0, 15.0, value=7.5, step=0.5,
                        label="Guidance Scale (prompt adherence)",
                    )
                    adv_seed = gr.Slider(
                        -1, 999999, value=-1, step=1,
                        label="Seed (-1 = random)",
                    )
                    adv_highres = gr.Checkbox(
                        value=True, label="High-Res Fix (2x refiner, slower but sharper)",
                    )
                    adv_video = gr.Checkbox(
                        value=False, label="Enable Video Panels (LTX Video, experimental)",
                    )

                # Benchmark
                with gr.Group(elem_classes=["hud-corner"]):
                    bench_btn = gr.Button("📊 Run GPU Benchmark", variant="secondary")
                    bench_output = gr.Markdown("")

            # ── RIGHT: Output ───────────────────────────────────────────
            with gr.Column(scale=7):
                output_gallery = gr.Gallery(
                    label="Generated Comic Pages",
                    columns=2,
                    height=750,
                    object_fit="contain",
                )
                status_output = gr.Markdown(
                    value="*Generate a comic to see results here.*",
                )
                gpu_status = gr.Markdown(value=gpu_utils.format_gpu_status())

        # ── FOOTER ─────────────────────────────────────────────────────
        gr.HTML("""
        <div style="text-align:center; padding: 20px 0 12px 0; color: #555577;
                    font-size: 12px; letter-spacing: 1px; position:relative; z-index:1;">
            <div style="height:1px; margin-bottom: 14px; max-width:500px;
                        margin-left:auto; margin-right:auto;
                        background: linear-gradient(90deg, transparent, rgba(0,240,255,0.3),
                                                     rgba(139,92,246,0.3), transparent);"></div>
            <b style="color:#00d4e0;">TEXTOVID</b> &nbsp;&middot;&nbsp;
            AMD AI DevMaster Hackathon 2026 &nbsp;&middot;&nbsp; Track 1: Multimodal AI
            <br>
            <span style="color:#444466;">Built on AMD Radeon GPU + ROCm + Stable Diffusion XL + Qwen LLM</span>
        </div>
        """)

        # ── EVENT WIRING ────────────────────────────────────────────────
        generate_btn.click(
            fn=run_pipeline,
            inputs=[
                mode_state,
                text_input,
                cat_genre,
                cat_subgenre,
                cat_artstyle,
                cat_theme,
                cat_mood,
                cat_length,
                api_key_input,
                adv_steps,
                adv_cfg,
                adv_seed,
                adv_highres,
                adv_video,
            ],
            outputs=[output_gallery, status_output],
        )

        bench_btn.click(
            fn=run_benchmark,
            inputs=[adv_steps],
            outputs=[bench_output],
        )

    return demo


# ════════════════════════════════════════════════════════════════════════
#   ENTRY POINT
# ════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  TEXTOVID — AI Comic Studio")
    print("  AMD AI DevMaster Hackathon 2026 — Track 1")
    print("=" * 60)

    info = gpu_utils.get_gpu_info()
    print(f"\n  GPU: {info['device_name']}")
    print(f"  VRAM: {info['vram_free_gb']:.1f} / {info['vram_total_gb']:.1f} GB")
    print(f"  ROCm: {info['rocm_version']}")
    print(f"  Video: {'enabled' if config.VIDEO_ENABLED else 'disabled'}")
    print(f"  High-Res Fix: {'enabled' if config.HIGH_RES_FIX else 'disabled'}")
    print(f"  Page Size: {config.COMIC_PAGE_W}x{config.COMIC_PAGE_H}")
    print()

    demo = build_ui()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
    )