# Sumbot - Source-Grounded Weekly Report Agent

**Track:** Track 2 - Development & Local Deployment of Private AI Agents

**Participant:** Rong Fu (solo participant; no registered team name)

**Source code:** https://github.com/doublegun9965/sumbot

**Demo video:** https://youtu.be/5oDVvO2Nt5k

**License:** MIT

## Project summary

Sumbot is a locally deployed AI agent that turns project materials into a source-grounded weekly report. It loads text, Word, PowerPoint, Excel, and PDF materials; extracts current facts with source filenames; drafts a concise report; and reviews the draft against both the original materials and extracted facts before human approval.

The application uses a fixed and inspectable Extractor -> Writer -> Reviewer workflow. Model-provider details remain isolated behind an OpenAI-compatible client so that inference can run locally through Lemonade and its bundled llama.cpp backend.

## Submission materials

| Track 2 requirement | Material |
|---|---|
| Project specification | [Sumbot_Project_Specification.pdf](Sumbot_Project_Specification.pdf) |
| Application scenarios | Project specification, Application Scenarios section |
| Agent architecture | Project specification, Agent Architecture section |
| Core capabilities | Project specification, Core Capabilities section |
| Model and local deployment | Project specification and [source README](https://github.com/doublegun9965/sumbot#readme) |
| Radeon inference optimization | Project specification, AMD Radeon GPU Use and Inference Optimization section |
| Complete source, dependencies, and startup guide | [Sumbot source repository](https://github.com/doublegun9965/sumbot) |
| 3-5 minute real-operation demo | [YouTube demo](https://youtu.be/5oDVvO2Nt5k) |
| Supplementary material | [Sumbot_Poster.pdf](Sumbot_Poster.pdf) |

## Core workflow

```text
Project materials
    |
    v
Document loading and normalization
    |
    v
Extractor - facts with source filenames
    |
    v
Writer - weekly report from extracted facts only
    |
    v
Reviewer - compare the report with facts and original materials
    |
    v
Human review and Markdown export
```

Supporting components include a FastAPI HTML interface, a single-worker background queue, local SQLite persistence, document parsing through MarkItDown, and an OpenAI-compatible model client.

## AMD Radeon environment

The recorded deployment used:

| Component | Recorded value |
|---|---|
| GPU host inventory | 8 x AMD Radeon PRO W7900D |
| GPU architecture | Navi 31, `gfx1100` |
| PCI device | `1002:744b` |
| ROCm | 7.2.1 |
| AMDSMI | 26.2.2 |
| amdgpu | 6.16.13 |
| HSA runtime | 1.18 |
| Model server | Lemonade 11.5.0 |
| Inference backend | Lemonade bundled llama.cpp backend |
| Model | `qwen2.5-32b-it-Q4_K_M-LOT` |
| Quantization | Q4_K_M |
| Sumbot mode | Real model mode (`MOCK_LLM=false`) |

The host exposed eight Radeon devices. Device visibility does not establish that one Sumbot request used all eight GPUs, so this submission makes no multi-GPU utilization or scaling claim.

## Radeon-oriented engineering

- The local model-serving backend owns ROCm kernels, model loading, quantization, and GPU memory configuration.
- Sumbot serializes model work to one job at a time to avoid local inference contention.
- Extraction, writing, and review have independent output-token limits.
- Parsed-document size and parsing time are bounded.
- Long-running inference is executed in the background so browser requests do not remain open.
- Stage elapsed times, output truncation, and failures are visible to the user.

No unverified latency, throughput, memory, quality, or multi-GPU result is claimed.

## Privacy and evidence boundaries

- Uploaded binary files are parsed in memory and are not retained as originals.
- Extracted text, task metadata, and results remain in local SQLite storage.
- Reports retain filename-level source attribution.
- The Reviewer assists human verification but cannot guarantee factual correctness.
- Mock mode is provided for deterministic workflow testing, but mock output is not evidence of AMD Radeon execution.
- Actual privacy depends on keeping the configured model endpoint local and controlling browser tunnel access.

## Quick start

```bash
git clone https://github.com/doublegun9965/sumbot.git
cd sumbot
cp env.example env.local
bash scripts/run_app.sh
```

For the real recorded configuration, set the local `env.local` values to the available Lemonade endpoint and model, with `MOCK_LLM=false`. Secrets and machine-specific configuration are intentionally excluded from Git.
