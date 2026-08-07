# Track 2 Submission Checklist — Team Neoh

> PR title: `Track 2, Neoh, Radeon-Assistant`  
> Work directory: `submissions/Neoh/`

## Project Identity

| Item | Value |
|---|---|
| Team | Neoh |
| Work name | Radeon-Assistant (磐石) |
| Track | Track 2 — Private AI Agent Development & Local Deployment |
| Hardware target | AMD Radeon Pro W7900 / RX 7900 series (gfx1100) |
| Core stack | vLLM 0.23.1 (ROCm 7.14) + Qwen2.5-14B-Instruct + Python 3.14 |
| License | MIT |

## Track 2 Requirements → Repository Files

### 1. Project Specification (PDF)

Required content: application scenarios, architecture diagram, core capabilities, model & local deployment, AMD inference optimization.

| Required Section | Status | File(s) |
|---|---|---|
| Application scenarios | Ready | [`docs/project_spec.pdf`](docs/project_spec.pdf) §1 |
| Architecture diagram | Ready | [`docs/project_spec.pdf`](docs/project_spec.pdf) §2, [`docs/architecture.png`](docs/architecture.png) |
| Core capabilities | Ready | [`docs/project_spec.pdf`](docs/project_spec.pdf) §3 |
| Model & local deployment | Ready | [`docs/project_spec.pdf`](docs/project_spec.pdf) §5 |
| AMD inference optimization | Ready | [`docs/project_spec.pdf`](docs/project_spec.pdf) §6, [`docs/benchmark_qwen2.5-14b.md`](docs/benchmark_qwen2.5-14b.md) |

Generator: [`scripts/generate_spec.py`](scripts/generate_spec.py)

### 2. Source Code + README

| Component | Path |
|---|---|
| Entry point (CLI / Web UI) | [`app.py`](app.py) |
| Agent core (Planner / Executor / Reflector) | [`agent/`](agent/) |
| Inference wrapper (vLLM) | [`inference/`](inference/) |
| Memory & RAG (FAISS, parser) | [`memory/`](memory/) |
| 14 built-in tools | [`tools/`](tools/) |
| Streamlit Web UI | [`ui/`](ui/) |
| Model downloader / RAG init scripts | [`scripts/`](scripts/) |
| ROCm install script | [`install_rocm.sh`](install_rocm.sh) |
| Environment file | [`setenv-rocm.sh`](setenv-rocm.sh) |
| Configuration | [`config.yaml`](config.yaml) |
| Main documentation | [`README.md`](README.md) |

### 3. Demo Video (3–5 minutes)

| Status | Note |
|---|---|
| Ready | [`demo.mp4`](demo.mp4) — 3 min 51 s walkthrough covering CLI, Web UI (ChatGPT-style), RAG document Q&A, Agent task with tool calls, and Verilog generation + iverilog simulation. |

### 4. Supplementary Material (Poster)

| Status | File(s) |
|---|---|
| Ready | [`docs/poster.png`](docs/poster.png) (single-page English poster), [`docs/POSTER.md`](docs/POSTER.md) (source content), [`scripts/generate_poster.py`](scripts/generate_poster.py) (renderer) |

## Test Evidence

| Type | File |
|---|---|
| Functional tests (EN) | [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) |
| Functional tests (ZH) | [`docs/TEST_REPORT.zh-CN.md`](docs/TEST_REPORT.zh-CN.md) |
| Throughput / latency benchmark | [`docs/benchmark_qwen2.5-14b.md`](docs/benchmark_qwen2.5-14b.md), [`docs/benchmark_qwen2.5-14b.json`](docs/benchmark_qwen2.5-14b.json) |

## Integration & Deployment Notes

- ROCm-only environment: the deep-learning stack is installed from AMD sources only via [`install_rocm.sh`](install_rocm.sh).
- `setenv-rocm.sh` must be sourced before running any GPU-related command (sets `HSA_OVERRIDE_GFX_VERSION=11.0.0`, `LD_PRELOAD` glibc shim, etc.).
- OpenAI-compatible endpoint: [`scripts/serve.py`](scripts/serve.py); see [`docs/DIFY_INTEGRATION.md`](docs/DIFY_INTEGRATION.md) for Dify wiring.
- Cloud runbook (Radeon Cloud bring-up): [`docs/CLOUD_RUN.md`](docs/CLOUD_RUN.md).
- Project planning notes: [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).

## What Is Missing

- (none — all Track 2 required materials submitted)

## AI-Trace Disclosure

This repository contains no committed AI-agent configuration files (no `CLAUDE.md`, `.codebuddy`, `.cursor`, `AGENTS.md` in git), no `Co-Authored-By` AI attribution in commits, and no references to the local-only `CODEBUDDY.md` file in any submitted content. `CODEBUDDY.md` itself is listed in `.gitignore` and stays in the local working directory only.
