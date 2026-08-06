# FastAgentFactory Project Specification

## Project Positioning

FastAgentFactory is a fully local, manufacturable, composable, and auditable private AI Agent platform. It packages prompts, models, tools, skills, knowledge, resources, memory, scheduling, and workflows into AgentPackages and manages their lifecycle from manufacturing and validation to publication, execution, and evolution.

The primary application is a long-running personal AI assistant. Core model inference runs on AMD Radeon GPUs with ROCm. Task planning, tool calls, retrieval, memory, and multi-agent collaboration do not depend on a closed-source Agent platform.

## Application Scenarios

### Personal Knowledge and Task Assistant

Users can attach local files and knowledge bases. Agents retrieve relevant evidence, produce reports, preserve artifacts, and carry relevant user preferences across sessions.

### Office Automation Assistant

Agents can combine local files, web search, schedules, email, and approval-aware tools to complete research, document production, periodic monitoring, and controlled delivery.

### Multi-agent Research Assistant

A main agent selects published AgentPackages, decomposes a goal, delegates isolated subtasks, monitors collaboration activity, semantically reviews submitted artifacts, and assembles a final deliverable.

### Financial Research Example

Three built-in U.S. equity agents demonstrate market monitoring, listed-company research, and portfolio risk analysis. They use Yahoo Finance market data and SEC company disclosures, can work independently or be coordinated by the personal assistant, and produce research-only demonstration output that is not investment advice.

### Manufacturable Specialist Assistant

Users can manufacture an AgentPackage from a natural-language requirement and evolve it later using runtime traces, failure evidence, and new objectives.

See [Application Scenarios](ApplicationScenarios.md) for task-pattern mapping and safety boundaries.

## Agent Architecture

![FastAgentFactory Agent architecture](assets/diagrams/fastagentfactory-agent-architecture-native.png)

The architecture separates user experience, the Factory control plane, Agent runtime, tool/resource gateways, and local AI infrastructure. Sessions, workspaces, tool output, resources, and collaboration tasks have explicit isolation boundaries. See [Agent Architecture](AgentArchitecture.md).

## Core Capabilities

### Agent Manufacturing and Evolution

- Generate complete AgentPackages from natural-language goals.
- Validate patterns, prompts, tools, skills, knowledge, resources, and dependencies.
- Use manufacturing traces, tool probes, and final validation to constrain publication quality.
- Evolve published agents from observed failures and user objectives.

### Tool Calling and Workflow Orchestration

- Support `react_agent` and `plan_and_execute`.
- Route built-in tools, MCP, skills, package tools, and model tools through a unified gateway.
- Enforce workspace boundaries, approval policies, resource injection, and audit trails.
- Support plans, retries, interruption recovery, scheduled tasks, and file delivery.

### RAG, Memory, and Context Governance

- Ingest, retrieve, open, and cite local knowledge.
- Isolate session and package state.
- Assemble context under explicit token budgets and compression thresholds.
- Configure package-level cross-session memory writes and retrieval injection.

### Multi-agent Collaboration

- Search and select specialist AgentPackages.
- Run sub-agents with isolated sessions, workspaces, and tool outputs.
- Apply inference-slot backpressure and idempotent environment initialization.
- Resume the main agent when a task is submitted, blocked, or failed.
- Use semantic delivery criteria rather than brittle package-specific field rules.

### Privacy, Permissions, and Observability

- Execute Agent workloads as supervised native subprocesses with isolated session workspaces and dependency environments.
- Limit files to the active workspace boundary.
- Encrypt resource values and inject them only into authorized packages.
- Audit traces, tool calls, model usage, task state, token consumption, and artifacts.

See [Core Capabilities](CoreCapabilities.md) for the implementation-oriented capability map.

## Models and Local Deployment

| Role | Default model | Runtime |
| --- | --- | --- |
| Chat | Qwen3.6-35B-A3B APEX GGUF | llama.cpp + ROCm/HIP |
| Embedding | BAAI/bge-m3 | Transformers + PyTorch ROCm |
| Image generation | FLUX.1-dev Q4_0 | stable-diffusion.cpp + HIPBLAS |

Model profiles define capabilities, context, YaRN extension, output limits, concurrency slots, KV cache types, Flash Attention, MTP, GPU layers, and VRAM estimates. The inference control node manages loading, unloading, implementation switching, capacity checks, GPU telemetry, and benchmarks.

Two topologies share the same runtime interfaces:

- `DEPLOY_TARGET=local`: Web, Agent runtime, and AMD inference services run on one Linux/ROCm host.
- `DEPLOY_TARGET=ssh`: Web and Agent runtime run on a control host and reach loopback-only AMD inference services through SSH tunnels.

See [Deployment and Acceptance](Deployment.md) for reproducible setup and validation.

## AMD Radeon GPU Inference Optimization

The repository builds two llama.cpp implementations from the same baseline revision. Official is the comparison baseline; AMD carries native HIP changes. Paired benchmarks use the same model, prompt, context, cache policy, sampling parameters, and output limit.

Implemented and evaluated directions include:

- Reuse Q8_1 activation quantization across compatible MatVec dispatches.
- Fuse Residual Add, RMSNorm, and weight scaling to reduce launches and memory traffic.
- Use a native RDNA3 Wave32 Q6_K × Q8_1 MatVec kernel.
- Record host shapes and kernel selection to distinguish eligibility from actual dispatch.
- Use MTP speculative decoding to validate multiple candidate tokens per target forward pass.

The measured results use two separate attribution scopes:

- With MTP disabled, AMD improved single-token Decode throughput from `84.0867 tok/s` to `88.8320 tok/s`, a `5.64%` gain over Official.
- With MTP enabled for both implementations, Decode was effectively tied. AMD improved Prompt throughput by `16.70%`, reduced model-compute TTFT by `14.31%`, improved two-client QPS by `5.09%`, and reduced mean request latency by `4.89%`.

MTP changes the decode schedule for both implementations, so its scheduling gain is not attributed to AMD kernels. Results are specific to the tested model, shapes, ROCm version, and RDNA3 GPU and are not universal performance claims.

See [AMD Radeon GPU Inference Optimizations](performance/ROCmOptimizations.md) for implementation details, comparisons, and limitations.

## Stability and Response Performance

- Capacity estimation uses actual slots, per-slot context, KV cache types, and VRAM budget.
- Normal benchmarks report Prefill, Decode, MTP, VRAM, power, and KV-prefix reuse.
- Concurrency benchmarks report QPS, aggregate input/output TPS, error rate, TTFT P95, and latency P95.
- Operator analysis uses rocprof and GGML traces for attribution and never presents profiler timing as normal service throughput.
- Containers, SQLite connections, sessions, workspaces, and tool output follow explicit ownership boundaries.

## Open-source Components, Models, and Data

Third-party source code, model weights, and external data providers retain their own licenses and terms. Model weights are downloaded during deployment and are not committed to the repository. Market data is retrieved from public services at runtime; users remain responsible for provider terms, rate limits, and authorization.
