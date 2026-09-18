# Radeon Sentinel

**Logs never leave the laptop.**

Radeon Sentinel is a **private SRE co-pilot** — a locally deployed AI agent that
investigates service incidents entirely on an AMD Radeon GPU via ROCm. Your logs,
configs, and runbooks are read by a model that lives on your machine, never sent
to any cloud API.

Built for **Track 2 (Private AI Agents)** of the
[AMD AI DevMaster Hackathon](https://luma.com/amd-4dhi).

> Co-pilot, not autopilot: the agent retrieves runbooks, runs allow-listed
> read-only diagnostics, and produces a cited diagnosis — but every
> state-changing action is gated behind explicit human approval. Across all
> three demo scenarios, **zero** unapproved actions were executed.

> Status: core inference validated on Radeon Cloud (gfx1100, ROCm 7.2.1),
> GPTQ-Int4 optimized to 96 tok/s (↑227% over float16). 11/11 tests passing.
> Quality A/B confirms no semantic regression: root-cause hit rate and
> structure conformance both 100% on Int4. English spec, video, and poster
> ready for submission.

## Demo video

[Watch the 4:45 Radeon Sentinel demo](https://app.notion.com/p/linguistwantstech/radeon-sentinel-demo-3b234433b7e280db9777d470ba4cfed1?source=copy_link).

The public video is 1920×1080 H.264 with AAC narration and hard-coded English
and Chinese subtitles. It demonstrates the live Radeon/ROCm environment, local
inference endpoint, full agent workflow, approval gate, audit trail, and the
measured float16 versus GPTQ-Int4 optimization result.

## Why this project

The Track 2 rubric rewards a complete, useful agent and gives 40 points to AMD
Radeon/ROCm execution and optimization, plus a possible 20-point optimization
bonus. Radeon Sentinel is scoped to demonstrate all five listed agent
capabilities:

- local knowledge retrieval (RAG);
- allow-listed tool invocation;
- multi-step task planning;
- local multi-turn memory;
- explicit permission and privacy controls.

The narrow incident-response workflow keeps the demo measurable and realistic
within the contest window.

## Current vertical slice

Given a synthetic service incident, Radeon Sentinel will:

1. ingest local logs, service metadata, and runbooks;
2. retrieve evidence and produce a cited diagnosis;
3. create a step-by-step response plan;
4. run read-only diagnostic tools in a sandbox;
5. pause for approval before a simulated remediation;
6. retain a local audit trail and case memory;
7. expose the workflow through a CLI and optional Gradio UI.

The repository includes three synthetic scenarios: API saturation,
configuration drift, and an upstream dependency failure. The default mock model
makes the workflow deterministic and testable without credentials. An
OpenAI-compatible adapter can use the Radeon Cloud shared API during development
and a dedicated vLLM endpoint for the final local-GPU demonstration.

## Implemented stack

- Python 3.9+
- dependency-free core workflow and BM25-style local runbook retrieval
- OpenAI-compatible model adapter with a deterministic offline mock
- allow-listed synthetic diagnostic tools with a default-deny policy
- SQLite for local case memory and audit records
- optional Gradio demo UI
- pytest for workflow and policy tests

Core inference runs on AMD Radeon (gfx1100) via ROCm 7.2.1 + vLLM 0.16.1,
serving Qwen2.5-7B-Instruct at float16 (baseline) and GPTQ-Int4 (optimized).
Both variants were benchmarked on the designated environment (see
`docs/optimization-report.md` and `docs/evidence/`), and the Int4 quality
trade-off was verified offline over the 20-run capture
(`scripts/quality_eval.py`): no diagnostic regression.

## Quick start

Run the tested offline workflow:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python -m radeon_sentinel --incident api_latency
```

The simulated restart is denied by default. Explicitly approve it for a
permission-path demo:

```bash
python -m radeon_sentinel \
  --incident config_drift \
  --approve-remediation
```

The approved action is still a simulation and never reaches a real service.

Install and launch the optional UI:

```bash
python -m pip install -e ".[demo]"
python -m radeon_sentinel.app
```

## Radeon model configuration

Copy `.env.example` values into your environment; do not commit a real key.
For a shared Radeon Cloud API or a dedicated vLLM endpoint:

```bash
export SENTINEL_MODEL_MODE=openai
export MODEL_BASE_URL="https://your-endpoint.example/v1"
export MODEL_API_KEY="replace-me"
export MODEL_NAME="replace-me"
python -m radeon_sentinel --incident dependency_failure
```

The adapter sends requests only to the configured OpenAI-compatible
`/chat/completions` endpoint. Mock mode remains the default when these settings
are absent.

## Safety behavior

- Only `inspect_service_health`, `search_logs`, and `restart_service` are
  allow-listed.
- Unknown tools are denied.
- The first two tools are read-only and operate only on synthetic fixtures.
- The restart tool requires explicit approval and records only a simulated
  action.
- Case memory and the append-only audit log are local SQLite data.
- API keys are read from environment variables and never included in model
  prompts or audit output.

## Success criteria

- Reproducible end-to-end demo on Radeon Cloud with ROCm.
- Core inference visibly executed on an AMD Radeon GPU.
- At least three reliable incident scenarios, including one permission-denied
  path.
- Correct evidence citations and a complete local audit trail.
- Recorded baseline and optimized latency, throughput, VRAM, and task-success
  results.
- English report, README, 3–5 minute demo video, and poster ready before the
  deadline.

## Repository map

```text
src/radeon_sentinel/
  agent.py                    Investigation workflow
  retrieval.py                Local runbook retrieval
  tools.py                    Allow-listed synthetic tools
  memory.py                   SQLite case memory and audit
  model.py                    Mock and OpenAI-compatible clients
  cli.py / app.py             CLI and optional Gradio UI
demo_data/
  incidents/                  Three synthetic incident fixtures
  runbooks/                   Local evidence corpus
tests/                        Policy and vertical-slice tests
docs/
  SPECIFICATION.md           Track 2 project specification
  optimization-report.md     Radeon/ROCm benchmark analysis
  poster.png                 Submission poster
  evidence/                  Raw ROCm and optimization evidence
scripts/
  serve_vllm.sh              Reproducible Radeon vLLM launch command
  rocm_capture.py            Environment and benchmark capture
  quality_eval.py            Offline quality-regression evaluation
README.md                     Reproduction and project guide
SECURITY.md                   Safety boundary for agent tools
```

## Submission

This repository contains the complete English Track 2 deliverables: source
code, reproduction instructions, project specification, Radeon/ROCm benchmark
evidence, optimization analysis, poster, and the 4:45 public demo video.

## Official references

- [Event page](https://luma.com/amd-4dhi)
- [Official contest repository](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
- [Radeon Cloud guide](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/tree/main/Radeon-Cloud-User%20Guide)
- [Rules and Conditions](https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit?tab=t.0)

## License

Licensed under the **Apache License, Version 2.0**. See [`LICENSE`](LICENSE).

The model weights (**Qwen2.5-7B-Instruct** and the official GPTQ-Int4 variant)
are licensed under
[Apache-2.0](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/blob/main/LICENSE)
and are not redistributed in this repository.
