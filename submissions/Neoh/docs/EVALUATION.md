# Evaluation Guide — Radeon-Assistant (Team Neoh, Track 2)

This guide tells a reviewer exactly **how to bring the project up, what to click, and what the expected result is**, so that every claim in the submission can be reproduced on an AMD Radeon machine. It also maps each Track 2 judging dimension to the concrete artefact that supports it.

Two paths are provided:

* **Path A — 10-minute live demo** (needs a ROCm host with a Radeon GPU and the model downloaded).
* **Path B — offline review** (no GPU): read the recorded evidence.

---

## Path A — 10-minute live demo

### A0. Bring-up (2 min, once)

```bash
cd submissions/Neoh
source setenv-rocm.sh                 # ROCm env + venv  (must be sourced in every new shell)
rocm-smi --showmemuse                 # expect 0 % — no leftover vLLM worker
python app.py --mode web --port 7860
```

Open <http://localhost:7860>. Sidebar → **Knowledge base** should show a non-zero *Indexed chunks* badge (the bundled datasheet corpus is pre-indexed; ~3.3 k chunks from 7 documents in 4 formats).

> The model is lazy-loaded: the **first** message takes ≈ 75–90 s (Qwen2.5-14B FP16 weight load + warm-up). Everything after that is fast. This is expected and visible in `rocm-smi` as VRAM climbing to ~28 GB.

### A1. Retrieval-augmented Q&A over local datasheets (3 min)

Keep **Interaction = `Chat (RAG)`** and ask, one at a time:

| # | Question | What to look for |
|---|---|---|
| 1 | *What is the I2C slave address of the LMT75 temperature sensor, and what is its supply voltage range?* | Answer is grounded in the **DOCX** sample datasheet; the `Sources` expander names `LMT75_I2C_TempSensor_Datasheet_sample.docx` |
| 2 | *Explain the working principle of the TMP117 temperature sensor and state its typical accuracy.* | Grounded in the real TI **PDF**; explains the sensing principle and quotes an accuracy figure |
| 3 | *For the W25Q128JV SPI flash, what is the page program size and which SPI modes does it support?* | Grounded in the **TXT** datasheet; mentions 256-byte pages and SPI modes 0/3 |
| 4 | *CW32L012 微控制器的供电电压范围和内核主频是多少？请用中文回答。* | Cross-language retrieval: grounded in the **Chinese PDF** manual and answered in Chinese |

Each answer carries a `Sources (n)` expander listing the retrieved chunks with their file names — that is the traceability evidence: the answer can be checked against the exact datasheet passage that produced it.

### A2. Agent skills with tool calling (4 min)

Switch **Interaction → `Agent Task (tools)`**. Now the Planner → Executor → Reflector loop runs and the reply is a step-by-step trace showing which tool ran and what it returned.

| # | Prompt | Skill exercised |
|---|---|---|
| 5 | *Generate a Verilog module named i2c_slave that implements an I2C slave interface with an 8-bit register file.* | `generate_verilog` — HDL written to `generated/` |
| 6 | *Write a Verilog testbench for a 4-bit ALU module named alu4 supporting add, sub, and, or.* | `generate_testbench` |
| 7 | *Report the GPU status and the system information of this machine.* | `get_gpu_info`, `get_system_info` — proves it is really running on the Radeon |
| 8 | *List the files under data/hardware_documents, then read W25Q128JV_SPI_Flash_Datasheet_sample.txt.* | `list_directory`, `read_file` |
| 9 | *Run Python code that prints the 7-bit I2C addresses from 0x48 to 0x4B in hexadecimal.* | `execute_python` — a **high-risk** tool, so it passes the approval gate |

### A3. Safety and privacy (1 min)

1. Sidebar → **Tool safety** → switch to `Block high-risk`, then re-send prompt 9. The step is refused instead of executed — the human-in-the-loop gate is real, not decorative.
2. Sidebar → **Audit log** shows the JSON-Lines trail (`logs/audit.log`): every tool call, every approval decision, task starts and chat events. Chat bodies are recorded only as lengths, so the log itself leaks nothing.
3. Disconnect the network (or watch with `ss -tnp`) and repeat any question — inference keeps working, because the model, the embeddings and the vector index are all local.

---

## Path B — offline review (no GPU)

| Question | Artefact |
|---|---|
| What is it, and how is it built? | [`../README.md`](../README.md), [`project_spec.pdf`](project_spec.pdf), [`architecture.png`](architecture.png) |
| How do I run it? | [`USER_MANUAL.md`](USER_MANUAL.md) |
| Does it work? | [`TEST_REPORT.md`](TEST_REPORT.md) (EN) / [`TEST_REPORT.zh-CN.md`](TEST_REPORT.zh-CN.md) (ZH) |
| Web UI + skills end-to-end evidence | [`WEB_UI_TEST.md`](WEB_UI_TEST.md) — transcript of a scripted human-simulation run through the browser |
| How fast is it on the Radeon? | [`benchmark_qwen2.5-14b.md`](benchmark_qwen2.5-14b.md) / [`.json`](benchmark_qwen2.5-14b.json) |
| Where is the submission checklist? | [`../SUBMISSION.md`](../SUBMISSION.md) |
| Integration story | [`DIFY_INTEGRATION.md`](DIFY_INTEGRATION.md), [`CLOUD_RUN.md`](CLOUD_RUN.md) |

---

## Reproducing the measurements yourself

```bash
source setenv-rocm.sh

# 1) Throughput / latency on your own GPU (writes docs/benchmark_<model>.json|md)
python scripts/benchmark.py --model qwen2.5-14b

# 2) Rebuild the knowledge base and print the chunk count
python scripts/init_hardware_rag.py

# 3) Scripted human-simulation run through the Web UI (needs the UI running)
python workspace/scripts/web_human_test.py all
#    -> workspace/test_results/web_human_test.{json,md}
```

---

## Track 2 criteria → evidence map

| Judging dimension | How this project addresses it | Evidence |
|---|---|---|
| **Local deployment on AMD hardware** | Qwen2.5-14B FP16 served by vLLM on ROCm 7.14, gfx1100; no CUDA anywhere; env pinned by `setenv-rocm.sh` / `install_rocm.sh` | `install_rocm.sh`, `setenv-rocm.sh`, §A2 prompt 7 (`get_gpu_info`), `benchmark_qwen2.5-14b.md` |
| **Privacy / data never leaves the machine** | Inference, embeddings (`all-MiniLM-L6-v2`) and FAISS search all run locally; the corpus lives in `data/`; audit log stores lengths, not content | §A3, `agent/audit.py`, `memory/` |
| **Agent capability** | Hand-written Planner → Executor → Reflector loop (no external agent framework) driving 14 registered tools; every run is rendered as an auditable step trace | `agent/`, `tools/`, §A2 |
| **Domain value (hardware R&D)** | Hardware system prompt, multi-format datasheet RAG with PDF **table** extraction, Verilog / testbench generation | `agent/prompts.py`, `memory/document_parser.py`, `tools/hardware_tools.py`, §A1–A2 |
| **Safety / controllability** | Five high-risk tools behind an approval gate; switchable safety policy in the UI; JSON-Lines audit trail | `agent/executor.py`, `config.yaml → security`, §A3 |
| **Usability** | Streamlit UI with two interaction modes, source citations, knowledge-base management, dark mode; CLI; OpenAI-compatible endpoint for Dify | `ui/web_app.py`, `scripts/serve.py`, `DIFY_INTEGRATION.md` |
| **Engineering quality / honesty** | Documented limitations (no simulator verification), reproducible benchmark, documented ROCm pitfalls and fixes | `README.md` §Scope, `USER_MANUAL.md` §9 |

---

## Known limitations (stated up front)

* Generated Verilog / testbenches are **not** verified by a simulator (iverilog / Verilator); they are drafting aids.
* Retrieval quality depends on the corpus: scanned, image-only PDFs produce no text (no OCR).
* In the Web UI the approval gate is a policy switch rather than a blocking modal, because a Streamlit script run cannot block on terminal input; the CLI keeps the interactive `y/N` prompt. Both paths write the same audit records.
* Single-GPU configuration is what has been tested; tensor parallelism is wired but untested here.
