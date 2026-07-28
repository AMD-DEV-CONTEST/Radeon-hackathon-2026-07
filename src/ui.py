"""
Optional Gradio web UI for OmniKernel-ROCm.

Provides a cleaner demo experience than the CLI for the hackathon video.
Run with: python -m src.ui

Requires: pip install gradio
"""

import os
import sys
from pathlib import Path

try:
    import gradio as gr
    GRADIO_AVAILABLE = True
except ImportError:
    GRADIO_AVAILABLE = False

from src.orchestrator import Orchestrator
from src.llm import LLMClient, LLMConfig, MockLLMClient


def build_demo(
    orch: Orchestrator,
) -> "gr.Blocks":
    """Build the Gradio interface."""

    with gr.Blocks(
        title="OmniKernel-ROCm",
    ) as demo:

        gr.HTML("""
        <div class="header">
            <h1>🔥 OmniKernel-ROCm</h1>
            <p class="subheader">Local ROCm/HIP Performance Diagnosis Agent · AMD AI DevMaster Hackathon 2026</p>
        </div>
        """)

        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    label="Diagnosis Session",
                    elem_classes=["chatbot"],
                    show_label=True,
                )
                with gr.Row():
                    msg_box = gr.Textbox(
                        placeholder="Describe your slow workload, push back on a diagnosis, or say 'benchmark it'...",
                        label="",
                        scale=8,
                        container=False,
                    )
                    send_btn = gr.Button("Send", variant="primary", scale=1)

                with gr.Row():
                    clear_btn = gr.Button("New Session", variant="secondary")
                    history_btn = gr.Button("Show History")
                    audit_btn = gr.Button("Audit Log")

            with gr.Column(scale=1):
                gr.Markdown("### Session Info")
                codebase_box = gr.Textbox(
                    value=orch._codebase_path,
                    label="Codebase Path",
                    interactive=True,
                )
                fingerprint_box = gr.Textbox(
                    label="Codebase Fingerprint",
                    value="(start session to compute)",
                    interactive=False,
                )
                mode_indicator = gr.Markdown(
                    f"**Mode**: {'🟡 Mock' if orch.mock_tools else '🟢 Real GPU'}"
                )

                gr.Markdown("### Quick Commands")
                gr.Markdown("""
                - Type a description → diagnosis
                - *"that's not right..."* → pushback
                - *"benchmark it"* → measure both
                - *"apply the fix"* → save .patch
                - *"reject"* → discard proposal
                """)

                gr.Markdown("### Tool Status")
                tool_status = gr.Markdown("*(not yet queried)*")

        # ------------------------------------------------------------------
        # Event handlers
        # ------------------------------------------------------------------

        def respond(message: str, history: list) -> tuple:
            """Process user message and return updated chat history."""
            if not message.strip():
                return history, ""

            # Initialize session if needed
            if orch.session is None:
                orch.start_session()

            response = orch.handle_turn(message)
            history = history + [[message, response]]

            # Update fingerprint display
            fp = orch.session.codebase_fingerprint if orch.session else "—"
            return history, ""

        def update_fingerprint():
            if orch.session:
                return orch.session.codebase_fingerprint
            return "(no active session)"

        def start_new_session(codebase_path: str):
            orch.start_session(codebase_path or ".")
            fp = orch.session.codebase_fingerprint
            return [], f"New session started for: {codebase_path}\nFingerprint: {fp}"

        def show_history():
            if not orch.session:
                return "No active session."
            return orch.memory.summarize_history(orch.session.codebase_fingerprint)

        def show_audit():
            log = orch.gate.get_audit_log()
            if not log:
                return "No audit entries yet."
            lines = [f"[{e['action_type']}] → {e['status']} | target: {e['target']}" for e in log]
            return "\n".join(lines)

        def get_tool_status():
            from src.tools.rocm_smi import run_rocm_smi, format_smi_summary
            smi = run_rocm_smi(mock=orch.mock_tools)
            summary = format_smi_summary(smi)
            return f"**rocm-smi:**\n```\n{summary}\n```"

        # Wire up events
        send_btn.click(
            fn=respond,
            inputs=[msg_box, chatbot],
            outputs=[chatbot, msg_box],
        )
        msg_box.submit(
            fn=respond,
            inputs=[msg_box, chatbot],
            outputs=[chatbot, msg_box],
        )
        clear_btn.click(
            fn=start_new_session,
            inputs=[codebase_box],
            outputs=[chatbot, fingerprint_box],
        )
        history_btn.click(
            fn=show_history,
            outputs=[tool_status],
        )
        audit_btn.click(
            fn=show_audit,
            outputs=[tool_status],
        )

        # Auto-refresh tool status on load
        demo.load(fn=get_tool_status, outputs=[tool_status])

    return demo


def main():
    if not GRADIO_AVAILABLE:
        print("Gradio is not installed. Run: pip install gradio")
        sys.exit(1)

    import argparse
    parser = argparse.ArgumentParser(description="OmniKernel-ROCm Web UI")
    parser.add_argument("--codebase", default=".", help="Codebase path")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--mock-llm", action="store_true", dest="mock_llm")
    parser.add_argument("--llm-url", default="http://localhost:8000/v1", dest="llm_url")
    parser.add_argument("--llm-model", default="qwen2.5-coder-7b-instruct", dest="llm_model")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true", help="Create public Gradio share link")
    args = parser.parse_args()

    # Build LLM client
    if args.mock_llm or args.mock:
        llm_client = MockLLMClient()
    else:
        config = LLMConfig(base_url=args.llm_url, model=args.llm_model)
        llm_client = LLMClient(config=config)
        health = llm_client.health_check()
        if health["status"] != "ok":
            print(f"[WARNING] LLM server not reachable. Using mock mode.")
            llm_client = MockLLMClient()

    orch = Orchestrator(
        codebase_path=args.codebase,
        llm_client=llm_client,
        mock_tools=args.mock,
    )

    demo = build_demo(orch)
    print(f"\n[OmniKernel] Web UI starting on http://localhost:{args.port}")
    demo.launch(
        server_port=args.port,
        share=args.share,
    )


if __name__ == "__main__":
    main()
