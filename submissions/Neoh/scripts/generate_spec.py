"""Generate the Radeon-Assistant project specification PDF.

Usage:
    cd submissions/Neoh
    python scripts/generate_spec.py

Output:
    docs/project_spec.pdf
"""

from pathlib import Path
from fpdf import FPDF

# All generated artifacts live in ../docs relative to this script (scripts/).
DOCS = Path(__file__).resolve().parent.parent / "docs"


class SpecPDF(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Radeon-Assistant - Project Specification | Track 2 | Team Neoh", align="L")
        self.cell(0, 8, f"Page {self.page_no()}", align="R")
        self.ln(8)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, "AMD Radeon Hackathon 2026-07", align="C")

    def chapter_title(self, title):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(44, 62, 80)
        self.ln(4)
        self.cell(0, 8, title, ln=True)
        self.set_draw_color(44, 62, 80)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def chapter_subtitle(self, subtitle):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(44, 62, 80)
        self.ln(3)
        self.cell(0, 6, subtitle, ln=True)
        self.ln(1)

    def body_text(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5, text)
        self.ln(2)

    def bullet(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(50, 50, 50)
        self.cell(4)
        self.cell(4, 5, "-", ln=0)
        self.multi_cell(0, 5, text)
        self.ln(1)


def main():
    pdf = SpecPDF()
    # Built-in Helvetica handles the all-English specification text.
    pdf.set_auto_page_break(auto=True, margin=18)

    # ------------------- Cover -------------------
    pdf.add_page()
    pdf.set_y(80)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(44, 62, 80)
    pdf.cell(0, 14, "Radeon-Assistant", ln=True, align="C")
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(52, 73, 94)
    pdf.cell(0, 10, "A Privacy-First Local AI Agent on AMD Radeon GPU", ln=True, align="C")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, "Project Specification Document", ln=True, align="C")
    pdf.cell(0, 7, "Track 2 - Private AI Agent Development & Local Deployment", ln=True, align="C")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, "Team: Neoh", ln=True, align="C")
    pdf.cell(0, 6, "Competition: AMD Radeon Hackathon 2026-07", ln=True, align="C")
    pdf.cell(0, 6, "Date: July 2026", ln=True, align="C")

    pdf.set_y(-60)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5,
        "Abstract. Radeon-Assistant is a fully local AI agent system running on AMD Radeon GPUs via the ROCm software stack. "
        "It combines a hand-written Planner-Executor-Reflector agent loop, a FAISS-backed RAG knowledge base, 14 built-in tools, "
        "human-in-the-loop safety controls, and a hardware-R&D specialization layer. No external API is called during inference.",
        align="C")

    # ------------------- 1. Application Scenarios -------------------
    pdf.add_page()
    pdf.chapter_title("1. Application Scenarios")
    pdf.body_text(
        "Radeon-Assistant targets scenarios where data privacy, offline availability, and local control are non-negotiable. "
        "By running the entire inference pipeline on AMD Radeon GPUs, the system eliminates the latency, cost, and privacy risks "
        "associated with cloud-based LLM APIs."
    )

    pdf.chapter_subtitle("1.1 Local Knowledge Base Q&A")
    pdf.body_text(
        "Users upload private documents (PDF, DOCX, Markdown, plain text) and ask questions against them. "
        "Documents are parsed, chunked, embedded with all-MiniLM-L6-v2, and stored in a local FAISS index. "
        "Top-K chunks are retrieved as context for the LLM. Source metadata is preserved so answers can be traced back to the originating document."
    )

    pdf.chapter_subtitle("1.2 Office & Desktop Automation")
    pdf.body_text(
        "The agent performs file operations, executes shell commands, runs Python code, and queries system information through a registry of 14 built-in tools. "
        "High-risk operations require explicit user approval before execution."
    )

    pdf.chapter_subtitle("1.3 Multi-Step Task Planning")
    pdf.body_text(
        "Complex requests are handled by the Planner-Executor-Reflector loop. The Planner emits a JSON list of steps; the Executor runs each step with HITL approval; "
        "the Reflector evaluates completion and suggests retries if needed. The loop supports up to 10 iterations."
    )

    pdf.chapter_subtitle("1.4 Hardware R&D Assistance (Specialization)")
    pdf.body_text(
        "A hardware-domain system prompt and dedicated tools help engineers read chip datasheets, compare parameters, "
        "and generate Verilog / SystemVerilog modules and testbenches locally. PDF tables (pin tables, electrical-parameter tables) are extracted and indexed for RAG retrieval."
    )

    pdf.chapter_subtitle("1.5 Privacy-Sensitive Environments")
    pdf.body_text(
        "No component makes outbound network calls during inference. All LLM inference, embedding, and vector search run locally. "
        "An audit log records tool invocations, approval decisions, tasks, and chat metadata in JSON Lines format."
    )

    # ------------------- 2. System Architecture -------------------
    pdf.add_page()
    pdf.chapter_title("2. System Architecture")
    pdf.body_text(
        "The system is organized into seven layers. Data flows from the user interface through the agent core, safety layer, tools, memory, "
        "and inference engine, ultimately reaching the AMD Radeon GPU hardware."
    )

    # Embed architecture diagram
    img_path = DOCS / "architecture.png"
    if img_path.exists():
        avail_w = pdf.w - pdf.l_margin - pdf.r_margin
        pdf.image(str(img_path), x=pdf.l_margin, w=avail_w)
    else:
        pdf.body_text("[architecture.png not found at generation time]")

    pdf.ln(4)
    pdf.chapter_subtitle("Layer Responsibilities")
    table_data = [
        ("User", "Streamlit Web UI / CLI", "Accepts input, displays responses, handles file uploads"),
        ("Agent", "Planner / Executor / Reflector", "Decomposes tasks, executes steps, evaluates results"),
        ("Safety", "HITL Approval + Audit Log", "Intercepts high-risk operations, records all actions"),
        ("Tools", "14 registered tools", "File, shell, code, system, and hardware operations"),
        ("Memory", "Short-term + FAISS RAG", "Conversation history and vector retrieval of documents"),
        ("Inference", "vLLM + ROCm", "Safetensors model loading, GPU offload, chat completion"),
        ("Hardware", "AMD Radeon GPU", "Physical compute via HIP/ROCm kernels"),
    ]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(25, 6, "Layer", border=1, fill=True)
    pdf.cell(55, 6, "Component", border=1, fill=True)
    pdf.cell(0, 6, "Responsibility", border=1, fill=True, ln=True)
    pdf.set_font("Helvetica", "", 9)
    for layer, comp, resp in table_data:
        pdf.cell(25, 6, layer, border=1)
        pdf.cell(55, 6, comp, border=1)
        pdf.cell(0, 6, resp, border=1, ln=True)
    pdf.ln(4)

    pdf.body_text(
        "Agent loop detail: When a user submits a task, the Planner receives the task description and available tool schemas, "
        "then prompts the LLM to produce a JSON array of steps. The Executor processes each step, invoking the approval gate when required. "
        "The Reflector evaluates whether the task was accomplished and provides a suggestion for the next iteration if needed."
    )

    # ------------------- 3. Core Capabilities -------------------
    pdf.add_page()
    pdf.chapter_title("3. Core Capabilities")

    pdf.chapter_subtitle("3.1 Local Knowledge Retrieval (RAG)")
    pdf.body_text(
        "Supports PDF (pdfplumber, with table extraction), DOCX, Markdown, and plain text. Documents are split into 512-character chunks with 50-character overlap. "
        "Chunks are embedded with all-MiniLM-L6-v2 (384-dimensional vectors) and stored in FAISS IndexFlatL2. Top-5 chunks are retrieved at query time."
    )

    pdf.chapter_subtitle("3.2 Tool Calling")
    pdf.body_text(
        "Fourteen tools are registered at startup across five categories:"
    )
    pdf.bullet("File tools: read_file, write_file, delete_file, list_directory, create_directory")
    pdf.bullet("Shell tools: execute_command, execute_python")
    pdf.bullet("Code tools: code_interpreter, format_code")
    pdf.bullet("System tools: get_system_info, get_gpu_info, get_process_list")
    pdf.bullet("Hardware tools: generate_verilog, generate_testbench")
    pdf.body_text(
        "Each tool declares its parameter schema and whether it requires approval. New tools are added by registering a single Python function."
    )

    pdf.chapter_subtitle("3.3 Multi-Step Task Planning")
    pdf.body_text(
        "The Planner-Executor-Reflector loop handles tasks requiring multiple tool calls. The Planner generates up to 5 steps per task; "
        "the Executor processes them with HITL approval for high-risk operations; the Reflector evaluates the outcome and guides retry if necessary."
    )

    pdf.chapter_subtitle("3.4 Local Multi-Turn Memory")
    pdf.body_text(
        "Short-term memory keeps the last 20 conversation messages. Long-term memory is the FAISS vector store, which persists across sessions and provides semantic retrieval of uploaded documents."
    )

    pdf.chapter_subtitle("3.5 Permission & Privacy Protection")
    pdf.body_text(
        "Human-in-the-loop approval intercepts tools marked requires_approval=True. The audit logger writes JSON Lines records for every tool call, approval decision, task execution, and chat event. "
        "Chat content is logged only as length summaries to protect privacy."
    )

    # ------------------- 4. Hardware R&D Specialization -------------------
    pdf.add_page()
    pdf.chapter_title("4. Hardware R&D Specialization")
    pdf.body_text(
        "To make the 'hardware R&D private agent' claim concrete, three specialization layers were added on top of the general agent framework:"
    )
    pdf.bullet("Hardware-domain system prompt: constrains answers to EDA, MCU/SoC/FPGA, datasheets, schematics/PCB collaboration, Verilog/SystemVerilog, timing/power estimation, and embedded firmware.")
    pdf.bullet("Datasheet parsing: PDF tables (pin tables, parameter tables) are extracted and indexed so they become searchable by the RAG subsystem.")
    pdf.bullet("Hardware generation tools: generate_verilog and generate_testbench use the local LLM to produce synthesizable modules and testbenches, written to ./generated/.")
    pdf.body_text(
        "This is a usage-scenario specialization, not a from-scratch EDA engine. Generated Verilog/testbenches are not verified by a simulator (e.g., iverilog) in the current version."
    )

    # ------------------- 5. Model & Local Deployment Plan -------------------
    pdf.add_page()
    pdf.chapter_title("5. Model & Local Deployment Plan")

    pdf.chapter_subtitle("5.1 Model Selection")
    pdf.body_text(
        "The primary LLM is Qwen2.5-14B-Instruct in FP16 safetensors format (~28 GB). It was chosen for strong Chinese/English bilingual capability, "
        "native function-calling support, and the Apache 2.0 license. Qwen2.5-7B-Instruct is supported as a lightweight fallback (~15 GB). "
        "The embedding model is all-MiniLM-L6-v2 (23 MB, 384-dimensional vectors). The vector store is FAISS IndexFlatL2."
    )
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(45, 6, "Component", border=1, fill=True)
    pdf.cell(55, 6, "Model / Format", border=1, fill=True)
    pdf.cell(0, 6, "Purpose", border=1, fill=True, ln=True)
    pdf.set_font("Helvetica", "", 9)
    rows = [
        ("Primary LLM", "Qwen2.5-14B-Instruct FP16 safetensors", "Core inference, planning, tool decisions"),
        ("Lightweight LLM", "Qwen2.5-7B-Instruct FP16 safetensors", "Faster fallback on limited VRAM"),
        ("Embedding", "all-MiniLM-L6-v2", "Document vectorization"),
        ("Vector store", "FAISS IndexFlatL2", "Local similarity search"),
    ]
    for comp, model, purpose in rows:
        pdf.cell(45, 6, comp, border=1)
        pdf.cell(55, 6, model, border=1)
        pdf.cell(0, 6, purpose, border=1, ln=True)
    pdf.ln(4)

    pdf.chapter_subtitle("5.2 Deployment Environment")
    pdf.body_text(
        "Target platform: Linux (Ubuntu 22.04+) with ROCm 7.14 and an AMD Radeon GPU. Testing was performed on AMD Radeon Cloud with a Radeon Pro W7900D (48 GB VRAM, gfx1100). "
        "The deep-learning stack (torch / vllm / flash-attn) is installed only from AMD ROCm sources (repo.amd.com, rocm.frameworks.amd.com) via install_rocm.sh - CUDA builds are blacklisted. "
        "Because W7900/RX 7900 are gfx1100 cards, the environment variables HSA_OVERRIDE_GFX_VERSION=11.0.0 and PYTORCH_ROCM_ARCH=gfx1100 (plus FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE and the ROCm SDK PYTHONPATH) must be set before importing vLLM/torch."
    )

    pdf.chapter_subtitle("5.3 Deployment Steps")
    pdf.bullet("Install dependencies: bash install_rocm.sh")
    pdf.bullet("Download model: python scripts/download_model.py --model qwen2.5-14b")
    pdf.bullet("(Optional) Initialize RAG: python scripts/init_rag.py or python scripts/init_hardware_rag.py")
    pdf.bullet("Run CLI: python app.py --mode cli; or Web UI: python app.py --mode web --port 7860")

    # ------------------- 6. Performance -------------------
    pdf.add_page()
    pdf.chapter_title("6. Performance & Optimization")
    pdf.body_text(
        "Measured on AMD Radeon Cloud (Radeon Pro W7900D, 48 GB VRAM, single GPU, ROCm 7.14, vLLM 0.23.1, Python 3.14):"
    )
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(50, 6, "GPU", border=1, fill=True)
    pdf.cell(55, 6, "Model", border=1, fill=True)
    pdf.cell(35, 6, "Speed", border=1, fill=True)
    pdf.cell(0, 6, "VRAM", border=1, fill=True, ln=True)
    pdf.set_font("Helvetica", "", 9)
    perf_rows = [
        ("Radeon Pro W7900", "Qwen2.5-14B FP16", "~27.5 tokens/s", "~30 GB"),
        ("Radeon Pro W7900", "Qwen2.5-7B FP16", "~46 tokens/s", "~15 GB"),
    ]
    for gpu, model, speed, vram in perf_rows:
        pdf.cell(50, 6, gpu, border=1)
        pdf.cell(55, 6, model, border=1)
        pdf.cell(35, 6, speed, border=1)
        pdf.cell(0, 6, vram, border=1, ln=True)
    pdf.ln(4)
    pdf.body_text(
        "Optimization notes: vLLM uses PagedAttention and continuous batching. enforce_eager=False enables CUDA/ROCm graphs. "
        "Tensor parallelism is configurable but defaults to single-GPU. For higher throughput, users can switch to 7B or explore quantization with vLLM serve."
    )

    # ------------------- 7. Submission Structure -------------------
    pdf.chapter_title("7. Submission Structure")
    pdf.body_text(
        "The submission is located in submissions/Neoh/ and includes:"
    )
    pdf.bullet("agent/ - Planner, Executor, Reflector, audit logger, prompts")
    pdf.bullet("inference/ - vLLM engine wrapper and model loader")
    pdf.bullet("memory/ - Document parser, FAISS vector store, memory manager")
    pdf.bullet("tools/ - 14 registered tools including hardware specialization tools")
    pdf.bullet("ui/ - Streamlit web interface")
    pdf.bullet("scripts/ - Model downloader and RAG initialization scripts")
    pdf.bullet("docs/ - architecture.png and project_spec.pdf")
    pdf.bullet("config.yaml, requirements.txt, install_rocm.sh, app.py, notebooks/startup.ipynb")

    # ------------------- 8. Limitations & Next Steps -------------------
    pdf.add_page()
    pdf.chapter_title("8. Limitations & Next Steps")
    pdf.body_text(
        "The following limitations are recorded objectively to align claims with code reality:"
    )
    pdf.bullet("Verilog / testbench generation is LLM-based text generation; it is not connected to a simulator (iverilog, Verilator) for automatic verification.")
    pdf.bullet("Hardware features are usage-scenario specializations on top of a general agent framework, not a from-scratch EDA engine.")
    pdf.bullet("Model selection is backed by a local throughput / latency benchmark (docs/benchmark_qwen2.5-14b.md): 14B is the tested default (27.5 tok/s), 7B also profiled (46 tok/s); 32B remains untested on this 48 GB card.")
    pdf.bullet("ROCm inference requires Linux + AMD GPU; Windows desktop cannot run the ROCm vLLM wheel directly.")
    pdf.ln(3)
    pdf.body_text(
        "Planned next steps: add a small benchmark script for 7B/14B comparison; connect generated Verilog to iverilog for smoke-test validation; "
        "and expand the hardware document corpus with real datasheets."
    )

    out_path = DOCS / "project_spec.pdf"
    pdf.output(str(out_path))
    print(f"Saved project specification to {out_path}")


if __name__ == "__main__":
    main()
