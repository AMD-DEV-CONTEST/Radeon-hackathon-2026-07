# Vulcan

A private developer-productivity agent. It indexes your codebase, then reasons, searches, reads, runs tests and answers with cited context, with **every token generated on hardware you control**, never a third-party LLM API. Built for the AMD AI DevMaster Hackathon, Track 2: Development & Local Deployment of Private AI Agents. Inference runs on AMD Radeon GPUs via ROCm.

## Quantization is a capacity decision here, not a speed one

AWQ on Qwen3-8B was measured and rejected: 0.68x of fp16 throughput, because a
48 GB card serving an 8B model has no memory problem to solve. The same card
tells the opposite story on a model that does not fit:

| | fp16 | Q4_K_M |
|---|---|---|
| Qwen3-32B weights | 61.1 GB | **18.4 GB** |
| Fits in 49,136 MB VRAM | **no** | yes |

Served on the Radeon through llama.cpp built for ROCm, all 64 layers on the GPU,
reachable over the Radeon Cloud API by changing one environment variable:

```bash
export VULCAN_BASE_URL=https://<host>/spaces/<instance>/8000/v1
export VULCAN_MODEL=Qwen3-32B-Q4_K_M
vulcan ask "which module implements the semantic index?"
```

Evidence in `bench-results/quantization.json` and
`bench-results/radeon-llamacpp-qwen3-32b-q4.json`.

## Prove it, do not trust it

```bash
vulcan privacy-check
```

Runs a real task with every outbound request recorded and fails if anything
outside your configured endpoints is contacted. The claim that no token reaches
a third party is the point of this tool, so it is checkable rather than stated.

## Why local

Your code never leaves machines you control. Agent reasoning and generation run
on one OpenAI-compatible endpoint you own: Ollama on a laptop during
development, vLLM on ROCm for production. Switching backends is one environment
variable.

Embeddings are configured separately, and on the Radeon they are not served by
the same process. `vllm serve Qwen/Qwen3-8B` starts with task=generate, so the
server exposes `/v1/chat/completions` but **no `/v1/embeddings`** (verified:
that route returns 404). Serving embeddings from vLLM needs a second process
started with `--task embed` on an embedding model, and Radeon Cloud allows one
active instance per account. So in the measured setup generation runs on the
Radeon while `VULCAN_EMBED_MODEL` points at a local embedding model. Both are
endpoints you control, and no source ever reaches a third party, but only
generation is GPU-served in this configuration. Point `VULCAN_EMBED_MODEL` at
an `--task embed` vLLM instance to move embeddings onto the GPU as well.

Model sizing matters more than backend flags on a laptop: on a 16GB machine pick a model that leaves headroom (a 4B instruct model runs a full agent turn in ~26s where a 12B thinking model swaps and takes minutes). Prefer non-thinking instruct variants for the agent loop; reasoning preambles multiply per-step latency.

## The hardware

Every Radeon number in this project was measured on one instance, whose identity
is committed verbatim in [`bench-results/radeon-device.txt`](bench-results/radeon-device.txt):
`gfx1100` (RDNA 3, Navi 31), 48.0 GiB VRAM, 48 compute units, torch
`2.10.0+rocm7.2.4`, HIP `7.2.53211`.

## Quick start

```bash
pip install -e .

# Point at any OpenAI-compatible server (default: Ollama on localhost)
export VULCAN_BASE_URL=http://localhost:11434/v1
export VULCAN_MODEL=qwen3:4b-instruct
export VULCAN_EMBED_MODEL=mxbai-embed-large

vulcan index ~/code/myproject        # build the semantic index
cd ~/code/myproject
vulcan ask "where is auth token validation done?"
vulcan chat                          # multi-turn session with persistent memory
```

## On the Radeon box (ROCm)

```bash
# vLLM with ROCm serves the same API
export VULCAN_BASE_URL=http://localhost:8000/v1
export VULCAN_MODEL=Qwen/Qwen3-8B
vulcan bench --label radeon-vllm-fp16   # TTFT + tokens/sec, saved to bench-results/
```

`vulcan bench` produces comparable JSON across backends and configs (quantization, batch size, ROCm flags), which drives the optimization section of the submission.

## Architecture

- `vulcan/llm.py`: one thin client for chat + embeddings against any OpenAI-compatible server
- `vulcan/rag.py`: line-chunked codebase index, embeddings in SQLite, cosine search (no vector-DB dependency)
- `vulcan/agent.py`: ReAct loop with a JSON tool protocol (works on backends without native tool-calling)
- `vulcan/tools.py`: sandboxed tools, path-jail on file access, allowlisted commands only
- `vulcan/memory.py`: durable per-project notes that survive across sessions
- `vulcan/bench.py`: TTFT / throughput harness for the ROCm optimization writeup

## Dependencies

Python 3.10 or newer. Four runtime packages, declared in `pyproject.toml`:

| package | version | used for |
|---|---|---|
| `httpx` | >=0.27 | streaming HTTP to the OpenAI-compatible endpoint |
| `numpy` | >=1.26 | cosine similarity over the embedding index |
| `typer` | >=0.12 | CLI |
| `rich` | >=13.7 | terminal output |

Development adds `pytest` >=8.0. There is no vector database, no LangChain and
no agent framework: the index is SQLite plus numpy and the ReAct loop is about
a hundred lines in `vulcan/agent.py`.

A backend is also required, one of:

- **Ollama** for local development, serving both chat and embeddings
- **vLLM on ROCm** for GPU generation, plus a local embeddings endpoint (see above)

## Environment configuration

Every value is read from the environment; nothing is hardcoded. Copy
`.env.example` to `.env` and fill it in.

| variable | default | meaning |
|---|---|---|
| `VULCAN_BASE_URL` | `http://localhost:11434/v1` | chat endpoint |
| `VULCAN_API_KEY` | `local` | key for that endpoint |
| `VULCAN_MODEL` | `qwen3:4b-instruct` | generation model |
| `VULCAN_EMBED_BASE_URL` | falls back to `VULCAN_BASE_URL` | embeddings endpoint |
| `VULCAN_EMBED_API_KEY` | falls back to `VULCAN_API_KEY` | key for that endpoint |
| `VULCAN_EMBED_MODEL` | `mxbai-embed-large` | embedding model |
| `VULCAN_ENABLE_THINKING` | unset (sends nothing) | `false` cuts agent-step latency ~3.5x on Qwen3 via vLLM |
| `VULCAN_TEMPERATURE` | `0.2` | sampling temperature |
| `VULCAN_MAX_STEPS` | `12` | ReAct step ceiling |
| `VULCAN_DATA_DIR` | `~/.vulcan` | index and memory storage |

## Tests

```bash
pip install -e ".[dev]"
pytest
```
