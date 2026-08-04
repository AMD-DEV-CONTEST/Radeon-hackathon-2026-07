"""
Nova — Gradio chat UI.

Run after the local inference server is up and the vector store is built:
    python app.py

This is what you'll show in the demo video: real questions, answered from
locally indexed documents, tool calls, and remembered context — all running
on the AMD Radeon GPU.
"""
from __future__ import annotations

import logging

import gradio as gr

import config
from src.agent import NovaAgent

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

agent = NovaAgent()


def respond(message: str, history: list[dict]) -> str:
    try:
        result = agent.ask(message)
    except RuntimeError as exc:
        return f"⚠️ {exc}"
    answer = result["answer"]
    if result["sources"]:
        answer += f"\n\n_Sources: {', '.join(result['sources'])}_"
    return answer


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Nova — Private Local Research Assistant") as demo:
        gr.Markdown(
            "# 🔒 Nova — Private Local Research Assistant\n"
            f"Running fully locally on an AMD Radeon GPU (ROCm). "
            f"Knowledge base: `{config.DATA_DIR}` · "
            f"Vector DB: `{config.VECTOR_DB_DIR}`"
        )
        gr.ChatInterface(
            fn=respond,
            examples=[
                "List the files you have access to",
                "Calculate: (24 * 7) + 15",
                "What does the sample document say about ROCm?",
            ],
        )
    return demo


if __name__ == "__main__":
    if not agent.llm.health_check():
        logging.warning(
            "Local inference server not reachable at %s — chat requests will "
            "fail until it's running. See README > Running the model server.",
            config.LLM_SERVER_BASE_URL,
        )
    ui = build_ui()
    ui.launch(server_name="0.0.0.0", server_port=7860)
