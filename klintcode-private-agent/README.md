# KlintCode Private Agent

A compact, end-to-end **reference pipeline** for an enterprise-grade, **private deployment (Local-first)** coding agent. Built specifically for AMD Radeon GPUs (ROCm), this agent eliminates data leakage risks by keeping proprietary corporate IP entirely local.

The demo walks the full path from an initial prompt to an autonomously generated, 80-object domain-driven microservice system, pushing the limits of the **256K context window** on local hardware.

> **Note**: This project demonstrates the extreme capabilities of local inference on AMD hardware. The generated 80-object moving company backend represents weeks of human developer effort, fully modeled and compiled by the agent without internet access.

## Pipeline (M1 -> M5)

| Stage                                    | What it does                                                                       | Key files / Directories                                                   |
| ---------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **M1 — Prompt & Initialization**         | Ingests complex business requirements and sets up the 256K context budget.         | `agent-source-code/crates/context-builder/src/`                           |
| **M2 — Agent Reasoning & Planning**      | Queries the LLM (vLLM on ROCm) to design the initial domain architecture.          | `agent-source-code/crates/agent-core/src/agent_loop.rs`                   |
| **M3 — Generation & Execution**          | Outputs XML models using tools, splitting complexity across decoupled files.       | `benchmark-private-deployment/models/*.xml`                               |
| **M4 — Self-Correction (Evaluate)**      | Runs syntax checks and automatically triggers repairs for missing references.      | `agent-source-code/crates/validation/src/`                                |
| **M5 — Final Compilation**               | Translates the verified XML schema into a working Rust microservice library.       | `benchmark-private-deployment/models/main.xml`                            |

## Repository layout

```
KlintCode-Private-Agent/
  agent-source-code/                  # The full KlintCode private agent framework
    apps/
      klintcode-cli/                  # Command-line interface for autonomous batch generation
      klintcode-tui/                  # Interactive terminal UI for real-time monitoring of agent reasoning
    crates/
      agent-core/                     # Core autonomous agent loop (reasoning, tool execution, and self-repair)
      context-builder/                # Dynamic prompt engineering engine (supports 256K token budget without memory drop)
      model-vllm/                     # Interface for local vLLM instances (optimized for ROCm PagedAttention)
      pipeline/                       # Orchestrates the end-to-end task pipelines (Prompt -> XML -> Rust)
      tool-runner/                    # Secure sandboxed executor for bash commands and compiler feedback parsing
      validation/                     # Strict domain schema validator that checks generated XML models
    Cargo.toml                        # Rust workspace configuration
  benchmark-private-deployment/       # The generated benchmark output
    models/                           # 10 decoupled XML files (80+ entities)
      operations_extended.xml         # Massive 14KB logistics entity model
      employees.xml                   # Payroll and staff registry logic
      finance.xml                     # Invoicing and accounting logic
  README.md                           # This file
```

## Model & Inference Configuration

To achieve the optimal balance of speed, privacy, and massive context reasoning, KlintCode employs a hybrid AMD infrastructure approach using the Qwen model series. The specific configurations are detailed below:

| Environment | Inference Engine | Hardware | Model | Endpoint | Context Window | Key Parameters / Optimizations |
| --- | --- | --- | --- | --- | --- | --- |
| **Local Private Deployment** | vLLM (ROCm optimized) | AMD Radeon RX 7900 XTX | qwen3.6-35b-a3b-q4_k_m | `http://127.0.0.1:8000/v1` | 256K | `enable_thinking=false`<br>`max_model_len=262144`<br>ROCm PagedAttention & KV Cache |
| **Cloud Service (AMD Token Factory)** | AMD Token Factory API | Cloud / Serverless | Qwen3.6-35B-A3B | `https://developer.amd.com.cn/radeon/api/v1` | 128K | `max_tokens=256`<br>`enable_thinking=false` |

## Dependencies
- **[TeaQL](https://api.teaql.io/latest/)**: The foundational schema language and compiler used for generating the underlying Rust microservices.
- **teaql-agent-kit**: Provides the backend API generation service and essential toolchain base libraries that KlintCode relies upon for its autonomous execution.
- **vLLM (ROCm version)**: The high-throughput inference engine used to serve the large language model natively on AMD hardware.

## How to run on AMD Radeon (ROCm)
(Detailed environment setup and step-by-step reproduction instructions will be provided here...)

## Demonstration Video
[Bilibili - Highlights (Short Version)](https://www.bilibili.com/video/BV1vfuH61ELo/)
[Bilibili - Full Demonstration (Long Version)](https://www.bilibili.com/video/BV1yzuH6tExR/?vd_source=eec3d622b3269b343c727d6e337b9fdf)

*Recommended duration: 3-5 minutes.*
The video demonstrates the KlintCode Private Agent autonomously generating the 80-object moving company system in a local AMD Radeon environment, highlighting the fluid interaction, reasoning process, and functional completeness.

## Presentation / Poster (PPT)
[Link to PPT/Poster (PDF) - To be updated]

The presentation highlights the practical value of the tool, business scenarios, the underlying agent architecture, and the optimizations used for running locally on AMD ROCm.
