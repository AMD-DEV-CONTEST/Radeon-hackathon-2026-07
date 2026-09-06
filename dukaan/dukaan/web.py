"""A shop counter in a browser tab.

The CLI is the honest interface for a developer and a terrible one for the
person this is actually for. A seller has a photo on their phone, a price in
their head, and no reason to learn flags.

The interesting half of this file is not the form, it is the scrubber.

Because the only generative model on the box is a video model, a pack is not
three renders. It is one generated scene and three moments lifted out of it.
That means every other moment is already sitting on disk, paid for, and
recomposing a creative from a different one costs no GPU at all. So the seller
gets to choose the frame: drag the slider, watch the ad rebuild, and never wait
for the model again. A tool built on an image model cannot offer that, because
it would have to generate each candidate.

Nothing here does generation. It calls `build_pack`, the same path the CLI
takes, so the two surfaces cannot disagree about what the tool does.
"""
from __future__ import annotations

from pathlib import Path

import gradio as gr
from PIL import Image

from .backend import make_backend
from .config import Config, load
from .frames import fit_scene
from .layout import compose, contact_strip
from .pack import build_pack
from .spec import FORMATS, FORMATS_BY_NAME, STYLES, STYLES_BY_NAME, Brief

#: What each style looks like, in words a seller would use rather than prompt
#: fragments.
STYLE_BLURB = {
    "studio": "clean catalogue white, for marketplaces",
    "festive": "warm reds and marigold, string lights, for Diwali",
    "daylight": "pale wood and soft morning light, honest and everyday",
    "midnight": "dark and premium, single rim light",
}


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name.strip()).strip("-") or "product"


def build_ui(cfg: Config | None = None) -> gr.Blocks:
    cfg = cfg or load()

    with gr.Blocks(title="Dukaan") as ui:
        gr.Markdown(
            "# Dukaan\n"
            "One product photo in, a shop's worth of ready-to-post creatives out.\n\n"
            + (
                f"Generating on an AMD Radeon GPU: {cfg.width}x{cfg.height}, "
                f"{cfg.frames} frames, one pass for the whole pack."
                if not cfg.offline
                else "**No GPU configured**, so this is the CPU preview backend. "
                "Set `DUKAAN_INSTANCE` for real generation."
            )
        )

        # Frames and brief survive between the generate call and the scrubber,
        # which is what makes re-composing free.
        state = gr.State({})

        with gr.Row():
            with gr.Column(scale=2):
                photo = gr.Image(label="Your product photo", type="pil", height=250)
                headline = gr.Textbox(label="Headline", placeholder="Handmade brass ewer")
                subline = gr.Textbox(label="Price or offer", placeholder="1,450 rupees, free delivery")
                contact = gr.Textbox(label="Phone or handle", placeholder="+91 90000 00000")
                style = gr.Radio([s.name for s in STYLES], value="festive", label="Look",
                                 info=" · ".join(f"{k}: {v}" for k, v in STYLE_BLURB.items()))
                go = gr.Button("Make my pack", variant="primary")
                status = gr.Markdown("")

            with gr.Column(scale=3):
                gallery = gr.Gallery(label="Your pack", columns=3, height=360, object_fit="contain")
                detail = gr.Markdown("")

        gr.Markdown("---\n### Not the moment you wanted?")
        gr.Markdown(
            "The GPU generated a whole scene, not three pictures, so every frame of it is "
            "already paid for. Pick a different one and the creative rebuilds on the CPU. "
            "**No further GPU time, no waiting for the model.**"
        )
        with gr.Row():
            with gr.Column(scale=1):
                fmt_pick = gr.Radio([f.name for f in FORMATS], value="square", label="Which creative")
                frame_pick = gr.Slider(0, 1, value=0, step=1, label="Moment", interactive=False)
                recost = gr.Markdown("")
            with gr.Column(scale=2):
                preview = gr.Image(label="Preview", height=420)

        def run(photo, headline, subline, contact, style, progress=gr.Progress()):
            if photo is None:
                return None, "Pick a photo first.", "", {}, gr.update(interactive=False), None, ""
            if not (headline or "").strip():
                return None, "Give it a headline. It goes on the creative.", "", {}, gr.update(interactive=False), None, ""

            steps: list[str] = []

            def on_step(msg: str) -> None:
                steps.append(msg)
                progress(min(len(steps) / 7, 0.95), desc=msg)

            brief = Brief(product=_slug(headline), headline=headline.strip(),
                          subline=(subline or "").strip(), style=style)
            try:
                result = build_pack(cfg, make_backend(cfg), photo, brief,
                                    contact=(contact or "").strip(), on_step=on_step)
            except Exception as exc:  # surfaced, never swapped for a fake result
                return None, f"**Generation failed.** {exc}", "", {}, gr.update(interactive=False), None, ""

            shots = [(str(p), f"{n} · moment {result.frame_of.get(n, '?')}")
                     for n, p in result.creatives.items()]
            meta = result.meta or {}
            n_frames = len(result.clip_frames)
            lines = [f"**{len(shots)} creatives** from **one** pass on `{result.backend}`."]
            if meta.get("seconds"):
                size = meta.get("size", ["?", "?"])
                lines.append(f"GPU time **{meta['seconds']}s** for {meta.get('frames', '?')} frames "
                             f"at {size[0]}x{size[1]}. Every remaining moment is free.")
            st = {
                "frames": [str(p) for p in result.clip_frames],
                "headline": brief.headline, "subline": brief.subline,
                "contact": (contact or "").strip(), "style": style,
                "chosen": dict(result.frame_of),
            }
            return (
                shots, "Done.", "\n\n".join(lines), st,
                gr.update(maximum=max(n_frames - 1, 1), value=result.frame_of.get("square", 0),
                          interactive=n_frames > 1),
                None, "",
            )

        def recompose(st, fmt_name, idx):
            """Rebuild one creative from a different moment. CPU only."""
            if not st or not st.get("frames"):
                return None, ""
            idx = int(idx)
            frames = st["frames"]
            if not (0 <= idx < len(frames)):
                return None, ""
            fmt = FORMATS_BY_NAME[fmt_name]
            style = STYLES_BY_NAME[st["style"]]
            brief = Brief(product="preview", headline=st["headline"],
                          subline=st["subline"], style=st["style"])
            frame = Image.open(frames[idx]).convert("RGB")
            out = compose(fit_scene(frame, fmt.size), brief, fmt, style)
            out = contact_strip(out, st["contact"], style)
            was = st["chosen"].get(fmt_name)
            note = f"Rebuilt **{fmt_name}** from moment **{idx}**"
            if was is not None and idx != was:
                note += f" instead of {was}"
            return out, note + ". **0 seconds of GPU.**"

        go.click(run, inputs=[photo, headline, subline, contact, style],
                 outputs=[gallery, status, detail, state, frame_pick, preview, recost])
        for control in (frame_pick, fmt_pick):
            control.change(recompose, inputs=[state, fmt_pick, frame_pick],
                           outputs=[preview, recost])

        examples = sorted(Path("examples").glob("*.png")) if Path("examples").is_dir() else []
        if examples:
            gr.Examples(examples=[[str(p)] for p in examples if p.name != "pot.png"],
                        inputs=[photo], label="Example photos (CC0, see examples/CREDITS.md)")

    return ui
