# Core Capabilities

## 1. Agent Lifecycle

### Manufacturing

The Factory turns a natural-language requirement into an AgentPackage containing identity, prompts, model bindings, tools, skills, knowledge, resources, context, memory, dependencies, runtime pattern, and validation metadata. Manufacturing uses one contract model from authoring through runtime instead of converting into a second internal format.

### Evolution

Evolution starts from an existing published package, selected trace evidence, failure context, and a new objective. It edits only the intended package surfaces, validates the complete package, and produces a new publishable revision.

### Package Management

Published packages expose configuration, runtime state, resources, model/tool descriptions, context policy, memory write interval, sessions, workspaces, and artifacts. Package initialization is idempotent and single-flight, while conversation data remains session-isolated.

The manufacturing workspace below exposes stage progress, resource declarations, tool validation, and publication state. The UI is an observability surface; it does not bypass runtime validation.

## 2. RuntimeKernel and Graph Orchestration

RuntimeKernel executes the pattern declared by the package:

- `react_agent`: iterative reasoning, tool invocation, observation, and response.
- `plan_and_execute`: planning, step execution, state updates, and final synthesis.

Both patterns use the same context, memory, knowledge, tool, artifact, checkpoint, trace, and final-answer systems. Final answers can use the unified tool gateway when the declared workflow requires a last delivery action.

## 3. Model System

### Model Pool

The model pool manages local and external profiles for chat, embedding, and image generation. Profiles describe modality, tool calling, reasoning, model description, native context, YaRN extension, output limit, concurrency, KV cache, Flash Attention, GPU layers, MTP, and VRAM policy.

In the AMD competition deployment, the control host stores external profiles that point to the inference node. Model files, the ROCm runtime, llama.cpp slots, and Embedding/Image services remain on the AMD host. SSH tunnels change only transport; profile selection, role defaults, and capability checks still come from the control-host ModelPoolStore through `/profiles` and `/defaults`. The frontend does not maintain a separate online model catalog.

### Runtime Selection

Model selection considers role, modality, tool-calling support, reasoning support, context requirements, and the profile description. Packages can bind models explicitly or use role defaults. Model-tool bindings remain separate from the main chat model.

### Reasoning and Multimodality

Sessions expose reasoning intensity and model choice where supported. The image model is invoked through the existing model-tool abstraction, and generated images are stored as workspace artifacts rather than inserted as base64 model context.

## 4. Tool System

### Tool Sources

- Built-in filesystem, shell, scheduler, knowledge, collaboration, and artifact tools
- Installed MCP servers such as Web Search
- Package-local tools
- Package-local or installed skills
- Model tools such as image generation

### Unified Governance

All tools pass through the same gateway for schema validation, runtime ownership, path boundaries, approval policy, resource injection, output compression, persistence, and trace emission. Collaboration does not invent a second tool-execution policy. Workspace file tools can deliver files directly; shell remains subject to its explicit risk and approval configuration.

## 5. Sessions, Checkpoints, and State

Each session owns its conversation, checkpoint thread, workspace, tool output, memory interaction, and runtime trace. FactoryChat follows the same session model as published AgentPackages. Normal and collaboration sessions are separated in the UI but remain visible and recoverable.

Checkpoint persistence supports interruption recovery. Restart recovery distinguishes genuinely running work from stale assignments and reacquires eligible collaboration tasks without duplicating workers.

## 6. Context and Memory

### Context Assembly

The context assembler projects only the state needed by the active model call. It combines the system prompt, conversation, tool observations, plans, knowledge, memory, and runtime status under an explicit token budget.

Package context configuration can override the environment context window and compression threshold. The effective per-slot context is used consistently by compression and VRAM estimation.

### Cross-session Memory

The memory system asynchronously extracts durable user preferences and decisions after a configurable number of completed user turns. The default interval is three turns, and an AgentPackage can override it from the package detail view. Memory retrieval is scoped, relevance-filtered, and separate from raw conversation replay.

## 7. Knowledge and RAG

Knowledge sources can be attached at package or session scope. The runtime performs ingestion, chunking, embedding, retrieval, opening, and citation. Authored package assets are not automatically treated as runtime knowledge; they must be declared through the knowledge contract.

The knowledge UI exposes source registration, background ingestion state, and document access. A source becomes retrievable only after ingestion completes and the relevant knowledge contract is active.

## 8. Resources and Secrets

Resource descriptors declare structured value schemas, validation constraints, and consuming tools. Users configure each resource from package details. Values are encrypted at rest using the local master key and are not written back into AgentPackage source files. Configured values can be revealed in the authorized UI while password controls remain visually masked by default.

## 9. Scheduler

Scheduled tasks use stable task identities and dedicated execution records. A rerun replaces the failed active attempt instead of accumulating duplicate live sessions, and retry guidance can include the prior failure reason. Scheduled activity is visible from every session through a dedicated view; an active related chat can receive status cards.

The scheduled-task view selects an execution target from the active context and exposes task creation, status, and run-history entry points. Triggering, leases, and failure recovery remain owned by the Scheduler Runtime.

## 10. Artifacts and Delivery

Workspace artifacts include reports, presentations, structured files, and images. The artifact system records paths, media type, ownership, and preview/download metadata. Collaboration workspaces create a `share_files` delivery area automatically. Acceptance is semantic: the main agent defines the required meaning and inspects the actual deliverables rather than relying on brittle package-specific field names.

## 11. Trace, Usage, and Benchmarking

- Runtime trace: model calls, reasoning summaries, tool calls, approvals, errors, and state transitions
- Model usage: local-model input/output tokens, cache use, duration, and session totals
- Collaboration inspection: task state, recent collaboration activity, and recent reasoning summaries
- Performance: Prefill/Decode throughput, QPS, latency percentiles, MTP, KV-prefix reuse, VRAM, power, and GPU utilization
- Operator analysis: GGML graph nodes, HIP kernel families, shapes, quantization variants, dispatch selection, and fallback reasons

Profiler runs are isolated from normal performance runs so profiling overhead cannot be reported as service performance.

## 12. Multi-agent Collaboration

The collaboration system provides agent search, semantic task creation, worker scheduling, task inspection, retry, cancellation, artifact submission, and main-agent resumption. It applies inference capacity backpressure and package-environment single-flight initialization. The main agent summarizes the delegation after creation and waits for active notifications instead of polling inspection continuously.

The collaboration view presents the main agent, task state, worker activity, recent reasoning summaries, and delivery entry points so parallel execution and semantic acceptance remain observable.

## 13. Runtime Isolation and Extensions

AgentPackage sessions run as supervised native subprocesses. Logical ownership separates package environments, sessions, workspaces, SQLite connections, tool outputs, and artifacts. Dependency environments are resolved by lock identity and reused safely without sharing writable runtime databases. This is an application-level isolation boundary rather than a kernel security sandbox.

Extensions remain declarative through package contracts and installed registries. The platform avoids package-specific branches in the core runtime.

The extension-management view brings MCP servers, Skill extensions, and tool permissions into one surface. The active context supplies the default target while users can select another target explicitly; connection tests and enablement still pass through Gateway resource and permission boundaries.

## 14. Local and Remote Inference

`DEPLOY_TARGET=local` and `DEPLOY_TARGET=ssh` use the same inference control API, model profiles, capacity model, implementation switching, and benchmark protocol. Only endpoint transport differs. This keeps development, evaluation, and deployment behavior aligned.

## Capability Checklist

| Capability | User-facing surface | Runtime owner |
| --- | --- | --- |
| Personal assistant chat | Chat sessions | RuntimeKernel |
| Agent manufacturing/evolution | Factory workspace | Factory control plane |
| Tool calls and approvals | Conversation/tool cards | Tool Gateway |
| Knowledge and RAG | Knowledge workspace | Knowledge runtime |
| Cross-session memory | Package detail and chat | Memory runtime |
| Multi-agent collaboration | Collaboration tab | Collaboration scheduler |
| Scheduled execution | Scheduled-task view | Scheduler runtime |
| Artifacts | Delivery workspace | Artifact system |
| Local model management | Model configuration | Model pool/inference node |
| Performance analysis | Benchmark pages | Benchmark runtime |
