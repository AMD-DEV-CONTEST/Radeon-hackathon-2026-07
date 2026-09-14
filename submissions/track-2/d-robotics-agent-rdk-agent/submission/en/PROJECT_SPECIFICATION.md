# RDK Agent - Track 2 Project Specification

**Tagline:** From natural-language requirements to governed robot capabilities on RDK X5.

**Submission track:** Development and Local Deployment of Private AI Agents

**Application:** RDK Agent

**Source repository:** `https://github.com/cowhorseming/rdk-sophon`
**Demo video:** [Bilibili primary](https://www.bilibili.com/video/BV1t3up6iEhy/) · [Baidu Cloud MP4 backup](https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd) · [video notes](VIDEO.md)

![RDK Agent concept cover](assets/rdk-agent-hero.png)

> The cover is a conceptual illustration and is not presented as a photograph of the submitted hardware.

## 1. Executive summary

RDK Agent is a privately deployed multi-agent platform for developing and operating robot capabilities on an RDK X5. State and device control remain local; model inference can use a participant-controlled private endpoint. A developer describes a robot behavior in natural language. Specialized agents transform that request into an independently packaged capability through test design, implementation, executable verification, release construction, board deployment, Skill installation, and controlled hardware acceptance. The submitted action-package path currently targets parameterless `rdk-servo-action/v1` actions for the MagicBox servo runtime.

The system addresses a concrete robotics problem: even a small behavior crosses natural-language intent, Python hardware logic, tests, command-line integration, remote deployment, Skill metadata, and physical verification. Manual handoffs are difficult to reproduce. A general-purpose coding agent also needs stronger controls before it can interact with real hardware.

RDK Agent separates model-driven reasoning from deterministic delivery and device execution. Agents work within tool, Skill, filesystem, timeout, and sandbox boundaries. Deterministic scripts control scaffolding, validation, release structure, hashes, and atomic deployment. The RDK X5 exposes a stable control and telemetry contract through `sophonctl` and `probe-daemon`.

## 2. Why “Sophon”? - The naming story

The board-side subsystem `rdk-sophon` takes its name from the sophon (智子) in *The Three-Body Problem*. In the novel, an extraordinarily advanced messenger is sent across space to Earth, where it can observe human activity and sustain communication with its origin.

The `rdk-sophon` board-side subsystem deliberately reinterprets that science-fiction idea as transparent, owner-controlled engineering:

| Literary metaphor | `rdk-sophon` implementation |
| --- | --- |
| A messenger is sent to a distant world | `probe-daemon` is deployed to the RDK X5 board. |
| It observes local conditions | Collectors read temperature, CPU, memory, disk, network, and BPU state. |
| It reports across a long communication link | Telemetry and JSON-RPC carry board state to development-host clients. |
| It mediates communication with the distant system | `sophonctl` connects `rdk-agent` to board-side plugins and capabilities. |
| It can influence events remotely | Governed commands can invoke an approved robot capability. |

The ethical and operational direction is intentionally different from covert fictional surveillance: `rdk-sophon` is installed by the device owner, exposes explicit interfaces, keeps an audit trail, applies command policy, and restricts agent permissions.

![Original science-fiction interpretation of the Sophon naming metaphor](assets/sophon-three-body-concept.png)

> This is a project-created AI-generated conceptual illustration. No official artwork or assets from the novel or adaptations are used. The name is a literary allusion used only to explain an internal code name; this independent project is not endorsed by or affiliated with the work's author, publishers, rights holders, or screen adaptations.

## 3. Target users and application scenarios

### 3.1 Robot application developers

A developer can request a new self-contained robot action without manually coordinating test files, control code, plugin registration, Skill documentation, deployment, and acceptance.

Example:

```text
Create a new action that moves its left side once.
```

The system preserves the original request throughout the workflow. If generated metadata, paths, or hardware calls reverse the requested side, a deterministic guard rejects the change before it is written.

### 3.2 Robotics educators and prototype teams

The visible Test -> Code -> Verify loop makes agentic robot development inspectable. Offline tests use fakes and mocks; the model does not need direct GPIO access to develop a capability.

### 3.3 RDK X5 operators

The same platform provides read-only inspection for temperature, CPU, memory, disk, network, BPU, and dynamic plugins. It distinguishes a successful command path from human confirmation of physical motion.

### 3.4 Reusable private robot capabilities

Validated capabilities become local Skills. Robot Application Mode can select an installed Skill from natural language and execute one mapped action without reopening the development workflow.

## 4. System architecture

![End-to-end architecture](assets/architecture.png)

The repository contains two independently releasable systems:

| Component | Responsibility |
| --- | --- |
| `rdk-agent` | TypeScript TUI/headless application, intent routing, multi-agent orchestration, scoped tools, Skill selection, deterministic delivery adapters, and human-in-the-loop handling. |
| `sophonctl` | Stable development-host command contract for board state, plugins, and actions. |
| `probe-daemon` | Rust service on RDK X5 for RPC dispatch, state collection, telemetry, alerting, command policy, audit, and dynamic plugins. |
| Servo plugin and action packages | Board-side Python capability runtime with local metadata and independently removable action packages. |
| Private model server | OpenAI-compatible inference endpoint on an owned AMD Radeon Cloud instance with ROCm; selected through Pi configuration rather than application code. |

`rdk-agent` does not link to the Rust crates. It invokes `sophonctl`, which communicates with `probe-daemon` over TCP port 7777. The model runtime and the device runtime are also separated: model inference proposes bounded work; deterministic tools and the board contract govern what is written or executed.

## 5. Agent architecture and workflow

![Five-node development workflow](assets/workflow.png)

### 5.1 Intent gate

Exact greetings and acknowledgements are answered deterministically. Other development input is classified in a short model session with no tools, no Skills, no project context, and no filesystem writes. Only a high-confidence request inside the supported action-package scope starts development. `/develop` is an explicit human override.

### 5.2 Action Package TDD

The current workflow uses one bounded TDD loop:

1. **Action Test Design Agent** creates or revises behavior tests and action metadata.
2. **Action Coding Agent** implements only the action entry point.
3. **Action Verification Agent** independently runs contract and behavior checks without write access.

Failed verification restarts the full Test -> Code -> Verify loop. After three unsuccessful iterations, the workflow pauses for human guidance instead of silently continuing.

### 5.3 Deterministic delivery

After verification:

1. **Board Release Deployment Agent** calls deterministic build tooling and atomically publishes the release.
2. **Skill Installation Agent** installs the generated runtime Skill on the development host.
3. **CLI Hardware Acceptance Agent** executes the new capability once through `sophonctl`.
4. **Natural-Language Skill Acceptance Agent** selects the installed Skill using the original request and executes the same capability once.

### 5.4 Robot Application Mode

Application Mode has a separate single-agent path. Capability questions remain read-only. An imperative request authorizes one mapped action. The tool layer enforces this distinction even if model text is incorrect.

## 6. Core capabilities

### 6.1 Tool calling

Agents receive only the tools required by their stage. Custom tools expose bounded operations such as scaffold, validate, build, and deploy rather than unrestricted scripts.

### 6.2 Multi-step planning and task execution

The domain workflow enforces ordered handoffs from intent routing through TDD, release, deployment, Skill installation, and two acceptance paths. A downstream stage cannot start before its predecessor succeeds.

### 6.3 Agent- and tool-layer permission/privacy controls

Every agent has a tool allowlist, Skill allowlist, write-path allowlist, timeout, and sandbox policy. Development tests run in a network-disabled Podman container with a read-only workspace and resource limits. Credentials and host home directories are not mounted into the test environment.

### 6.4 Human-in-the-loop recovery

Ambiguity, model/tool errors, invalid structured results, and exhausted revision budgets pause the workflow and request human input. `/abort` stops a blocked run.

### 6.5 Local device telemetry and dynamic execution

`probe-daemon` provides one state snapshot for on-demand queries and telemetry. Dynamic plugin commands use exact argument vectors instead of `sh -c`. Robot action packages are discovered from local registries and can be removed without rebuilding the Rust CLI.

### 6.6 Track capability matrix

The Track 2 rules list five agent capabilities and require at least two. This project deliberately claims only capabilities implemented in the repository:

| Track capability | Status | Evidence boundary |
| --- | --- | --- |
| Local RAG | Not implemented | Not claimed. |
| Tool calling | Implemented | Scoped read/bash/write/edit plus deterministic action-package and deployment tools. |
| Multi-step planning | Implemented | Ordered domain workflow with bounded TDD revision. |
| Local multi-turn memory | Partial | In-memory sessions and human follow-up exist; persistent cross-run memory is not implemented and is not counted. |
| Permission/privacy mechanism | Implemented at the agent/tool layer | Allowlists, offline sandbox, read-only mounts, evidence gates, and explicit action/query separation. Transport authentication and normal-path per-action approval remain roadmap items. |

## 7. Safety and reliability design

### 7.1 Safety below the prompt layer

Prompt instructions are not the only control. File tools validate paths, Bash rejects file mutation and unsafe command forms, action-package tooling validates structure and semantics, and hardware actions are unavailable to development agents.

### 7.2 Direction-consistency guard

When the original request explicitly identifies left, right, or both sides, action ID, metadata, intent examples, directory, and Python bridge calls must agree. Conflicts fail with stable code `ACTION-DIRECTION-001` before mutation.

### 7.3 Executable evidence gate

A textual `passed` result is insufficient. The runner records whether the Verification Agent actually executed Bash and whether the final check succeeded. Missing or failed evidence changes the result to revision.

### 7.4 Deterministic contract validation

The action-package format rejects imports, dynamic execution, private controller access, runtime parameters, asynchronous entry points, and coupling to test-spy fields. Release structure and metadata are generated by scripts rather than free-form model output.

### 7.5 Atomic deployment

Deployment uploads to staging, validates files and hashes, takes a backup, replaces the target, and restores the backup when a post-swap step fails.

### 7.6 Honest physical acceptance

Automated checks prove the command path and software contract. They do not claim that a physical motion looked correct. Final motion remains a human-observed acceptance boundary.

## 8. Model and private local deployment

The Pi SDK is the only layer that resolves a model provider. Domain and application code are model-independent. Each stage creates an isolated in-memory session and reports the selected provider/model at runtime.

The competition deployment targets a participant-controlled dedicated vLLM service on AMD Radeon Cloud:

```text
RDK Agent -> OpenAI-compatible private endpoint -> vLLM -> ROCm -> AMD Radeon GPU
     |
     `-> sophonctl -> RDK X5 -> probe-daemon -> servo capability
```

The current private runtime configuration selects:

- Provider ID: `amd`
- Model: `Qwen3-Next-80B-A3B-Instruct`
- Protocol: OpenAI-compatible Chat Completions
- Client context window declaration: 131,072 tokens

The repository intentionally excludes the real endpoint and API key. A sanitized configuration is provided in [`config/pi-models.amd-rocm.example.json`](config/pi-models.amd-rocm.example.json).

The team has actually run both `Qwen3-Next-80B-A3B-Instruct` and the SFT-trained `Qwen3-32B-Agentic-SFT-r1-v3`. The 80B path has archived single-Radeon `llama.cpp` serving and compatibility records; the 32B SFT path also completed a recorded five-node live `rdk-agent` workflow. The client configuration alone does not attest the separate private vLLM server's GPU, ROCm, launch command, revision, or precision, so that server provenance is not used for the published performance claims.

## 9. AMD Radeon and ROCm optimization

### 9.1 Implemented inference-work reduction

The project already reduces model work at the application layer:

- Exact greeting/acknowledgement traffic bypasses inference.
- Intent classification uses a short, tool-free, Skill-free, context-free session.
- Each agent has one focused role rather than a single expanding conversation.
- Only allowlisted Skills are loaded; the selected Skill must be read explicitly.
- Cross-stage text handoffs are bounded to the last 6,000 characters while files remain the source of truth.
- Deterministic scripts handle scaffolding, validation, packaging, hashes, and deployment without extra model calls.
- Independent in-memory sessions prevent unrelated history from accumulating across stages.

These controls reduce tokens and variability regardless of accelerator. The archived 32B SFT run additionally measures the live five-node workflow at 4 min 04 s.

### 9.2 Measured Radeon runtime paths

Two participant-controlled `gfx1100` paths were measured separately:

1. **32B SFT:** NF4 4-bit base plus LoRA adapter, ROCm 7.2.1, 88 trials per arm, and a live RDK X5 Agent run.
2. **80B:** Q4_K_M GGUF on one 51.5 GB Radeon card with `llama.cpp`, one warm-up plus five measured runs per arm, and three API compatibility canaries.

The paths keep their runtimes, protocols, and metrics separate. See the [model track index](MODEL_TRACK.md) and the root README Section 9.5 for exact revisions, hashes, measurements, and reproduction boundaries.

### 9.3 Benchmark artifact

The repository retains the measured results and verification scripts for both Radeon paths. The OpenAI-compatible endpoint benchmark script remains available for future private vLLM measurements and never writes the API key to its report.

| Metric | 32B SFT path | 80B serving path |
| --- | --- | --- |
| Time to first token | p50 17.41 s -> **8.26 s**; p95 83.97 s -> **12.89 s** | archived medians 2,021.26 ms -> **1,808.76 ms** |
| Decode throughput | 6.54 -> **6.72 tok/s** | 37.19 -> **49.82 tok/s** |
| End-to-end Agent run | **5/5 nodes in 4 min 04 s** | no separately archived five-node trace |
| Peak GPU memory | 27.99 -> 28.06 GB | 48.84 -> 49.52 GB |
| Evidence scope | 88 trials/arm plus live-Agent screenshot | 5 measured runs/arm plus API canaries |

## 10. Reproducibility and deployment

The evaluator path is documented in [REPRODUCIBILITY.md](REPRODUCIBILITY.md). The integrated deployment entry point is:

```sh
export RDK_BOARD_IP=192.0.2.10 # Documentation-only example; replace with the board IP.
./rdk-agent/deploy/install-rdk-agent-stack.sh \
  --ssh-host x5-root \
  --board-address "$RDK_BOARD_IP:7777"
```

Read-only checks:

```sh
sophonctl --board x5 ping
sophonctl --board x5 state
sophonctl --board x5 plugins list
```

Development-host verification:

```sh
cd rdk-agent
npm ci
npm run check
npm test

cd ../rdk-sophon
cargo test --workspace
cargo clippy --workspace -- -D warnings
cargo build --release --workspace
```

## 11. Verification evidence

Evidence captured on 2026-08-05:

| Area | Result |
| --- | --- |
| TypeScript static check | Passed |
| `rdk-agent` automated tests | 134 passed, 0 failed |
| `rdk-sophon` automated tests | 62 passed, 0 failed |
| Rust Clippy with warnings denied | Passed |
| Rust release workspace build | Passed |
| Live RDK X5 ping | `pong: true` |
| Live RDK X5 thermal state | DDR 55.113 C; CPU 54.38 C at capture time |
| Dynamic plugin discovery | `servo` plugin found |

![Repository verification snapshot](assets/test-evidence.png)

![Sanitized live RDK X5 evidence](assets/board-evidence.png)

The Rust formatting check is not presented as passing: `cargo fmt --all -- --check` reported existing formatting differences. This is listed as a pre-submission follow-up rather than hidden.

## 12. Current limitations and roadmap

- Persistent local multi-turn memory and local RAG are not implemented.
- Normal-path human approval before every real action is not implemented; imperative application requests authorize one action.
- TCP transport currently lacks client authentication, mTLS, and rate limiting.
- Workflow and human-input state are not persisted across process restarts.
- The model runtime configuration is global rather than selected per agent profile.
- The separate private vLLM endpoint's server provenance is not archived; measured 32B SFT and 80B `llama.cpp` Radeon results are archived independently.
- Physical motion quality requires human observation.

These boundaries are roadmap items, not completed features.

## 13. Track 2 rubric map

The governing rules score 100 base points plus 20 optional points. The submission maps evidence as follows:

| Rubric item | Submission evidence |
| --- | --- |
| Scenario and positioning | Sections 1-3; natural-language robot capability development, the Sophon naming metaphor, and device operation. |
| Agent core capability | Sections 5-7; tool calling, multi-step planning, permissions/privacy, TDD delivery. |
| Smooth multi-turn interaction | Intent routing, bounded revision, human follow-up, and two operating modes; persistent memory is not claimed. |
| Core inference on Radeon | Actual 32B SFT and 80B Qwen3 runs on participant-controlled `gfx1100` hosts, with separate evidence scopes. |
| Radeon inference optimization | Measured baseline-versus-optimized results for both paths, plus the 32B SFT live five-node Agent run. |
| Optional Radeon Cloud Model API optimization | 80B single-card serving, API compatibility canaries, model/hash identity, and reproducible aggregate verification. |

## 14. Deliverables

- Complete TypeScript and Rust source trees with lockfiles.
- English repository README and detailed reproduction instructions.
- Project Specification in Markdown and PDF.
- PowerPoint pitch deck.
- Architecture, workflow, board-evidence, and test-evidence images.
- A sanitized AMD model-provider example and benchmark script.
- Demo video placeholder and shot list for the already recorded video.
- PR description and final submission checklist.
