from __future__ import annotations

import os

import gradio as gr

from src.device import detect_device, vram_profile
from src.orchestrator import JobState, generate_card_job, revise_job
from src.paths import ensure_runtime_dirs
from src.world import load_world

ensure_runtime_dirs()
WORLD = load_world()
DEVICE = detect_device()
AFFINITY_CHOICES = ["Auto"] + WORLD.affinity_names()


CSS = """
.gradio-container {max-width: 1200px !important;}
footer {display: none !important;}
#title {font-size: 1.6rem; font-weight: 700;}
#tagline {opacity: 0.8;}
#badge {color: #7dd3fc;}
"""


def _pref(affinity: str) -> str | None:
    if not affinity or affinity == "Auto":
        return None
    return affinity


def ui_generate(brief, ref, affinity, progress=gr.Progress(track_tqdm=False)):
    if not (brief or "").strip():
        raise gr.Error("Please describe your character first")

    states = []

    def cb(state: JobState, msg: str):
        states.append(f"{state.value}: {msg}")
        progress(len(states) / 5.0, desc=msg)

    result = generate_card_job(
        user_text=brief,
        affinity_pref=_pref(affinity),
        ref_image=ref,
        mock=None,
        progress_cb=cb,
    )
    if result.state == JobState.FAILED:
        raise gr.Error(result.error or "Generation failed")

    status = " -> ".join(states) if states else result.state.value
    return (
        result.job_id,
        str(result.card_path) if result.card_path else None,
        result.lore_md,
        status,
    )


def ui_revise(job_id, instruction, progress=gr.Progress(track_tqdm=False)):
    if not job_id:
        raise gr.Error("Generate a character card first")
    if not (instruction or "").strip():
        raise gr.Error("Please enter a revision instruction")

    def cb(state: JobState, msg: str):
        progress(0.5, desc=msg)

    result = revise_job(job_id, instruction, mock=None, progress_cb=cb)
    if result.state == JobState.FAILED:
        raise gr.Error(result.error or "Revision failed")
    return (
        str(result.card_path) if result.card_path else None,
        result.lore_md,
        f"revised: {result.state.value}",
    )


def build_app() -> gr.Blocks:
    profile = vram_profile(DEVICE)
    with gr.Blocks(title=f"{WORLD.world_name} - Character Workshop") as demo:
        gr.Markdown(
            f"<div id='title'>{WORLD.world_name} - Character Workshop</div>"
            f"<div id='tagline'>{WORLD.tagline}</div>"
            f"<div id='badge'>Local | ROCm/AMD | device={DEVICE.name} | profile={profile} | mock={DEVICE.mock_mode}</div>"
        )
        job_id = gr.State("")

        with gr.Row():
            with gr.Column(scale=4):
                brief = gr.Textbox(
                    label="Describe your character",
                    lines=8,
                    placeholder="Appearance, personality, ability hints... (original characters only - no third-party IP names)",
                )
                ref = gr.Image(label="Reference image (optional)", type="pil")
                affinity = gr.Dropdown(
                    label="Affinity preference", choices=AFFINITY_CHOICES, value="Auto"
                )
                btn = gr.Button("Generate Character Card", variant="primary")
                revise_txt = gr.Textbox(
                    label="Revise this result", placeholder="e.g. change to short golden hair"
                )
                btn_rev = gr.Button("Apply Revision")
            with gr.Column(scale=6):
                card_img = gr.Image(label="Character Card", type="filepath")
                lore = gr.Markdown(label="Lore")
                status = gr.Textbox(label="Progress", interactive=False)

        btn.click(
            ui_generate,
            inputs=[brief, ref, affinity],
            outputs=[job_id, card_img, lore, status],
        )
        btn_rev.click(
            ui_revise,
            inputs=[job_id, revise_txt],
            outputs=[card_img, lore, status],
        )

        gr.Markdown(
            "Powered by **AMD Radeon + ROCm** local inference | "
            f"World: {WORLD.world_name} | Track 1 Multimodal"
        )
    return demo


if __name__ == "__main__":
    ensure_runtime_dirs()
    app = build_app()
    app.launch(
        server_name="127.0.0.1",
        server_port=int(os.environ.get("PORT", "7860")),
        css=CSS,
    )
