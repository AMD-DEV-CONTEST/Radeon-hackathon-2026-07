"""
Gradio web interface for RadeonAgents.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import gradio as gr
import yaml

# Ensure project root is on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.llm import LLMEngine
from src.core.agent import Agent
from src.core.memory import MemoryManager
from src.core.tools import ToolRegistry
from src.multi_agent.orchestrator import MultiAgentOrchestrator
from src.rag.local_rag import LocalRAG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_config():
    config_path = ROOT / "config" / "default.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def create_system(cfg):
    print("Initializing RadeonAgents system (this may take a moment)...")
    llm = LLMEngine(
        model_name=cfg["model"]["name"],
        quantize=cfg["model"]["quantize"],
        device=cfg["model"]["device"],
        max_new_tokens=cfg["model"]["max_new_tokens"],
        temperature=cfg["model"]["temperature"],
        top_p=cfg["model"].get("top_p", 0.9),
    )

    rag = LocalRAG(
        persist_path=cfg["rag"]["persist_path"],
        embedding_model=cfg["rag"]["embedding_model"],
        chunk_size=cfg["rag"]["chunk_size"],
        chunk_overlap=cfg["rag"]["chunk_overlap"],
    )

    # Auto-ingest sample docs if present
    sample_dir = ROOT / "data" / "sample_docs"
    if sample_dir.exists() and rag.count() == 0:
        print("Ingesting sample documents...")
        rag.ingest_folder(sample_dir)

    tools = ToolRegistry(
        enable_python=cfg["tools"]["enable_python"],
        enable_web=cfg["tools"]["enable_web"],
        enable_fs=cfg["tools"]["enable_fs"],
        enable_rag=cfg["tools"]["enable_rag"],
        rag_instance=rag,
        workspace_root=str(ROOT),
    )

    memory = MemoryManager(
        max_history=cfg["memory"]["max_history"],
        vector_store_path=cfg["memory"]["vector_store_path"],
    )

    agent = Agent(
        llm=llm,
        tools=tools,
        memory=memory,
        name="RadeonAgent",
        max_iterations=cfg["agent"]["max_iterations"],
        verbose=cfg["agent"]["verbose"],
    )

    orchestrator = MultiAgentOrchestrator(
        llm=llm,
        tools=tools,
        memory=memory,
        verbose=cfg["agent"]["verbose"],
    )

    return llm, agent, orchestrator, rag


def build_ui(llm, agent, orchestrator, rag):
    def respond(message: str, history: list, mode: str):
        if not message.strip():
            return "Please enter a goal or question."
        try:
            if mode == "Multi-Agent":
                answer = orchestrator.run(message)
            else:
                answer = agent.run(message, use_planner=True)
            stats = llm.get_stats()
            footer = (
                f"\n\n---\n"
                f"**Device**: `{stats.get('gpu_name', stats.get('device', 'cpu'))}` | "
                f"**VRAM**: {stats.get('vram_allocated_gb', 'n/a')} GB allocated"
            )
            return answer + footer
        except Exception as e:
            logger.exception("Error during generation")
            return f"Error: {type(e).__name__}: {e}"

    def ingest_files(files):
        if not files:
            return "No files uploaded."
        count = 0
        for f in files:
            count += rag.ingest_file(f.name)
        return f"Successfully ingested {count} chunks from {len(files)} file(s). Knowledge base now has {rag.count()} chunks."

    theme = gr.themes.Soft(
        primary_hue="orange",
        secondary_hue="slate",
    )

    with gr.Blocks(theme=theme, title="RadeonAgents") as demo:
        gr.Markdown(
            """
            # 🚀 RadeonAgents
            **Intelligent Local Multi-Agent System optimized for AMD Radeon + ROCm**

            Reasoning • Hierarchical Planning • Tool Use • Memory • Multi-Agent • Local RAG
            """
        )

        with gr.Tab("Chat"):
            chatbot = gr.ChatInterface(
                fn=respond,
                additional_inputs=[
                    gr.Radio(
                        choices=["Single Agent", "Multi-Agent"],
                        value="Single Agent",
                        label="Execution Mode",
                    )
                ],
                examples=[
                    ["Create a prioritized daily plan for a developer who has 2 meetings, needs to finish a PR review, and wants to exercise."],
                    ["Write a Python function that computes the nth Fibonacci number using memoization and explain the time complexity."],
                    ["What is hierarchical task planning in AI agents? Summarize the key ideas."],
                    ["List the files in the current project and summarize the purpose of the main modules."],
                ],
                title=None,
            )

        with gr.Tab("Knowledge Base (RAG)"):
            gr.Markdown("Upload local documents (.txt, .md, .py, etc.) to build a private knowledge base.")
            file_upload = gr.File(file_count="multiple", label="Upload documents")
            ingest_btn = gr.Button("Ingest into RAG", variant="primary")
            ingest_output = gr.Textbox(label="Status", lines=3)
            ingest_btn.click(fn=ingest_files, inputs=file_upload, outputs=ingest_output)

        with gr.Tab("System Info"):
            stats = llm.get_stats()
            info = "\n".join(f"**{k}**: `{v}`" for k, v in stats.items())
            gr.Markdown(f"### Current LLM Engine\n{info}\n\n### Available Tools\n```\n{agent.tools.get_tool_descriptions()}\n```")

    return demo


def main():
    cfg = load_config()
    llm, agent, orchestrator, rag = create_system(cfg)
    demo = build_ui(llm, agent, orchestrator, rag)
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)


if __name__ == "__main__":
    main()
