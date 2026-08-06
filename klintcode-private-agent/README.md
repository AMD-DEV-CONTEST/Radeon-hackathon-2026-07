# KlintCode Private Agent

A compact, end-to-end **reference pipeline** for an enterprise-grade, **private deployment (local-first)** coding agent. It runs Qwen3.6-35B-A3B locally on an AMD Radeon PRO W7900 through ROCm-enabled llama.cpp, keeping business requirements, models, and generated source code on the local system.

The demo walks the full path from an initial prompt to an autonomously generated, 80-object domain-driven microservice system, pushing the limits of the **256K context window** on local hardware.

> **How the system works:** The LLM provides intelligence, KlintCode controls the process, and TeaQL guarantees deterministic output. The AMD GPU performs local LLM inference; TeaQL generates Rust code and the Rust compiler verifies it on the host CPU.

## Pipeline (M1 -> M5)

| Stage                                    | What it does                                                                       | Key files / Directories                                                   |
| ---------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **M1 — Prompt & Initialization**         | Ingests complex business requirements and sets up the 256K context budget.         | `agent-source-code/crates/context-builder/src/`                           |
| **M2 — Agent Reasoning & Planning**      | Queries Qwen3.6 through llama.cpp's OpenAI-compatible API to design the domain.     | `agent-source-code/crates/agent-core/src/agent_loop.rs`                   |
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
      model-vllm/                     # Legacy crate name; OpenAI-compatible local inference client
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

The submitted private deployment uses one consistent local inference configuration:

| Environment | Inference Engine | Hardware | Model | Endpoint | Context Window | Key Parameters / Optimizations |
| --- | --- | --- | --- | --- | --- | --- |
| **Local Private Deployment** | ROCm-enabled llama.cpp | AMD Radeon PRO W7900 48GB | Qwen3.6-35B-A3B GGUF Q4_K_M | `http://127.0.0.1:8000/v1` | 262,144 tokens | Full GPU layer offload (`-ngl 99`)<br>Single inference slot (`-np 1`)<br>Quantized MoE weights<br>`enable_thinking=false` |

The measured deployment uses approximately 20.4GB for model weights and around 26GB of VRAM during long-context inference. Generation reaches approximately 88-92 tokens/s, and prompt processing reaches approximately 1,605 tokens/s for a 40K-token prompt. See the installation guide below for commands and measurement details.

## Dependencies
- **[TeaQL](https://api.teaql.io/latest/)**: The foundational schema language and compiler used for generating the underlying Rust microservices. *(Note: The author of this hackathon submission is the original owner and maintainer of the TeaQL service and ecosystem.)*
- **teaql-agent-kit**: Provides the backend API generation service and essential toolchain base libraries that KlintCode relies upon for its autonomous execution.
- **llama.cpp (ROCm build)**: Serves the quantized model through an OpenAI-compatible local endpoint and offloads all supported model layers to the W7900.

## Prerequisites for Code Generation (M5 Phase)

The published Docker image includes KlintCode, Rust, Cargo, and `cargo-teaql` 2.0.8, so M1-M5 can run in the same container. For a native installation, install the following tools:

1. **Install Rust Environment:**
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   source $HOME/.cargo/env
   ```

2. **Install Cargo TeaQL Toolchain:**
   ```bash
   cargo install cargo-teaql --version 2.0.8 --locked
   cargo-teaql install-links
   ```

## How to run on AMD Radeon (ROCm)

Start the ROCm-enabled llama.cpp server using the linked installation guide, then run the complete agent and TeaQL build environment in Docker. Host networking lets the container reach the local OpenAI-compatible endpoint at `127.0.0.1:8000`.

```bash
# 1. Ensure llama-server is running on the host at 127.0.0.1:8000.
# 2. Run the KlintCode Private Agent TUI with a persistent workspace.
docker run --rm -it --network host \
  -v "$(pwd):/workspace" \
  -w /workspace \
  teaql/klintcode-private-agent:latest
```

*(Note: Alternatively, if you must use a standard bridge network, you can override the endpoint via `-e KLINTCODE_ENDPOINT="http://host.docker.internal:8000"`)*

The image contains the full M5 toolchain. You can verify it with:

```bash
docker run --rm --entrypoint sh teaql/klintcode-private-agent:latest \
  -lc 'rustc --version && cargo --version && cargo-teaql --version'
```

**Model Deployment on AMD W7900:**
For a comprehensive guide on how we deployed, benchmarked, and served the Qwen3.6-35B-A3B model on the AMD Radeon PRO W7900 48GB using ROCm, please refer to the [AMD W7900 Model Installation Guide](./AMD_W7900_Model_Installation_Guide.md).

## Demonstration Video
[Bilibili - Highlights (Short Version)](https://www.bilibili.com/video/BV1vfuH61ELo/)
[Bilibili - Full Demonstration (Long Version)](https://www.bilibili.com/video/BV1yzuH6tExR/?vd_source=eec3d622b3269b343c727d6e337b9fdf)

*Recommended duration: 3-5 minutes.*
The video demonstrates the KlintCode Private Agent autonomously generating the 80-object moving company system in a local AMD Radeon environment, highlighting the fluid interaction, reasoning process, and functional completeness.

## Presentation / Poster (PPT)
[KlintCode Private Agent - Presentation (PDF)](./KlintCode-Private-Agent-Presentation.pdf)

The presentation highlights the practical value of the tool, business scenarios, the underlying agent architecture, and the optimizations used for running locally on AMD ROCm.

## Reproducible benchmark evidence

The checked-in private-deployment benchmark contains 81 business objects across 10 included model files plus `main.xml`. The final gate is deterministic: TeaQL validation must report zero errors, followed by `cargo check` in the generated Rust workspace. GPU acceleration is used for LLM inference; code generation and compiler verification run on the local host CPU.
