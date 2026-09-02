# RugBuster CIA Intelligence Agent

**AMD AI DevMaster Hackathon — Track 2: Development & Local Deployment of Private AI Agents**

A local, LangChain-orchestrated agent that wraps RugBuster's production **CIA Intelligence
Engine** — a 7-module token-fraud-detection pipeline for DeFi/multi-chain tokens — and
classifies findings with a locally-hosted, fine-tuned **Qwen3-14B (QLoRA)** model running on
an AMD Radeon GPU via ROCm. No detection logic was changed for this submission: this repo is
an orchestration/packaging layer around already-QA'd modules (see
[docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) for scope and provenance).

## What it does

Given a token contract address (optionally with the deployer address and deploy timestamp),
the agent:

1. **Plans** which of the 7 detection modules to run and in what order, based on which inputs
   are actually available (`src/planner.py`) — multi-step task planning.
2. **Invokes** each selected module as a LangChain `StructuredTool` (`src/tools.py`,
   `src/cia_modules.py`) — tool invocation.
3. **Classifies** the aggregated structured findings with the local fine-tuned model
   (`src/llm_client.py`, `src/orchestrator.py`) to produce a GOOD / WARN / DANGER verdict with
   a natural-language rationale — local inference on Radeon GPU / ROCm.
4. Every call across a process/network boundary is HMAC-SHA256 signed and verified
   (`src/auth.py`) — permission control & privacy protection.

The 7 modules: Funding Origin (3-hop trace), Deployment Latency (sniper detection),
Transaction Entropy (bot-farm signature), Wash Pattern, Holder Cluster Age, Contract Backdoor
(bytecode selector scan), Holder Concentration.

> **Model status:** the fine-tuned Qwen3-14B checkpoint used here is an early/trial run and
> can hallucinate. `scan_with_verdict()` cross-checks the model's verdict against a
> deterministic, LLM-free risk baseline (`src/risk_baseline.py`) and flags any disagreement
> rather than trusting the model output silently — see
> [docs/PROJECT_SPEC.md §5](docs/PROJECT_SPEC.md) for the full explanation and the roadmap to
> a production-grade checkpoint.

## Environment setup

### Local dev on Windows / Z13 (gfx1151)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`llama-cpp-python` on Windows ships CPU-only ROCm wheels today (see
[docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) for the same ROCm/Windows limitation already
hit during model training) — on Windows you will run the agent in `--no-llm` mode
(planning + tools only, no GPU needed) or with CPU-only local inference. Full ROCm-accelerated
local inference is intended for Linux (native or the Radeon Cloud instance below).

### Linux (native, or AMD Radeon Cloud instance)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Rebuild llama-cpp-python against ROCm/HIPBLAS so GPU offload is used:
CMAKE_ARGS="-DGGML_HIPBLAS=on" pip install --force-reinstall --no-cache-dir llama-cpp-python
```

No `gfx11xx`-specific target is hardcoded anywhere in this repo. `src/gpu_config.py` resolves
the backend/gfx target at runtime (`ROCM_GFX_TARGET` env var → `rocminfo` autodetect → generic
fallback), so the same code runs unmodified on the Z13's gfx1151 and on whatever discrete
Radeon GPU the cloud instance provides.

### Docker (best effort — see `docker/Dockerfile`)

Intended for the Linux/Radeon Cloud target, not the Windows dev box (ROCm-in-Docker over
WSL2 is not practical for this project's timeline — see the note at the top of
`docker/Dockerfile`):

```bash
docker build -t rugbuster-cia-agent -f docker/Dockerfile .
docker run --device=/dev/kfd --device=/dev/dri --group-add video \
  -v $(pwd)/models:/app/models --env-file .env \
  rugbuster-cia-agent --chain AVAX --contract 0xTOKEN
```

## Configuration

Copy `.env.example` to `.env` and fill in explorer API keys / HMAC secret / model path as
needed. See the comments in that file for every supported variable.

## Run

Planning + tool invocation only (fast, no GPU/model required — good for verifying the agent
pipeline itself):

```bash
python main.py --chain AVAX --contract 0xTOKEN --no-llm
```

Full pipeline including the local LLM verdict (needs the GGUF model — see
`src/llm_client.py`, downloads from
[`ffurduj/syndicate-gguf`](https://huggingface.co/ffurduj/syndicate-gguf) on first run if not
present locally):

```bash
python main.py --chain AVAX --contract 0xTOKEN \
  --deployer 0xDEPLOYER --deploy-timestamp 1735689600
```

Run tests (planner logic only, no network/GPU required):

```bash
pytest tests/ -q
```

## Dependencies

See [requirements.txt](requirements.txt). Core planning/tools need only `requests`,
`pydantic`, and `langchain-core`. Local LLM inference additionally needs
`langchain-community`, `llama-cpp-python` (ROCm-built for GPU use), and `huggingface_hub`.

## Repository layout

```
hackathon-submission/
├── main.py                  # CLI entrypoint
├── requirements.txt
├── docker/Dockerfile
├── docs/PROJECT_SPEC.md     # Track 2 Project Specification Document
├── src/
│   ├── chain_client.py      # chain-agnostic explorer/RPC client (no hardcoded secrets)
│   ├── cia_modules.py       # the 7 detection modules (ported, logic unchanged)
│   ├── tools.py             # LangChain StructuredTool wrappers around the modules
│   ├── planner.py           # multi-step task planning
│   ├── auth.py               # HMAC-SHA256 permission control
│   ├── gpu_config.py         # portable ROCm/CUDA/CPU device detection
│   ├── llm_client.py         # local Qwen3-14B QLoRA GGUF client (LangChain LlamaCpp)
│   └── orchestrator.py       # CIAAgent — ties planning + tools + LLM together
├── tests/test_planner.py
└── SUMMARY.md                # what's done / what's left for manual follow-up
```

## Relationship to the production RugBuster codebase

This submission is an isolated, standalone repo. It was built by **reading** (read-only) the
production CIA Intelligence Engine in sibling repos `rugbuster-api` (the 7 modules) and
`rugbuster-scoring-engine` (the orchestration facade + HMAC auth), and porting the relevant
logic here unchanged. No production repo, branch, or deploy config was modified as part of
this work. See [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) and file-level docstrings for
exact provenance of each ported piece.
