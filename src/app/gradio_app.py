from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import gradio as gr

from src.agent.agent import PrivateAgent
from src.agent.planner import build_task_plan
from src.agent.tools import ToolRegistry
from src.config import load_settings
from src.llm.backend import build_llm
from src.memory.memory import SessionMemory
from src.rag.store import VectorStore

# Self-contained styles (Gradio theme CSS often fails behind rc-tunnel).
TUNNEL_SAFE_CSS = """
:root {
  --bg: #0f172a;
  --panel: #111827;
  --card: #1f2937;
  --line: #334155;
  --text: #e5e7eb;
  --muted: #94a3b8;
  --accent: #14b8a6;
  --accent-2: #0d9488;
  --warn: #f59e0b;
}
body, .gradio-container {
  font-family: "IBM Plex Sans", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif !important;
  background:
    radial-gradient(1200px 500px at 10% -10%, rgba(20,184,166,.18), transparent 55%),
    radial-gradient(900px 420px at 100% 0%, rgba(245,158,11,.10), transparent 50%),
    var(--bg) !important;
  color: var(--text) !important;
}
.gradio-container {
  max-width: 980px !important;
  margin: 0 auto !important;
  padding: 22px 16px 40px !important;
}
.gr-group, .block, .form {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  margin: 0 0 12px 0 !important;
}
label, .label-wrap span {
  color: var(--muted) !important;
  font-size: 12px !important;
  letter-spacing: .04em !important;
  text-transform: uppercase !important;
  font-weight: 600 !important;
}
textarea, input, .scroll-hide textarea {
  background: var(--card) !important;
  color: var(--text) !important;
  border: 1px solid var(--line) !important;
  border-radius: 12px !important;
  padding: 12px 14px !important;
}
button {
  background: linear-gradient(180deg, var(--accent), var(--accent-2)) !important;
  color: #042f2e !important;
  border: 0 !important;
  border-radius: 10px !important;
  padding: 11px 18px !important;
  margin: 0 10px 10px 0 !important;
  font-weight: 700 !important;
  min-height: 42px !important;
  box-shadow: 0 8px 20px rgba(20,184,166,.25) !important;
}
button.secondary {
  background: #334155 !important;
  color: #e2e8f0 !important;
  box-shadow: none !important;
}
/* Hide Gradio giant placeholder icons */
.icon-wrap, .upload-container .icon, .empty .icon,
.block .icon-wrap, .wrap.center.full > .icon-wrap,
.file .icon, .upload-container > svg, .empty > svg {
  display: none !important;
}
.upload-container, .wrap.center.full {
  min-height: 64px !important;
  max-height: 96px !important;
  padding: 10px !important;
  background: var(--card) !important;
  border: 1px dashed var(--line) !important;
  border-radius: 12px !important;
}
footer { display: none !important; }
"""


def create_runtime() -> dict[str, Any]:
    settings = load_settings()
    upload_dir = settings.resolve(settings.paths.upload_dir)
    sample_dir = settings.resolve(settings.paths.sample_docs)
    upload_dir.mkdir(parents=True, exist_ok=True)
    sample_dir.mkdir(parents=True, exist_ok=True)

    store = VectorStore(settings)
    if store.count() == 0 and sample_dir.exists():
        store.add_directory(sample_dir)

    memory = SessionMemory(settings.resolve(settings.agent.memory_path))
    tools = ToolRegistry(store=store, memory=memory, upload_dir=upload_dir)
    llm = build_llm(settings.llm)
    agent = PrivateAgent(
        llm=llm,
        tools=tools,
        memory=memory,
        max_steps=settings.agent.max_steps,
    )
    return {
        "settings": settings,
        "store": store,
        "memory": memory,
        "agent": agent,
        "upload_dir": upload_dir,
    }


def format_trace(result) -> str:
    lines = [f"Tools used: {', '.join(result.used_tools) or '(none)'}"]
    for i, step in enumerate(result.steps, 1):
        lines.append(f"\n### Step {i}")
        lines.append(f"Model: {step.thought[:1200]}")
        if step.observation:
            lines.append(f"Observation: {step.observation[:1200]}")
    return "\n".join(lines)


def render_chat_html(history: list[tuple[str, str]]) -> str:
    if not history:
        return """
        <div style="border:1px solid #334155;border-radius:14px;background:#1f2937;padding:18px;min-height:220px;color:#94a3b8;">
          <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px;color:#14b8a6;">Chat</div>
          <div>还没有消息。在下方输入问题，例如：请假需要提前几天申请？</div>
        </div>
        """
    bubbles = []
    for q, a in history:
        bubbles.append(
            f"""
            <div style="margin:0 0 12px auto;max-width:88%;background:#0f766e;color:#ecfeff;
                        border-radius:14px 14px 4px 14px;padding:10px 12px;line-height:1.5;">
              <div style="font-size:11px;opacity:.8;margin-bottom:4px;">You</div>
              {escape(q)}
            </div>
            <div style="margin:0 0 16px 0;max-width:92%;background:#111827;border:1px solid #334155;color:#e5e7eb;
                        border-radius:14px 14px 14px 4px;padding:10px 12px;line-height:1.55;">
              <div style="font-size:11px;color:#14b8a6;margin-bottom:4px;">Agent</div>
              {escape(a)}
            </div>
            """
        )
    return f"""
    <div style="border:1px solid #334155;border-radius:14px;background:#1f2937;padding:14px;min-height:220px;max-height:420px;overflow:auto;">
      <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px;color:#14b8a6;">Chat</div>
      {''.join(bubbles)}
    </div>
    """


def build_ui() -> gr.Blocks:
    rt = create_runtime()
    settings = rt["settings"]
    store: VectorStore = rt["store"]
    agent: PrivateAgent = rt["agent"]
    upload_dir: Path = rt["upload_dir"]

    with gr.Blocks(title=settings.app.name) as demo:
        gr.HTML(
            f"""
            <div style="border:1px solid #334155;border-radius:16px;background:linear-gradient(180deg,#1f2937,#111827);
                        padding:18px 18px 16px;margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:end;">
                <div>
                  <div style="font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#14b8a6;margin-bottom:8px;">
                    AMD AI DevMaster · Track 2
                  </div>
                  <h1 style="margin:0;font-size:30px;line-height:1.15;color:#f8fafc;">{settings.app.name}</h1>
                  <p style="margin:10px 0 0;color:#94a3b8;line-height:1.55;max-width:620px;">
                    私有本地 Agent：知识库问答 · Tool Calling · 记忆 · 多步规划<br/>
                    Team <b style="color:#e2e8f0;">{settings.app.team}</b> · AMD Radeon / ROCm
                  </p>
                </div>
                <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:10px 12px;color:#cbd5e1;min-width:150px;">
                  <div style="font-size:11px;color:#94a3b8;letter-spacing:.08em;text-transform:uppercase;">KB Chunks</div>
                  <div style="font-size:28px;font-weight:700;color:#f59e0b;margin-top:2px;">{store.count()}</div>
                </div>
              </div>
            </div>
            """
        )

        chat_view = gr.HTML(value=render_chat_html([]))
        query = gr.Textbox(
            label="Question",
            placeholder="例如：请假需要提前几天申请？ / 记住我喜欢简洁中文回答",
            lines=2,
        )
        with gr.Row():
            send = gr.Button("Run Agent")
            clear = gr.Button("Clear", elem_classes=["secondary"])

        with gr.Row():
            plan_box = gr.Textbox(label="Task Plan", lines=5, scale=1)
            mem_view = gr.Textbox(label="Local Memory", lines=5, value=rt["memory"].recall(), scale=1)

        trace = gr.Textbox(label="Agent Trace", lines=7)
        status = gr.Textbox(
            label="Knowledge Base Status",
            value=f"KB chunks: {store.count()}",
            interactive=False,
        )

        gr.HTML(
            """
            <div style="margin:6px 0 2px;color:#94a3b8;font-size:12px;letter-spacing:.08em;text-transform:uppercase;">
              Upload Private Docs
            </div>
            """
        )
        files = gr.File(
            label="Drop .md / .txt / .pdf here",
            file_count="multiple",
            type="filepath",
            height=84,
        )
        with gr.Row():
            ingest_btn = gr.Button("Ingest Uploads")
            sample_btn = gr.Button("Re-ingest Samples", elem_classes=["secondary"])

        state = gr.State([])

        def on_send(message: str, hist: list):
            hist = list(hist or [])
            if not message or not str(message).strip():
                return render_chat_html(hist), hist, "", "", rt["memory"].recall(), f"KB chunks: {store.count()}"
            plan = "\n".join(f"{i+1}. {s}" for i, s in enumerate(build_task_plan(message)))
            result = agent.run(str(message).strip())
            hist = hist + [(str(message).strip(), result.answer)]
            return (
                render_chat_html(hist),
                hist,
                plan,
                format_trace(result),
                rt["memory"].recall(),
                f"KB chunks: {store.count()}",
            )

        def on_ingest(file_list):
            if not file_list:
                return f"KB chunks: {store.count()}", "No files selected."
            total = 0
            for fp in file_list:
                src = Path(fp)
                dst = upload_dir / src.name
                dst.write_bytes(src.read_bytes())
                total += store.add_file(dst)
            return f"KB chunks: {store.count()}", f"Ingested chunks: {total}"

        def on_sample():
            sample_dir = settings.resolve(settings.paths.sample_docs)
            n = store.add_directory(sample_dir)
            return f"KB chunks: {store.count()}", f"Sample chunks added: {n}"

        def on_clear():
            return (
                render_chat_html([]),
                [],
                "",
                "",
                rt["memory"].recall(),
                f"KB chunks: {store.count()}",
            )

        send.click(
            on_send,
            [query, state],
            [chat_view, state, plan_box, trace, mem_view, status],
        ).then(lambda: "", None, query)
        query.submit(
            on_send,
            [query, state],
            [chat_view, state, plan_box, trace, mem_view, status],
        ).then(lambda: "", None, query)
        ingest_btn.click(on_ingest, [files], [status, trace])
        sample_btn.click(on_sample, None, [status, trace])
        clear.click(on_clear, None, [chat_view, state, plan_box, trace, mem_view, status])

    return demo


def main() -> None:
    import os

    settings = load_settings()
    demo = build_ui()
    host = os.getenv("GRADIO_SERVER_NAME", settings.app.host)
    port = int(os.getenv("GRADIO_SERVER_PORT", str(settings.app.port)))
    share = os.getenv("GRADIO_SHARE", "0") == "1"
    root_path = os.getenv("GRADIO_ROOT_PATH", "")
    launch_kwargs: dict[str, Any] = {
        "server_name": host,
        "server_port": port,
        "share": share,
        "ssr_mode": False,
        "css": TUNNEL_SAFE_CSS,
    }
    if root_path:
        launch_kwargs["root_path"] = root_path
    demo.launch(**launch_kwargs)


if __name__ == "__main__":
    main()
