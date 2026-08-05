# LexiPilot

**Track:** Track 2 - Development & Local Deployment of Private AI Agents  
**Team:** `sheepdog`

**Members:** `appleboycat`, `du-du-lu`

**Project:** LexiPilot - A Private Adaptive Vocabulary Learning Agent  
**Source repository:** https://github.com/appleboycat/LexiPilot  
**Demo video:** https://github.com/appleboycat/LexiPilot/blob/main/submission/video/lexi_pilot_en.mp4

## Project

LexiPilot converts a natural-language vocabulary study goal into a validated,
adaptive learning session. Qwen3-8B selects read-only learner-state tools and
proposes a structured plan. Local deterministic code validates the plan,
presents cards, records only explicit answers, applies spaced repetition,
prioritizes current mistakes, and saves progress safely.

## Why It Fits Track 2

LexiPilot implements a hybrid private Agent loop:

```text
goal
-> Qwen3-8B read-only Tool Calling
-> learner-state evidence
-> validated JSON plan
-> deterministic interactive controller
-> explicit progress update
-> targeted bilingual practice
```

The planning model cannot call write tools. Invalid JSON, unknown words,
inconsistent evidence, unavailable tools, timeouts, and endpoint failures
activate a deterministic fallback planner.

## Submission Materials

- [Project Specification](project_specification.pdf)
- [Presentation](presentation.pdf)
- [Demo Video](demo_video.md)
- [Architecture diagram](https://github.com/appleboycat/LexiPilot/blob/main/submission/architecture/lexipilot_architecture.svg)
- [Full submission index](https://github.com/appleboycat/LexiPilot/tree/main/submission)

## AMD Radeon Deployment

- Model: `Qwen/Qwen3-8B`
- Backend: OpenAI-compatible vLLM
- Environment: dedicated AMD Radeon Cloud GPU instance with ROCm
- Tool parser: Hermes
- Final demo setting: `QWEN_ENABLE_THINKING=false`

Learner tools and progress storage remain in the user-controlled LexiPilot
environment. Only minimum task context required for planning or generation is
sent to the dedicated endpoint. Exact GPU, ROCm, and vLLM versions are supplied
through real deployment evidence and are not inferred here.

## Benchmark Summary

One warm-up and five measured requests were run per thinking mode and workload.

| Workload | Metric | Thinking enabled | Thinking disabled |
|---|---|---:|---:|
| Planning | Median latency | 13.7371 s | 13.7773 s |
| Planning | Tool-call validation | 100% | 100% |
| Generation | Median latency | 7.0341 s | 6.5433 s |
| Generation | Validation | 100% | 100% |
| Generation | Client-observed completion tokens/s | 17.9127 | 19.2563 |

Measurements include client, network, endpoint, scheduling, and serving
overhead. They are not raw GPU or kernel throughput.

## Reproduction

```bash
git clone https://github.com/appleboycat/LexiPilot.git
cd LexiPilot
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 scripts/setup_demo_data.py
python3 -m pytest -q
python3 scripts/smoke_fresh_clone.py
FORCE_COLOR=1 python3 lexipilot.py --demo --env-file .env --debug
```

Model-free fallback:

```bash
python3 lexipilot.py --demo --deterministic --no-color
```

## Privacy

The public repository excludes credentials, private endpoint URLs, real
profiles, backups, generated personal materials, complete local indexes,
private source PDFs, and derived CSV files. Reports exclude complete prompts,
responses, profiles, and tool output. Public reproduction uses sanitized sample
vocabulary and synthetic learner memory.
