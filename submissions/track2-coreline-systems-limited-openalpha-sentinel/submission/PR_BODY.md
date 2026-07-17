# Pull Request Title

```text
Track 2, Coreline Systems Limited, OpenAlpha Sentinel
```

# Pull Request Body

## Submission

| Field | Value |
|---|---|
| Track | Track 2 - Private AI Agent Development and Local Deployment |
| Team | Coreline Systems Limited |
| Application | OpenAlpha Sentinel |
| Team members | Zeng Baocheng (曾宝成), [`csaizbc`](https://github.com/csaizbc), 1154375864@qq.com; Yang Jinhao (杨锦皓), [`yangjinhao06-droid`](https://github.com/yangjinhao06-droid), yangjinhao06@gmail.com |
| Project report | [English project report](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/main/docs/submission/generated/OpenAlpha-Sentinel-Project-Report.en.docx) |
| Demo video | [3:39.9 English-subtitled demo](https://github.com/csaizbc/Radeon-hackathon-2026-07/blob/demo-video/OpenAlpha-Sentinel-Demo.en.1080p.mp4) ([direct MP4](https://raw.githubusercontent.com/csaizbc/Radeon-hackathon-2026-07/demo-video/OpenAlpha-Sentinel-Demo.en.1080p.mp4)) |
| Selected supplemental material | [English submission slides](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/main/docs/submission/generated/OpenAlpha-Sentinel-Slides.en.pptx) |
| Source directory | `submissions/track2-coreline-systems-limited-openalpha-sentinel/` |
| Development repository | https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon |

## What We Built

OpenAlpha Sentinel is a local-first research agent that continuously collects configured public open-source quantitative strategy material, converts it into versioned and evidence-linked strategy cards, stores it in a local retrieval system, and answers questions with citations to the original source.

It is designed for individual quantitative researchers, financial-engineering students, and small research teams. It does not connect to trading accounts, execute third-party repositories, promise returns, or provide personalized investment advice.

## Key Features

- GitHub discovery, RSS/Atom ingestion, and a deterministic local demo corpus
- Normalized strategy cards with source, revision, license, disclosures, risks, and evidence
- Local retrieval and source-aware question answering
- Multi-turn narrowing and comparison of collected strategies
- Jobs and recurring watch rules for continuous monitoring while the service is running
- Local browser workbench with Overview, Strategy Cards, Agent Chat, Sources, Jobs, and Watch Rules
- Replaceable local model provider, with final inference served by `llama.cpp` on AMD Radeon + ROCm

## Track 2 Capabilities

| Capability | Evidence in this submission |
|---|---|
| Local RAG | Local card/evidence retrieval and cited answers |
| Tool use | Explicit GitHub, RSS, retrieval, demo-seed, and watch-rule operations |
| Multi-step planning | Bounded discover, fetch, normalize, deduplicate, extract, index, and report workflow |
| Local multi-turn memory | Contextual follow-up filtering in Agent Chat |
| Permission and privacy | Explicit source configuration; source collection is separated from local inference; indexed workflows remain local |

## AMD Radeon and ROCm

The submitted runtime uses a local ROCm/HIP `llama.cpp` service; the application does not use Codex or a hosted model API as its runtime inference engine. Separate saved transcripts prove a real OpenAlpha CLI request and a loopback HTTP `200` request, both labeled `backend=llama.cpp-rocm` and both returning a commit-pinned source URL with original-file lines `8-28`. These transcripts verify the two application transports, but they do not by themselves prove the actual offloaded-layer count or process-attributed GPU use for an individual request.

| Item | Final submitted result |
|---|---|
| Environment | AMD OneClick Base, Ubuntu 24.04.4, ROCm 7.2.1 |
| GPU | `gfx1100`, approximately 48 GiB reported VRAM; the platform did not expose a reliable commercial model name |
| HIP | `7.2.53211` |
| `llama.cpp` | `ROCm/llama.cpp` commit `1b99711a5f2582ec99686eb7958844749c223cf5` |
| Model | Qwen3-8B, `Qwen3-8B-Q4_K_M.gguf`, Apache-2.0 |
| Model SHA-256 | `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| Runtime code | Application evidence: clean commit `8f9aad7a206287b2158f0fccb7a70c4a7373aa87`; offload validation: clean commit `25129cdd853a4fe5a258386350d933339b381028` |
| ROCm GPU-layer assignment | `generated/rocm-offload-validation-20260717T152430Z.txt` reports `offloaded 37/37 layers to GPU` on `ROCm0`; `-ngl 99` is the configuration upper bound |
| Decode throughput | `93.47 +/- 0.08 tokens/s` (`tg256`, five repetitions) |
| TTFT P50 / P95 | Not measured in the current evidence set |
| Peak VRAM | Not measured; one capture-time GPU-wide snapshot reports 63% GPU use and `6,642,937,856` bytes used, but it is neither a peak nor process/model-resident VRAM |
| Cold-cache pipeline throughput | Not measured in a comparable CPU/Radeon optimization study |
| Quality change | Not measured in the current evidence set |

Raw benchmark output and methodology: [benchmark report](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/main/docs/submission/BENCHMARK_REPORT.en.md)

## Reproduce

The project README contains the complete installation, configuration, local startup, demo seed, test, Radeon setup, and benchmark steps.

```bash
# Follow the exact commands in the submitted project README.
# No hosted AI API is required for the final Radeon workflow.
```

## Validation

- Local MVP workflow: complete
- Deterministic local/demo workflow: `PASS - three fixtures produced three source-linked cards`
- Test suite: `PASS - 56 tests and 81% statement coverage on local Python 3.11.15`; the saved earlier Radeon-host run passed all 35 tests on Python 3.12.3
- Radeon CLI and HTTP application paths: `PASS - separate transcripts show a real CLI request and loopback HTTP 200 response, both with backend=llama.cpp-rocm and a commit-pinned line citation`
- ROCm `llama-bench` and offload: `PASS - ROCm, ngl=99 configuration, independently measured 37/37 layers on ROCm0`
- Structured extraction through the local Radeon endpoint: not separately validated
- Saved cited application responses: `PASS - CLI and HTTP transcripts cite commit-pinned lines 8-28`
- Restart/resume: `PASS for one controlled trace - all three PIDs changed, both health checks passed, repeat seed created 0 cards and skipped 3 revisions, protected counts and notifications were unchanged, SQLite integrity was ok, and foreign-key violations were 0`
- Optional 24-hour soak test: not run (optional)
- Clean-environment reproduction: not separately validated on a second blank Radeon instance

## Submission Materials

- English project report: [English report DOCX](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/main/docs/submission/generated/OpenAlpha-Sentinel-Project-Report.en.docx)
- Chinese project report (supplementary): [Chinese report DOCX](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/main/docs/submission/generated/OpenAlpha-Sentinel-Project-Report.zh-CN.docx)
- Demo video (3:39.9): [public video page](https://github.com/csaizbc/Radeon-hackathon-2026-07/blob/demo-video/OpenAlpha-Sentinel-Demo.en.1080p.mp4) and [direct MP4](https://raw.githubusercontent.com/csaizbc/Radeon-hackathon-2026-07/demo-video/OpenAlpha-Sentinel-Demo.en.1080p.mp4)
- Selected supplemental material: [English submission slides](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/main/docs/submission/generated/OpenAlpha-Sentinel-Slides.en.pptx)
- Benchmark report and raw artifacts: [report](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/main/docs/submission/BENCHMARK_REPORT.en.md) and [`generated/`](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/tree/main/docs/submission/generated)
- Labeled final quality evaluation: not run in the current evidence set
- Optional 24-hour stability report: not run (optional)
- Third-party licenses and attributions: [third-party notices](https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/main/docs/submission/THIRD_PARTY_NOTICES.en.md)

## Team Contributions

| Member | Contribution |
|---|---|
| Zeng Baocheng (曾宝成) / [`csaizbc`](https://github.com/csaizbc) / 1154375864@qq.com | Project lead; application design and implementation; disposable Radeon deployment; benchmarking and evidence; submission engineering |
| Yang Jinhao (杨锦皓) / [`yangjinhao06-droid`](https://github.com/yangjinhao06-droid) / yangjinhao06@gmail.com | ROCm validation research; test-evidence documentation; review |

## Responsible-use Boundary

OpenAlpha Sentinel is for research and education only. Research-readiness scores describe traceability and disclosure quality, not investment merit. Source-author metrics are labeled as claims, unsupported fields remain unknown, and the project does not provide trading execution or personalized buy/sell recommendations.

---

### Evidence-status note

The clean application and offload-validation commits, model hash, ROCm `llama-bench` snapshot, independent `37/37` layer trace, Radeon-host 35-test run, cited CLI and loopback HTTP `200` transcripts, one controlled three-process restart/persistence trace, and the public 3:39.9 demo video are saved. Structured LLM extraction, comparable CPU/Radeon optimization, TTFT percentiles, labeled quality results, and active peak VRAM tracing were not measured in the current evidence set. The optional 24-hour soak was not run. None of those remaining items is claimed as complete.
