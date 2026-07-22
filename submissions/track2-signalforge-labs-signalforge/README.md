# SignalForge - AMD AI DevMaster Hackathon Track 2 Submission

| Field | Value |
| --- | --- |
| Track | Track 2 - Development and Local Deployment of Private AI Agents |
| Team | SignalForge Labs |
| Application | SignalForge |
| Team member | Rafael Bernucci - product architecture, financial domain design, evaluation strategy, and release ownership |
| Frozen source commit | [`72991a40118a6253d6ee5fd13f331bcd2974b2fa`](https://github.com/rvbernucci/signalforge/commit/72991a40118a6253d6ee5fd13f331bcd2974b2fa) |
| Frozen release | [`v1.0.0`](https://github.com/rvbernucci/signalforge/releases/tag/v1.0.0) |
| Canonical source repository | [github.com/rvbernucci/signalforge](https://github.com/rvbernucci/signalforge) |
| CI | [Repository quality run 29922275794](https://github.com/rvbernucci/signalforge/actions/runs/29922275794) |

## Submission Materials

- [Project specification PDF](https://github.com/rvbernucci/signalforge/releases/download/v1.0.0/SignalForge-Project-Specification.pdf)
- [4 minute 12.9 second AMD Radeon demo video](https://github.com/rvbernucci/signalforge/releases/download/v1.0.0/SignalForge-Radeon-Demo.mp4)
- [Six-slide judge deck](https://github.com/rvbernucci/signalforge/releases/download/v1.0.0/SignalForge-Judge-Deck.pptx)
- [Architecture diagram](https://github.com/rvbernucci/signalforge/releases/download/v1.0.0/architecture.svg)
- [Final release checklist](https://github.com/rvbernucci/signalforge/releases/download/v1.0.0/signalforge-release-checklist-final.json)
- [SG-05 freeze attestation](https://github.com/rvbernucci/signalforge/releases/download/v1.0.0/signalforge-sg05-attestation.json)

The complete source snapshot, documentation, deterministic fixtures, tests, evidence, PDF, deck,
and video are also included under `source/` in this submission directory.

## What SignalForge Does

SignalForge is a private, local-first financial research desk. It turns public SEC filings,
investor-relations evidence, macroeconomic series, and market observations into an inspectable
research case rather than an opaque chat answer. The first complete journey compares Microsoft and
NVIDIA as long-term businesses under explicit higher-rate and slower AI-infrastructure-spending
scenarios.

The product separates readable analysis from source evidence, deterministic calculation receipts,
assumptions, limitations, counterevidence, and thesis-invalidation conditions. It is designed for
research and education, not personalized investment advice or trade execution.

## Agent Architecture

1. A typed interpreter identifies the bounded research intent and required capabilities.
2. A Go-owned orchestrator creates a finite plan and invokes six role-specific local specialists.
3. Evidence retrieval uses authority, temporal, rights, citation, and context-budget policies.
4. Deterministic Go engines own financial calculations and emit replayable receipts.
5. Two independent local reviewer roles gate unsupported claims and risk boundaries.
6. One final local analyst synthesizes only authorized evidence, assumptions, and receipts.
7. A React workspace streams safe progress and exposes evidence and proof without revealing private reasoning.

All 11 logical roles share one local Gemma runtime with role-specific prompts and strict structured
contracts. Core inference is loopback-only on AMD Radeon through ROCm and `llama.cpp`; remote model
APIs are not part of the core path.

## Track 2 Capabilities

| Capability | SignalForge evidence |
| --- | --- |
| Local knowledge retrieval | SEC, investor-relations, macro, and market evidence with resolvable citations and bounded context |
| Tool invocation | Typed read-only data tools and deterministic finance engines with authorization gates |
| Multi-step task planning | Finite interpreter, planner, specialist, reviewer, and synthesis state machine |
| Local multi-turn memory | Opt-in local SQLite cases, governed follow-ups, inspect/export/delete controls, and safe projections |
| Permission and privacy | Loopback-only inference, secret rejection, read-only model authority, private traces, and fail-closed release gates |

## AMD Radeon And ROCm Evidence

- Environment: AMD Radeon Cloud, Radeon `gfx1100`, ROCm 7.2.1.
- Runtime: hash-pinned ROCm `llama.cpp` with the official Gemma 4 26B A4B Instruct QAT Q4_0 GGUF.
- Baseline: 40/40 deterministic contract checks and 86.46 median decode tokens/s.
- Accepted optimization: four context workers, unified F16 KV, continuous batching, and flash attention `auto`.
- Workload result: 44/44 frozen semantic checks in 157.47 seconds, 29.17% faster end to end than the accepted three-worker run.
- Final recorded journey: six specialist roles, two reviewer roles, 42 explicit claim dispositions, 31 released claims with authority, complete evidence coverage, six passing chaos cases, and three governed follow-ups.

These are bounded, hash-backed workload results. They are not claims of universal factual accuracy
or universal performance across GPUs and workloads.

## Reproduce

The deterministic fixture is the primary clean-room path and requires no GPU, API key, model
download, database setup, or network call after dependencies are installed. Clone the immutable
tag so the release auditor evaluates the exact standalone Git tree:

```bash
git clone --branch v1.0.0 --depth 1 https://github.com/rvbernucci/signalforge.git
cd signalforge
./scripts/verify.sh
go run ./cmd/signalforge-workspace --mode fixture --addr 127.0.0.1:8080
```

Open `http://127.0.0.1:8080`. The included `source/` tree is byte-identical to that tag and may be
used as an offline source copy. Its README documents the exact pinned Radeon live path,
dependencies, configuration, troubleshooting, model revision, model hash, and runtime revision.

## Freeze And Provenance

The tree under `source/` was exported from `v1.0.0` without modification. The two files beside this
README, `release-checklist-final.json` and `sg05-attestation.json`, record the post-CI owner
authorization and release freeze. Artifact hashes are listed in `SHA256SUMS`.
