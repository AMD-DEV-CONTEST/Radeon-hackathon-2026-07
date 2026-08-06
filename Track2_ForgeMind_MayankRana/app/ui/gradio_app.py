
import gradio as gr
import pathlib
import os
import time
import json

try:
    from app.rocm_utils import get_rocm_info
    from app.agents.graph import build_graph, run_swarm_simple
    from app.tools.rag_tool import get_rag
    from app.tools import file_tools
except ImportError as e:
    print(f"Import warning: {e}")

# Try to build LangGraph
try:
    graph = build_graph()
    USE_LANGGRAPH = True
except Exception as e:
    print(f"LangGraph build failed, using simple loop: {e}")
    graph = None
    USE_LANGGRAPH = False

def get_gpu_html():
    try:
        info = get_rocm_info()
    except:
        info = {"gpu_name": "Local GPU (CPU Fallback)", "rocm_version": "N/A", "vram_total_gb": 0, "gpu_util": 0}
    html = f"""
    <div style="background:#111; color:#0f0; padding:12px; border-radius:8px; font-family:monospace;">
    <b>🔥 AMD ROCm Status</b><br>
    GPU: {info.get('gpu_name','Unknown')}<br>
    ROCm: {info.get('rocm_version','N/A')}<br>
    VRAM: {info.get('vram_total_gb',0)} GB<br>
    Status: <span style="color:#0ff">● ONLINE - 100% Local Inference</span>
    </div>
    """
    return html

def ingest_codebase(workspace_path):
    if not workspace_path or not pathlib.Path(workspace_path).exists():
        return "❌ Workspace path does not exist"
    try:
        file_tools.set_workspace(workspace_path)
        rag = get_rag(workspace_path)
        result = rag.ingest()
        tree = file_tools.file_tree()
        return f"{result}\n\n--- File Tree ---\n{tree}"
    except Exception as e:
        return f"Error: {e}"

def run_task(task, workspace_path, model_name, progress=gr.Progress()):
    if not workspace_path:
        return "Please set workspace path", "", "", get_gpu_html()
    if not task:
        return "Please enter a task", "", "", get_gpu_html()

    try:
        file_tools.set_workspace(workspace_path)
    except Exception as e:
        return f"Error setting workspace: {e}", "", "", get_gpu_html()
    
    progress(0.1, desc="Planner Agent thinking...")
    time.sleep(0.5)
    
    initial_state = {
        "task": task,
        "workspace": workspace_path,
        "plan": "",
        "files_changed": [],
        "code_context": "",
        "test_result": "",
        "review_feedback": "",
        "docs": "",
        "iteration": 0,
        "messages": [],
        "status": "planning"
    }

    final_state = None
    logs = []

    if USE_LANGGRAPH and graph:
        try:
            for i, event in enumerate(graph.stream(initial_state)):
                for node_name, state_update in event.items():
                    # FIXED: simple log without nested f-string bug
                    plan_text = state_update.get('plan', '')[:500]
                    if not plan_text:
                        plan_text = str(list(state_update.keys()))[:500]
                    log_entry = "### Agent: " + node_name.upper() + "\n" + plan_text
                    logs.append(log_entry)
                    final_state = state_update
                    progress((i+1)/6, desc=f"{node_name} working...")
        except Exception as e:
            print(f"LangGraph stream error: {e}, falling back")
            final_state = run_swarm_simple(task, workspace_path)
            for m in final_state.get("messages", []):
                logs.append("### " + m.get('agent','unknown').upper() + "\n" + m.get('content','')[:2000])
    else:
        final_state = run_swarm_simple(task, workspace_path)
        for m in final_state.get("messages", []):
            content = m.get('content','')[:2000]
            agent = m.get('agent','unknown')
            logs.append(f"### {agent.upper()}\n{content}")

    if not final_state:
        final_state = initial_state

    plan_out = final_state.get("plan", "No plan")
    test_out = final_state.get("test_result", "No tests run")
    docs_out = final_state.get("docs", "No docs")
    files_out = "\n".join(final_state.get("files_changed", []))
    
    combined_log = "\n\n".join(logs)
    
    # Get GPU info safely
    try:
        gpu_name = get_rocm_info().get('gpu_name','Radeon')
    except:
        gpu_name = "Local GPU"
    
    summary = f"""
## ✅ ForgeMind Completed

**Task:** {task}
**Model:** {model_name}
**Iterations:** {final_state.get('iteration', 0)}

### 📁 Files Changed
{files_out}

### 🧪 Test Results
```
{test_out[:3000]}
```

### 📝 Docs
{docs_out}

### GPU: {gpu_name} - 100% Offline
"""
    return combined_log, plan_out, summary, get_gpu_html()

def create_ui():
    with gr.Blocks(theme=gr.themes.Soft(), title="ForgeMind - Radeon ROCm Swarm") as demo:
        gr.Markdown("""
        # 🔥 ForgeMind — Offline Sovereign Developer Swarm
        **Runs 100% Local on AMD Radeon + ROCm | No Cloud | No API Keys**
        *Track 2: Localized AI Agents Deployment — AMD AI DevMaster 2026*
        """)
        
        with gr.Row():
            with gr.Column(scale=2):
                workspace = gr.Textbox(label="Workspace Path", value="demo/sample_codebase", placeholder="/path/to/codebase")
                task = gr.Textbox(label="Task for Agent Swarm", placeholder="e.g., Add JWT auth to Flask app, fix login bug, and write tests", lines=3)
                model = gr.Dropdown(label="Local Model (ROCm)", choices=["qwen2.5-coder:7b", "qwen2.5-coder:1.5b", "llama3.1:8b"], value="qwen2.5-coder:1.5b")
                with gr.Row():
                    ingest_btn = gr.Button("📂 Ingest Codebase (Local RAG)", variant="secondary")
                    run_btn = gr.Button("🚀 Run Swarm on Radeon", variant="primary")
                
                gpu_html = gr.HTML(value=get_gpu_html())

            with gr.Column(scale=3):
                gr.Markdown("### 📜 Agent Swarm Live Trace")
                live_log = gr.Markdown(label="Agent Trace")
                with gr.Row():
                    plan_box = gr.Textbox(label="📋 Plan", lines=8)
                summary_box = gr.Markdown(label="Final Summary")

        ingest_out = gr.Textbox(label="Ingest Output", lines=10)

        ingest_btn.click(fn=ingest_codebase, inputs=[workspace], outputs=[ingest_out])
        run_btn.click(fn=run_task, inputs=[task, workspace, model], outputs=[live_log, plan_box, summary_box, gpu_html])

        gr.Markdown("""
        ---
        **How it works on ROCm:** Codebase → Tree-sitter → BGE embeddings (ROCm PyTorch) → ChromaDB → 5 agents via LangGraph → vLLM-ROCm
        """)

    return demo

if __name__ == "__main__":
    ui = create_ui()
    ui.launch(server_name="0.0.0.0", server_port=7860, share=False)
