"""MeshSmith Gradio app.

    python app.py [--host 0.0.0.0] [--port 7860]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import gradio as gr

from meshsmith.device import device_banner
from meshsmith.pipeline import MeshSmith
from meshsmith.presets import MATERIAL_PRESETS, PRESETS

BANNER = device_banner()
IS_AMD = BANNER["backend"].startswith("AMD")
SMITH = MeshSmith(output_root=Path(__file__).resolve().parent / "outputs")

ACCENT = "#ED1C24" if IS_AMD else "#76b900"
HEADER = f"""
<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap">
  <h1 style="margin:0">⚒️ MeshSmith</h1>
  <span style="opacity:.75">text or image → print-ready &amp; game-ready 3D assets, fully local</span>
</div>
<div style="margin-top:6px;padding:6px 10px;border-left:4px solid {ACCENT};background:rgba(128,128,128,.08)">
  Running on <b>{BANNER['gpu']}</b> · {BANNER['backend']} · torch {BANNER['torch']} · {BANNER['vram_gb']} GB VRAM
</div>
"""


def forge(prompt, image, quality, material, height_mm, seed, progress=gr.Progress()):
    if not prompt and image is None:
        raise gr.Error("Type a prompt or drop an image (or both).")

    def notify(frac, desc):
        progress(frac, desc=desc)

    result = SMITH.run(
        prompt=prompt or None,
        image=image,
        preset=quality,
        seed=int(seed),
        height_mm=float(height_mm),
        material=material,
        progress=notify,
    )
    paths = result["paths"]
    pr = result["print"]
    summary = (
        f"### Printability {pr['score']}/100 — {pr['verdict']}\n"
        f"Auto-orientation saved **{pr['orientation'].get('support_saved_pct', 0)}%** support material · "
        f"watertight: **{pr['watertight']}** · {result['raw_faces']:,} → "
        f"{result['cleanup']['faces_after']:,} faces\n\n"
        + result["timings_markdown"]
    )
    files = [paths["glb"], paths["stl"], paths["obj"], paths["report_md"], paths["report_json"]]
    return paths["cutout"], paths["glb"], summary, files, result


def build_app() -> gr.Blocks:
    with gr.Blocks(title="MeshSmith — local 3D asset foundry") as app:
        gr.HTML(HEADER)
        with gr.Row():
            with gr.Column(scale=1):
                prompt = gr.Textbox(
                    label="Prompt",
                    placeholder="a chess knight piece, ornate, baroque style",
                    lines=2,
                )
                image = gr.Image(label="…or start from an image", type="pil", height=220)
                with gr.Row():
                    quality = gr.Dropdown(list(PRESETS), value="standard", label="Quality")
                    material = gr.Dropdown(list(MATERIAL_PRESETS), value="clay", label="Material")
                with gr.Row():
                    height_mm = gr.Slider(20, 220, value=80, step=5, label="Print height (mm)")
                    seed = gr.Number(value=1234, label="Seed", precision=0)
                go = gr.Button("Forge it", variant="primary")
                cutout = gr.Image(label="Cutout used for 3D", height=220)
            with gr.Column(scale=2):
                viewer = gr.Model3D(label="Asset (drag to orbit)", height=420)
                summary = gr.Markdown()
                downloads = gr.File(label="Downloads (GLB · STL · OBJ · report)", file_count="multiple")
                with gr.Accordion("Full run details (JSON)", open=False):
                    details = gr.JSON()

        go.click(
            forge,
            inputs=[prompt, image, quality, material, height_mm, seed],
            outputs=[cutout, viewer, summary, downloads, details],
        )

        gr.Markdown(
            "MeshSmith runs **entirely locally** — SDXL-Turbo, u2net and Hunyuan3D-2 "
            "on your own GPU. No cloud APIs. Built for the AMD AI DevMaster Hackathon."
        )
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    build_app().queue(max_size=8).launch(server_name=args.host, server_port=args.port)
