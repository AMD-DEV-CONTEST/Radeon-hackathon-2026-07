"""Gradio application factory and entrypoint.

Why a factory: lets the UI be embedded into FastAPI in production
(via `gradio.mount_gradio_app`) and run standalone in dev.
"""
from __future__ import annotations

import logging
from typing import Any

from src.config import log


def build_demo() -> Any:
    """Build the top-level Gradio `Blocks` with the LibLibAI-style layout.

    D1 placeholder: a single tab that says hello. D5 fills in the real
    sidebar + 3 capability pages (text2image / img2img / style_transfer).
    """
    import gradio as gr

    with gr.Blocks(title="AMD Radeon Studio", theme=gr.themes.Soft()) as demo:
        gr.Markdown(
            """
            # 🎬 AMD Radeon Studio
            **多模态 AI 创作工坊** · 文生图 / 图生图 / 风格迁移
            """
        )
        with gr.Tabs():
            with gr.Tab("🏠 Home"):
                gr.Markdown(
                    "D1 骨架版 · D2-D4 会补齐三个功能页 · D5 上线完整 UI"
                )

    log.info("gradio demo built (D1 placeholder)")
    return demo


def run() -> None:  # pragma: no cover — exercised by `radeon-studio-ui` script
    """CLI entrypoint: `uv run radeon-studio-ui`."""
    demo = build_demo()
    demo.queue().launch(server_name="0.0.0.0", server_port=7860)


if __name__ == "__main__":  # pragma: no cover
    run()
