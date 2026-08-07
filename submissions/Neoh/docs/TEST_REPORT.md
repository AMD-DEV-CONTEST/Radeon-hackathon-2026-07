# Radeon-Assistant — Functional Test Report

**Project**: Radeon-Assistant (application name: "Panshi" / 磐石)
**Track**: Track 2 — Private AI Agent Development & Local Deployment
**Team**: Neoh
**Test date**: 2026-08-06
**Model under test**: Qwen2.5-14B-Instruct (FP16), running entirely on a local AMD Radeon GPU

> A Chinese translation of this document is available at [`TEST_REPORT.zh-CN.md`](./TEST_REPORT.zh-CN.md).

---

## 1. Summary

Every functional module of the system was exercised end-to-end on the target hardware with the
14B model. **No external API is called at any point** — inference, embedding and vector search all
run locally on the Radeon GPU.

| # | Module | Scope | Result |
|---|--------|-------|:------:|
| A | Inference engine + agent core | engine load, chat, multi-step task, summarize, prompt switching | PASS (5/5) |
| B | Tool registry | all 14 built-in tools invoked through the registry | PASS (14/14) |
| C | Human-in-the-loop + audit | approval granted, approval denied, audit log written | PASS (3/3) |
| D | Hardware-specific generation | engine injection, Verilog and testbench written to disk | PASS (3/3) |
| E | RAG / document pipeline | index build, PDF **table** extraction, retrieval, grounded Q&A | PASS (4/4) |
| F | Service entry points | Streamlit Web UI, `/v1/models`, `/v1/chat/completions` | PASS (3/3) |
| G | Performance benchmark | 5 hardware-R&D scenarios | 27.4 tok/s avg |

**Total: 32 / 32 functional checks passed.** Known limitations are documented honestly in
[Section 11](#11-known-limitations) — most notably, generated HDL is **not** verified by a simulator.

---

## 2. Test Environment

| Item | Value |
|------|-------|
| GPU | AMD Radeon Pro W7900D (gfx1100, 48 GB) — Radeon Cloud |
| OS | Ubuntu 22.04.5 LTS, glibc 2.35 |
| Python | 3.14.3 (venv at `/opt/venv314`) |
| PyTorch | 2.11.0+rocm7.14.0 |
| vLLM | 0.23.1.dev1+rocm7.14.0 (ROCm build, cp314) |
| transformers | 5.14.1 |
| flash-attn | 2.8.3 |
| Embedding model | all-MiniLM-L6-v2 (384-dim), local |
| Vector store | FAISS `IndexFlatL2` |
| `torch.cuda.is_available()` | `True` (HIP backend) |

Two environment details are mandatory on this hardware and are handled by `setenv-rocm.sh`:

- `HSA_OVERRIDE_GFX_VERSION=11.0.0` — without it vLLM does not recognise gfx1100 (W7900 / RX 7900).
- An `__isoc23_*` shim preloaded via `LD_PRELOAD` — the official wheels are built against
  glibc 2.38, while Ubuntu 22.04 ships glibc 2.35.

**The stack is ROCm-only. No CUDA runtime is present and no NVIDIA package is installed.**

### Engine runtime figures (14B, FP16)

| Metric | Value |
|--------|-------|
| Model weights on GPU | 27.57 GiB |
| GPU KV cache | 78,736 tokens (13.73 GiB) |
| Max concurrency @ 8,192 tokens/request | 9.61x |
| Engine init (profile + KV cache + warmup) | 20.83 s (compilation 3.55 s) |
| Cold model load | ~76 s |

---

## 3. Methodology

All checks were executed on the target GPU against the real 14B model — no mocks, no stubs.
Tools were invoked through the real `ToolRegistry`, not called directly, so the registry lookup and
dispatch path is covered as well.

Checks that do not require the GPU (tool execution, RAG index build, PDF parsing, retrieval) were
additionally re-run in a separate CPU-only pass to confirm the results are reproducible and
independent of engine state.

Each check asserts on a concrete observable value — a unique token in stdout, a specific numeric
value retrieved from a document table, a file appearing on disk — rather than merely asserting
"no exception was raised".

---

## 4. A — Inference Engine and Agent Core

| ID | Check | Evidence | Result |
|----|-------|----------|:------:|
| A0 | Engine loads 14B from local path | `./models/Qwen2.5-14B-Instruct` | PASS |
| A1 | `agent.chat()` in hardware prompt mode | 7,423-character grounded response | PASS |
| A2 | `agent.run_task()` plan → execute → reflect | `success=True`, `steps=1` | PASS |
| A3 | `summarize_conversation()` | 1,102-character summary | PASS |
| A4 | `agent.chat()` in generic prompt mode | 7,382-character response | PASS |

A4 confirms that both branches of `get_system_prompt(mode)` are reachable and that the
`chat(prompt_mode=) > RadeonAgent(prompt_mode=) > config.yaml > "hardware"` priority chain works.

The agent loop (`Planner → Executor → Reflector`) is hand-written; no external agent framework
such as LangChain is used.

---

## 5. B — Tool Registry (14 Tools)

All 14 registered tools were invoked via `registry.call_tool()` and asserted on their return value.

| Category | Tool | Assertion | Result |
|----------|------|-----------|:------:|
| File | `read_file` | content matches what was written | PASS |
| File | `write_file` | file exists on disk afterwards | PASS |
| File | `delete_file` | file no longer exists | PASS |
| File | `list_directory` | expected entry present in listing | PASS |
| File | `create_directory` | directory exists afterwards | PASS |
| Shell | `execute_command` | stdout contains the unique echo token | PASS |
| Shell | `execute_python` | stdout contains the unique print token | PASS |
| Code | `code_interpreter` | returned namespace contains the computed value | PASS |
| Code | `format_code` | black-formatted output returned | PASS |
| System | `get_system_info` | CPU / memory fields populated | PASS |
| System | `get_gpu_info` | AMD GPU reported | PASS |
| System | `get_process_list` | non-empty process list | PASS |
| Hardware | `generate_verilog` | synthesisable-style Verilog returned | PASS |
| Hardware | `generate_testbench` | testbench matching the DUT returned | PASS |

Tool registration happens by import side effect: `tools/__init__.py` imports each tool module and
every module calls `register_tool()` at import time. This test confirms the side-effect
registration path produces exactly the 14 tools listed in `config.yaml` under `agent.tools`.

---

## 6. C — Human-in-the-Loop Approval and Audit Trail

Tools flagged `requires_approval=True` (`write_file`, `delete_file`, `execute_command`,
`execute_python`, `code_interpreter`) must pause for an approval callback before running.

| ID | Check | Evidence | Result |
|----|-------|----------|:------:|
| C1 | Approval **granted** → tool executes | callback returned `True`, side effect observed | PASS |
| C2 | Approval **denied** → tool is skipped | callback returned `False`, no side effect | PASS |
| C3 | Audit log written | `logs/audit.log` contains both `approval` and `tool_call` records | PASS |

C2 is the security-relevant case: denial must actually prevent execution, not merely log a warning.
The test asserts the *absence* of the side effect, so a silently-executing tool would fail the check.

Audit records are written as JSON Lines. Chat content is recorded as a length summary only, so the
audit trail never leaks user content — consistent with the "data never leaves the machine" goal.

---

## 7. D — Hardware-Specific Generation

| ID | Check | Evidence | Result |
|----|-------|----------|:------:|
| D0 | Engine injected into hardware tools | `set_engine(engine)` called at agent construction | PASS |
| D1 | `generate_verilog` writes to `./generated/` | 8-bit up-counter with synchronous reset produced | PASS |
| D2 | `generate_testbench` writes to `./generated/` | `up_counter_tb.v` produced, matching the DUT | PASS |

`generate_verilog` / `generate_testbench` need the inference engine, so `agent/core.py` performs a
deliberate stateful injection via `hardware_tools.set_engine(engine)` while keeping the tool
functions otherwise stateless. D0 verifies that injection actually happened.

> See [Section 11](#11-known-limitations) — the generated HDL is produced by the LLM and is **not**
> checked by a simulator such as iverilog or Verilator.

---

## 8. E — RAG and Document Pipeline

This is the module most relevant to the hardware-R&D use case: chip datasheets carry their key
information in **tables** (pinouts, electrical parameters), which naive PDF text extraction destroys.

A synthetic datasheet was prepared containing a ruled pin table and an electrical-parameter table,
each holding a unique marker value that appears nowhere else, so a retrieval hit proves the value
travelled all the way from the PDF table through the index to the model.

| ID | Check | Evidence | Result |
|----|-------|----------|:------:|
| E1 | Index build from PDF + Markdown | 1 chunk from `.md`, 2 chunks from `.pdf` (text + table) | PASS |
| E2 | **PDF table extraction** + retrieval | retrieved `Pin Name Type Voltage_VPP / 1 VDD PWR 2.85` | PASS |
| E3 | Markdown table retrieval | retrieved `ILIM_ZX ... 1.80` current-limit threshold | PASS |
| E4 | End-to-end grounded Q&A | model answered "Pin1 (VDD) is 2.85 V" **with source attribution** | PASS |

E2 is the decisive result: `pdfplumber` recovered the table as structured rows rather than
collapsing it into unordered text, and the row survived chunking, embedding and retrieval intact.

E4 shows the full chain working — the model answered the pin-voltage question correctly and cited
the source document, using only locally retrieved context.

---

## 9. F — Service Entry Points

| ID | Check | Evidence | Result |
|----|-------|----------|:------:|
| F1 | Streamlit Web UI (`app.py --mode web`) | HTTP 200 on app path and `/healthz`, clean startup log | PASS |
| F2 | `GET /v1/models` | HTTP 200, `{"object":"list","data":[{"id":"qwen2.5-14b",...}]}` | PASS |
| F3 | `POST /v1/chat/completions` | valid OpenAI-format response with `usage` accounting | PASS |

F2/F3 confirm the OpenAI-compatible endpoint served by `scripts/serve.py`, which is what makes the
Dify integration described in [`DIFY_INTEGRATION.md`](./DIFY_INTEGRATION.md) possible: any
OpenAI-compatible client can point at this local endpoint without code changes.

The Web UI loads the model lazily on first chat, so startup is fast and the GPU stays free until
the user actually sends a message.

---

## 10. G — Performance Benchmark

Full results: [`benchmark_qwen2.5-14b.md`](./benchmark_qwen2.5-14b.md) /
[`benchmark_qwen2.5-14b.json`](./benchmark_qwen2.5-14b.json).

| Metric | Value |
|--------|-------|
| Average generation speed | **27.4 tokens/s** |
| Total tokens / total time | 10,238 / 373.3 s |
| Scenarios passed | 5 / 5 |
| Average keyword hit rate | 91% |

| # | Scenario | tokens/s | Keyword hit |
|---|----------|---------:|------------:|
| T1 | Knowledge retrieval | 27.3 | 75% |
| T2 | Parameter comparison | 27.5 | 100% |
| T3 | Log analysis | 27.4 | 80% |
| T4 | Code generation | 27.4 | 100% |
| T5 | Engineering calculation | 27.4 | 100% |

Throughput is stable across all five scenarios (27.3–27.5 tok/s), indicating no thermal or memory
pressure at this model size on a 48 GB W7900.

---

## 11. Known Limitations

Stated plainly, since this is a learning/development-stage project:

1. **Generated HDL is not simulator-verified.** `generate_verilog` / `generate_testbench` are
   LLM-based generation. No iverilog/Verilator run gates the output, so syntactic and functional
   correctness of the produced RTL is not guaranteed. Connecting a simulator for automatic
   self-checking is the most valuable next step.
2. **The hardware capability is a use-case specialisation, not a from-scratch EDA engine.** It sits
   on top of a general agent framework (domain system prompt + generation tools + datasheet RAG).
3. **The keyword hit rate is an automated proxy metric**, not human judgement. It is useful for
   relative 7B/14B/32B comparison but should not be read as an accuracy score. Human scoring or
   LLM-as-judge would be needed for a defensible quality claim.
4. **Only the 14B model was tested.** 7B and 32B are supported by the code path but were not
   benchmarked in this round, so there is no model-selection comparison data yet.
   Note also that `scripts/serve.py` offers a 32B option that `scripts/download_model.py` does not
   yet list.
5. **Table-extraction was validated on a synthetic datasheet**, not a full vendor chip manual.
   Real manuals have far messier layouts (multi-page tables, merged cells, rotated text).
6. **`install_rocm.sh` was not re-run end-to-end on a clean machine** in this round; the test
   environment was built incrementally. The script is syntax-checked and its steps match the
   verified working stack, but a clean-instance install run is still outstanding.
7. **No unit-test framework.** The project has no pytest suite; verification is end-to-end and
   scenario-driven as described above.
8. **ROCm inference requires Linux + an AMD GPU.** It cannot run on a Windows desktop.

---

## 12. Reproduction Steps

All commands run from `submissions/Neoh/` on a Linux host with an AMD GPU.

### 12.1 Install

```bash
bash install_rocm.sh
```

This sets up the Python 3.14 venv, installs the ROCm build of torch/vLLM/flash-attn, and builds the
glibc shim. It ends with a verification step that must print a HIP build of torch, the ROCm vLLM
version, and `True` for device availability.

> Do **not** run `pip install -r requirements.txt` on its own — the public index resolves the CUDA
> build of torch/vLLM, which cannot work on this hardware.

### 12.2 Load the environment

```bash
source setenv-rocm.sh
```

Required in every new shell. It exports `HSA_OVERRIDE_GFX_VERSION=11.0.0`, the amd_smi `PYTHONPATH`,
`FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE`, and the `LD_PRELOAD` glibc shim.

### 12.3 Download the model

```bash
python scripts/download_model.py --model qwen2.5-14b
```

Roughly 28 GB. Falls back ModelScope → hf-mirror → HuggingFace.

### 12.4 Reproduce each result

| Section | Command | What to look for |
|---------|---------|------------------|
| A, B, C | `python app.py --mode cli` | Chat normally; then `task <description>` to trigger planning. Invoking `write_file` / `execute_command` must **pause for approval** — this reproduces Section 6. |
| C3 | `cat logs/audit.log` | JSON Lines records of tool calls and approvals |
| D | in CLI: `task generate an 8-bit up-counter with synchronous reset` | `.v` files appear under `./generated/` |
| E | place a datasheet in `data/hardware_documents/`, then `python scripts/init_hardware_rag.py` | reported chunk count > 0; then ask about a value that only exists in a table |
| F1 | `python app.py --mode web --port 7860` | Web UI reachable, HTTP 200 |
| F2/F3 | `python scripts/serve.py --model qwen2.5-14b` | then `curl http://localhost:8000/v1/models` and POST to `/v1/chat/completions` |
| G | `python scripts/benchmark.py` | regenerates `docs/benchmark_qwen2.5-14b.{md,json}` |

### 12.5 Verify no CUDA / no external API

```bash
# Must print a HIP build and True — and must NOT print any nvidia/cuda package
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
pip list | grep -iE "nvidia|cuda" || echo "no CUDA packages — correct"
```

Inference reaches no external network endpoint: the model is loaded from a local path, embeddings
are computed locally by all-MiniLM-L6-v2, and vector search runs in-process via FAISS.
