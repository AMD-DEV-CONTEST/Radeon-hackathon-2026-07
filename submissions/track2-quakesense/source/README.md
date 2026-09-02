# QuakeSense public-safe source

This directory contains the inspectable implementation used by the Track 2 submission. Private datasets and generated run arrays are not required for the included unit tests or replay viewer.

## Architecture

- `quakesense_public/` — compact reference implementation of departure timing, edge capacity, shelter admission, and conservation.
- `claude/simulator/` — device-oriented swarm state, block routing, jurisdiction partitioning, constrained local-LLM leaders, and time-step kernels.
- `claude/geo/urban_blocks.py` — city-agnostic road-enclosed block construction.
- `claude/rl/` — shelter-allocation agent implementation.
- `claude/scripts/` — generic preparation, terrain, replay, validation, and analysis utilities.
- `claude/tests/` and `tests/` — mechanism, conservation, routing, and capacity checks.

City-specific private preparation scripts, absolute workstation paths, credentials, generated data, and unpublished evidence are excluded from the public submission.

## Environment

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install the ROCm-compatible PyTorch build appropriate for the Radeon host separately. The compact public tests use only the Python standard library; the full simulator uses NumPy, SciPy, NetworkX, geospatial packages, and PyTorch.

## Run checks

```bash
python -m pytest tests -q
python -m pytest claude/tests -q
```

## Local agent deployment

`claude/simulator/llm_leaders.py` sends grammar-constrained requests to a local OpenAI-compatible or llama.cpp-style endpoint. Configure the endpoint in the calling application; keep tokens and model weights outside Git. The decision grammar permits only offered shelter identifiers or the bounded hold action, so an unconstrained text response cannot silently become a simulator command.

## Public replay

The browser viewer and seven archived payloads are in `../public_demo/`. They are served as static files and do not require private source data.
