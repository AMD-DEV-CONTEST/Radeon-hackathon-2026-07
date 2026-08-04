"""RadeonPilot Gradio Ops Console.

A local operations console for multi-agent ROCm inference ops on an AMD Radeon
GPU. Binds to 127.0.0.1 by default. Run modes:
- RADEONPILOT_MODE=demo  labelled synthetic mode (no GPU required)
- RADEONPILOT_MODE=pi    real Pi multi-agent sessions over a local ROCm endpoint
"""

from __future__ import annotations

import json
import os

import gradio as gr

from radeonpilot import __version__
from radeonpilot import tools
from radeonpilot.orchestrator import OpsOrchestrator

KNOWLEDGE_PATH = os.environ.get("RADEONPILOT_KNOWLEDGE", "data/knowledge")
DB_PATH = os.environ.get("RADEONPILOT_DB", "runtime/radeonpilot.sqlite3")

orchestrator = OpsOrchestrator(knowledge_path=KNOWLEDGE_PATH, db_path=DB_PATH)


def attestation_badge(runtime: dict) -> str:
    if runtime.get("radeon_attested"):
        return "RADEON ATTESTED"
    if runtime.get("mode") == "demo":
        return "DEMO (GPU UNATTESTED)"
    return "GPU UNATTESTED"


def run_ops(message: str, history: list, session_id: str | None, role: str):
    run = orchestrator.run(user_message=message or "", role=role or "operator", session_id=session_id or None)
    reply_lines = [f"**[{run.mode.upper()}] {attestation_badge(run.runtime)}** — session `{run.session_id}`", "", run.summary or ""]
    if run.action_plan:
        reply_lines += ["", "### Action plan"]
        for step in run.action_plan:
            flag = "DANGEROUS" if step.get("dangerous") else "safe"
            reply_lines.append(
                f"- `{step.get('step_id')}` [{step.get('status')}/{flag}] ({step.get('owner')}): {step.get('description')}"
            )
    if run.error:
        reply_lines += ["", f"> Error: {run.error}"]
    agent_md = render_agents(run.reports)
    evidence_md = render_evidence(run.evidence)
    return (
        history + [{"role": "user", "content": message}, {"role": "assistant", "content": "\n".join(reply_lines)}],
        run.session_id,
        agent_md,
        evidence_md,
    )


def render_agents(reports) -> str:
    if not reports:
        return "_No agent reports yet._"
    lines = []
    for report in reports:
        status = "ok" if report.ok else "FAILED"
        lines.append(f"#### {report.role} ({report.key}) — {status}, {report.duration_ms} ms")
        if report.parsed:
            findings = report.parsed.get("findings", [])
            for finding in findings[:6]:
                lines.append(f"- {finding}")
            actions = report.parsed.get("recommended_actions", [])
            if actions:
                lines.append("- Recommended: " + "; ".join(str(a) for a in actions[:4]))
        elif report.error:
            lines.append(f"> {report.error}")
        lines.append("")
    return "\n".join(lines)


def render_evidence(evidence: list) -> str:
    if not evidence:
        return "_No local evidence matched._"
    lines = []
    for item in evidence:
        doc_id = item.get("metadata", {}).get("document_id", item["source"])
        lines.append(f"**{doc_id}** (score {item['score']})\n> {item['quote']}\n")
    return "\n".join(lines)


def diagnose():
    env = tools.gpu_environment()
    endpoint = tools.endpoint_status()
    return (
        f"### GPU environment\n```json\n{json.dumps(env.data, indent=2)[:2000]}\n```\n"
        f"### Endpoint\n```json\n{json.dumps(endpoint.data, indent=2)[:1200]}\n```"
    )


def search_knowledge(query: str) -> str:
    results = orchestrator.rag.search(query or "rocm", limit=5)
    return render_evidence([item.to_dict() for item in results])


def runtime_panel():
    mode = orchestrator.mode
    lines = [f"- Version: {__version__}", f"- Mode: **{mode}**"]
    if mode == "pi":
        try:
            from radeonpilot.pi_bridge import PiBridgeClient

            health = PiBridgeClient().health()
            runtime = health.get("runtime", {})
            lines.append(f"- Pi SDK: {health.get('pi', {}).get('package')} {health.get('pi', {}).get('version')}")
            lines.append(f"- Model: {health.get('model', {}).get('provider')}/{health.get('model', {}).get('id')}")
            lines.append(f"- Attestation: **{attestation_badge(runtime)}**")
            if runtime.get("gpu_name"):
                lines.append(f"- GPU: {runtime['gpu_name']}")
            if runtime.get("rocm_version"):
                lines.append(f"- ROCm: {runtime['rocm_version']}")
            if runtime.get("attestation_error"):
                lines.append(f"- Note: {runtime['attestation_error']}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"- Pi bridge unreachable: {exc}")
    else:
        lines.append("- GPU UNATTESTED (demo mode performs no Radeon inference)")
    audit = "\n".join(
        f"- [{item['event']}] {item['session_id'] or '-'}: {item['detail'] or ''}"
        for item in orchestrator.memory.audit_tail(15)
    )
    return "\n".join(lines), audit or "_No audit events yet._"


def build_app() -> gr.Blocks:
    with gr.Blocks(title="RadeonPilot Ops Console", theme=gr.themes.Soft()) as app:
        gr.Markdown(
            "# RadeonPilot Ops Console\n"
            "Multi-agent ROCm inference operations on a local AMD Radeon GPU — "
            "diagnose, deploy, benchmark, and optimize with evidence-cited agents."
        )
        session_state = gr.State(None)
        with gr.Row():
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(height=420, label="Ops conversation")
                with gr.Row():
                    message = gr.Textbox(label="Request", placeholder="e.g. Diagnose the endpoint and propose optimizations", scale=4)
                    role = gr.Dropdown(["operator", "ml_engineer", "sre", "ops_commander"], value="operator", label="Role")
                with gr.Row():
                    run_btn = gr.Button("Run ops", variant="primary")
                    clear_btn = gr.Button("New session")
            with gr.Column(scale=1):
                agents_md = gr.Markdown(label="Agent reports")
                evidence_md = gr.Markdown(label="Local evidence")

        with gr.Tabs():
            with gr.Tab("Diagnose"):
                diag_btn = gr.Button("Run deterministic diagnostics")
                diag_out = gr.Markdown()
                diag_btn.click(diagnose, outputs=diag_out)
            with gr.Tab("Knowledge"):
                kq = gr.Textbox(label="Search local ROCm/vLLM knowledge")
                k_btn = gr.Button("Search")
                k_out = gr.Markdown()
                k_btn.click(search_knowledge, inputs=kq, outputs=k_out)
            with gr.Tab("Audit & Runtime"):
                refresh_btn = gr.Button("Refresh")
                runtime_md = gr.Markdown()
                audit_md = gr.Markdown()
                refresh_btn.click(runtime_panel, outputs=[runtime_md, audit_md])

        run_btn.click(
            run_ops,
            inputs=[message, chatbot, session_state, role],
            outputs=[chatbot, session_state, agents_md, evidence_md],
        )
        clear_btn.click(lambda: ([], None, "_No agent reports yet._", "_No local evidence matched._"), outputs=[chatbot, session_state, agents_md, evidence_md])
        app.load(runtime_panel, outputs=[runtime_md, audit_md])
    return app


if __name__ == "__main__":
    build_app().launch(server_name="127.0.0.1", server_port=int(os.environ.get("RADEONPILOT_PORT", "7860")))
