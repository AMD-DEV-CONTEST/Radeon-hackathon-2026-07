# FlintCode Private Agent

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
FlintCode-Private-Agent/
  agent-source-code/                  # The full FlintCode private agent framework
    apps/
      flintcode-cli/                  # Command-line interface for autonomous batch generation
      flintcode-tui/                  # Interactive terminal UI for real-time monitoring of agent reasoning
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

## How to run on AMD Radeon (ROCm)
(Detailed environment setup and step-by-step reproduction instructions will be provided here...)

## Demonstration Video
[Link to Demo Video (YouTube/Bilibili/Drive) - To be updated]

*Recommended duration: 3-5 minutes.*
The video demonstrates the FlintCode Private Agent autonomously generating the 80-object moving company system in a local AMD Radeon environment, highlighting the fluid interaction, reasoning process, and functional completeness.

## Presentation / Poster (PPT)
[Link to PPT/Poster (PDF) - To be updated]

The presentation highlights the practical value of the tool, business scenarios, the underlying agent architecture, and the optimizations used for running locally on AMD ROCm.
