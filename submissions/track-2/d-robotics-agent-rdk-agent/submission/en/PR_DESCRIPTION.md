# Pull Request Title

```text
Track 2, d-robotics agent, RDK Agent
```

## Track 2 Submission: RDK Agent

- **Track:** Track 2 - Development and Local Deployment of Private AI Agents
- **Team / Participant:** `d-robotics agent`
- **Application:** RDK Agent
- **Demo video (primary):** https://www.bilibili.com/video/BV1t3up6iEhy/
- **Demo video (backup):** https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd
- **Source:** `https://github.com/cowhorseming/rdk-sophon`

## Project summary

RDK Agent is a privately deployed multi-agent platform for developing, validating, deploying, and operating robot capabilities on an RDK X5. The submitted action-package implementation currently targets parameterless `rdk-servo-action/v1` actions for the MagicBox servo runtime.

The board-side subsystem name `rdk-sophon` is a literary allusion to the sophon (智子) in *The Three-Body Problem*: a messenger sent to observe a distant world and sustain communication. Here, `probe-daemon` is deployed to the board to observe hardware state and act as the governed communication bridge between `rdk-agent` and device capabilities. Unlike the fictional observer, it is owner-controlled, auditable, and permission-bounded. This independent project uses no official artwork and is not endorsed by or affiliated with the work's author, publishers, rights holders, or screen adaptations.

A user describes a robot requirement in natural language. In Robot Development Mode, specialized agents transform it into a self-contained action package through test design, minimal implementation, independent executable verification, deterministic release construction, atomic board deployment, Skill installation, and both CLI and natural-language acceptance. In Robot Application Mode, a constrained agent selects a delivered Skill for a read-only query or one explicitly requested robot action.

The project combines two independently deployable subsystems:

- **`rdk-agent`** - TypeScript TUI/headless application for intent routing, multi-agent TDD, scoped tools, Skill selection, deployment, and human-in-the-loop recovery.
- **`rdk-sophon`** - Rust RDK X5 platform containing `probe-daemon`, `sophonctl`, hardware-state collection, JSON-RPC, telemetry, alerts, command policy/audit, multiple transports, and dynamic plugins.

## Track 2 capabilities

- Tool calling through stage-specific scoped tools.
- Multi-step planning and execution through an ordered domain workflow.
- Agent- and tool-layer permission/privacy controls through tool/Skill/write-path allowlists, offline tests, and action/query separation.
- Bounded revision loops with human follow-up.
- Private OpenAI-compatible model routing with a dedicated Radeon Cloud/vLLM deployment path.

Local RAG and persistent cross-run memory are not claimed.

## Architecture

```text
Development host                                     RDK X5

User -> RDK Agent TUI / headless runner
          |-- intent gate
          |-- Action Package TDD
          |-- offline Podman tests
          |-- deterministic build/deploy
          `-- generated Skills
                    |
                 sophonctl ---- TCP 7777 ----> probe-daemon
                                                   |-- hardware telemetry
                                                   `-- servo plugin/action packages

RDK Agent -> private OpenAI-compatible vLLM -> ROCm -> AMD Radeon GPU
```

## AMD Radeon and ROCm

The private runtime selects provider `amd` and `Qwen3-Next-80B-A3B-Instruct` through OpenAI-compatible Chat Completions. The public submission excludes the real endpoint and API key and includes a sanitized configuration.

Application-level inference controls already reduce unnecessary model work: deterministic greeting bypass, a short tool-free intent session, focused per-stage sessions, strict Skill loading, 6,000-character handoff bounds, and deterministic validators outside the model.

The team has run both `Qwen3-Next-80B-A3B-Instruct` and the SFT-trained `Qwen3-32B-Agentic-SFT-r1-v3`. The 80B path has archived single-Radeon `llama.cpp` serving, compatibility, and performance records; the 32B SFT path also has a recorded five-node live `rdk-agent` run. The separate private vLLM endpoint is only attested at the client-routing level, so its server provenance is not used for the published performance claims.

## Verification

Evidence captured on 2026-08-05:

- TypeScript static check passed.
- `rdk-agent`: 134/134 tests passed.
- `rdk-sophon`: 62/62 tests passed.
- Rust Clippy passed with warnings denied.
- Rust release workspace build passed.
- Live RDK X5 `ping` and state queries succeeded.
- Dynamic `servo` plugin discovery succeeded.

`cargo fmt --all -- --check` still reports existing formatting differences and is disclosed in the evidence log.

## Submitted materials

- Project Specification: Markdown and PDF.
- Complete source repository and English root README.
- Detailed reproducibility and deployment guide.
- Primary Bilibili video link plus a Baidu Cloud MP4 backup link.
- Supplementary PowerPoint deck.
- Architecture/workflow/evidence graphics.
- Sanitized AMD model configuration and benchmark script.
- Verification evidence, PR copy, and submission checklist.

## Evidence integrity

The submission does not expose credentials, does not present development-host Mach-O binaries as RDK X5 deliverables, does not treat a successful command as proof of physical motion quality, and does not report estimated AMD performance as measured data.
