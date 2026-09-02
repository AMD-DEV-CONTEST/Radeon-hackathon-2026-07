# AMD AI DevMaster Hackathon Track 2 Compliance

Review date: 27 July 2026  
Submission: SignalForge by SignalForge Labs  
Official pull request: [AMD-DEV-CONTEST/Radeon-hackathon-2026-07#16](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/16)

This document maps the published Track 2 rules to SignalForge evidence. It is a navigation aid, not
a scoring claim or a substitute for AMD's eligibility and judging decisions.

## Official Source Set

| Authority | Source | Use |
|---|---|---|
| Track rules and submission format | [Official hackathon README](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md) | Track 2 task, platform, capabilities, 120-point criteria, deliverables, PR format, and English-language requirement |
| Radeon Cloud operation | [Official Radeon Cloud User Guide](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/Radeon-Cloud-User%20Guide/README.md) | Workspace, storage, SSH, shared APIs, dedicated vLLM APIs, and deployment behavior |
| Registration and legal terms | [AMD AI DevMaster Hackathon event page](https://luma.com/amd-4dhi) and its linked rules | Registration, eligibility, conduct, rights, prizes, privacy, and legal terms |
| Organizer clarification | AMD official Discord Track 2 answers, recorded in the private operating brief | Final score is 120; both public AMD GPU Cloud endpoints and dedicated vLLM APIs are acceptable for the 20-point API path |

When sources differ, the event's linked legal terms govern eligibility and legal conditions, while
the current official repository README governs the technical submission format.

## Submission Format

| Official requirement | SignalForge disposition | Evidence |
|---|---|---|
| Fork the official repository and open a pull request | Complete | [Official PR #16](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/16) |
| PR title: `Track x, Team name, your application name` | Complete | `Track 2, SignalForge Labs, SignalForge` |
| Submission and project materials in English | Complete | README, source, PDF, deck, video, and public evidence are in English |
| Complete source repository | Complete | [Canonical source](https://github.com/rvbernucci/signalforge) and immutable forward `v1.1.1` tag |
| README with environment configuration, startup guide, and dependencies | Complete | [README](../README.md), especially Quick Start, Development, and Radeon reproduction |
| Project specification | Complete | [Six-page PDF](https://github.com/rvbernucci/signalforge/releases/download/sprint36-championship-v1/SignalForge-Project-Specification.pdf) |
| Architecture diagram | Complete | [Architecture](architecture.svg) |
| Demo video, recommended 3-5 minutes | Complete | [284.970-second Radeon demo](https://github.com/rvbernucci/signalforge/releases/download/sprint36-championship-v1/SignalForge-Radeon-Demo.mp4) |
| Actual operation from UI or CLI to final result on Radeon | Complete | Demo shows a real accepted hybrid Radeon journey, governed workflow, evidence, deterministic receipts, review, observability, and safe failure behavior |
| PPT or poster | Complete | [Six-slide deck](https://github.com/rvbernucci/signalforge/releases/download/sprint36-championship-v1/SignalForge-Judge-Deck.pptx) |

## Track 2 Technical Requirements

| Requirement | SignalForge implementation | Primary proof |
|---|---|---|
| Run on AMD Radeon Cloud and ROCm | Local Gemma inference on Radeon `gfx1100` and ROCm 7.2.1 | [Runtime record](../evidence/sprint34-radeon-runtime.json) |
| Core inference local on AMD Radeon | Local interpreter, specialists, critics, and final synthesis through loopback ROCm `llama.cpp` | Demo and [safe replay](../evidence/golden-safe-decision-replay.json) |
| No complete dependence on a closed-source agent platform | Typed Go orchestration and authority plane; React workspace; local open model runtime | [Architecture](architecture.svg) |
| Tool invocation and workflow orchestration | Closed role-authorized tool registry, deterministic receipts, bounded state machine | Project specification pages 3-4 |
| Operational stability and response performance | Typed failure behavior, bounded retries, startup checks, adversarial matrix, telemetry, and soak evidence | [Hardening matrix](../evidence/hardening-matrix.json) and runtime record |
| Local knowledge retrieval | Point-in-time regulatory and official investor-relations evidence with citations | Project specification page 4 |
| Multi-step task planning | Typed interpreter, orchestrator, specialist waves, critics, and answer compiler | Demo `0:26-3:05` |
| Local multi-turn memory | Governed follow-ups and opt-in local case retention | Demo `3:05-3:47` |
| Permission and privacy controls | Read-only model authority, explicit writes, inspect/export/delete, private traces, secret rejection | Demo `3:40-3:47` and project specification pages 5-6 |

SignalForge implements all five listed capability families; the rule requires at least two.

## 120-Point Evidence Matrix

| Criterion | Points | Status | Evidence |
|---|---:|---|---|
| Clear task positioning and creative application scenario | 20 | Demonstrated | Investor research decision workspace; demo opening; specification pages 1-2 |
| Task decomposition, tools, RAG, and memory | 20 | Demonstrated | All five capability families; demo live journey; architecture and deterministic receipts |
| Smooth multi-turn interaction | 20 | Demonstrated | Governed follow-up, opt-in memory, inspect/export/delete, progressive execution plan |
| Core inference on AMD Radeon | 20 | Measured | Local Gemma route on `gfx1100`/ROCm 7.2.1 with [current local evidence](../evidence/sprint36-radeon-local-journey.json) |
| Targeted inference-speed optimization | 20 | Measured | Four-worker profile passed 44/44 frozen checks in 157.47 seconds, 29.17% faster than the passing three-worker control; a separate eight-journey-per-mode tournament measured `2.7777x` aggregate local speedup versus the two-worker baseline |
| Optional Radeon Cloud Model API path | 20 | Demonstrated | Complete accepted hybrid journey with `radeon-vllm`, local review/synthesis, and local fallback; [current evidence](../evidence/sprint36-radeon-hybrid-journey.json) and [resilience record](../evidence/sprint36-radeon-resilience.json) |

These statuses mean that the required evidence exists and is reviewable. They do not pre-award
points or replace the judges' qualitative assessment.

## Radeon API Boundary

The hybrid path sends only bounded qualitative context-specialist packets to the
organizer-provided OpenAI-compatible Radeon API. Go retains the plan, tools, evidence authority,
numerical authority, contracts, and final envelope. Independent review and final synthesis remain
on the local Radeon model, and a rejected remote packet is replayed locally.

Evidence:

- [Hybrid architecture and configuration](hybrid-vllm-specialists.md)
- [Current accepted hybrid journey](../evidence/sprint36-radeon-hybrid-journey.json)
- [Current accepted demo journey](../evidence/sprint36-radeon-demo-journey.json)
- [Recomputable public latency tournament](../evidence/sprint33-latency-tournament.json)
- [Correlated Workspace capture](assets/sprint36-live-hybrid-success.png)
- [Correlated Mission Control capture](assets/sprint36-live-hybrid-mission-control.png)
- [Current API-loss and model-loss record](../evidence/sprint36-radeon-resilience.json)

## Artifact Integrity

The forward championship release is `v1.1.1` and the public image tag is
`ghcr.io/rvbernucci/signalforge:v1.1.1`. Its immutable source and digest are published after the
forward build and anonymous readback. Historical `v1.1.0` remains byte-identical and available.

The image is public `linux/amd64`, runs as `10001:10001`, contains no credentials or model weights,
and includes a verified `/app/licenses` bundle. SBOM, provenance, Trivy HIGH/CRITICAL, anonymous
pull, and clean fixture execution are release-blocking gates.

## Rights, Conduct, and Responsible Scope

- Original SignalForge code and documentation are Apache-2.0 licensed.
- Third-party software, fonts, models, services, and data remain under their own terms.
- Model weights, restricted source bodies, private corpora, credentials, and raw private inference
  material are excluded from the application image and public artifacts.
- Reference-only sources are cited or linked rather than redistributed when redistribution rights
  are not established.
- The public content does not contain prohibited, discriminatory, defamatory, illegal, or
  inappropriate material.
- SignalForge is research software, not an audit, legal opinion, fiduciary service, personalized
  investment recommendation, trading system, or guarantee.

Participant eligibility remains subject to AMD verification, including Luma approval, AMD
Developer Program registration, legal identity, age, location, Discord and GitHub accounts, and
the event's complete terms.

## Known Limitations

- The deepest recorded and human-reviewed journey is bounded to Microsoft and NVIDIA.
- The broader Technology 20 universe is governed by explicit activation and abstention states.
- External answer accuracy has not been scored against independent human ground truth.
- The video is assembled from current, privacy-safe captures of a real accepted hybrid Radeon
  journey; it does not expose prompts, responses, source bodies, credentials, or private reasoning.
- Current Sprint 36 evidence is bound to the forward source candidate and separately identifies the
  rehearsed OCI image. The final digest is not inferred from an earlier native run.
