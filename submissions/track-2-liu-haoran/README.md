# Work Assistant

**AMD AI DevMaster Hackathon 2026 - Track 2: Development & Local Deployment of Private AI Agents**

- **Participant:** Liu Haoran (`@Maomaodesu`)
- **Application:** Work Assistant
- **Source code:** [Maomaodesu/work-assistant-agent](https://github.com/Maomaodesu/work-assistant-agent)
- **Demo video:** [Watch the 3-5 minute demonstration on Bilibili](https://www.bilibili.com/video/BV1weu76jEb2/)
- **Project specification:** [project-specification.md](project-specification.md)
- **Presentation:** [work-assistant-track-2-demo-deck.pptx](work-assistant-track-2-demo-deck.pptx)

## Overview

Work Assistant is a local-first workspace for developers who work with Code Agents. It unifies scattered local AI conversation histories, work items, and project context. The application helps a developer recover after an interruption by identifying the source of a task, the evidence of progress, and the next recommended action.

## Core Capabilities

- LangGraph workflows for task planning, project assessment, and evidence-based progress analysis.
- Local inspection of Git metadata and file changes before an LLM produces task plans, conclusions, risks, and next-step recommendations.
- Incremental RAG for long Code Agent histories: it processes only new or changed conversation segments, retrieves relevant local context, and uses hierarchical summaries to bound context and inference cost.
- Traceable work items that retain their source conversation and can export continuation prompts for other Code Agents.
- Local conversation management, filtering, and analysis by Code Agent provider and project.

## AMD Radeon Cloud Deployment

The submitted deployment serves `Qwen/Qwen3-14B` on an AMD Radeon Cloud dedicated GPU instance. The service runs with ROCm 7.2.1 and vLLM 0.16.0, exposing an OpenAI-compatible endpoint that the local Work Assistant uses without business-workflow changes.

The included project specification records a reproducible non-streaming endpoint measurement: three 128-token responses averaged **9,043.72 ms** end-to-end latency and **14.15 completion tokens/s**. The deployment is shown with redacted configuration evidence in the demo video. No unmeasured before/after speedup is claimed.

## Reproducibility

Environment setup, dependencies, startup instructions, inference configuration, and test instructions are maintained in the [source repository README](https://github.com/Maomaodesu/work-assistant-agent#readme).
