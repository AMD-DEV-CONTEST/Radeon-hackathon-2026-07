# Submission Materials Guide

Judge-facing materials for **PrivatePlate** (AMD AI DevMaster 2026 · Track 2).

## Materials

| Material | Location |
| --- | --- |
| Project root README (environment, architecture, startup) | [`../../README.md`](../../README.md) |
| Project Specification | [`PROJECT_SPECIFICATION.md`](./PROJECT_SPECIFICATION.md) |
| AMD Radeon / ROCm adaptation and optimization | [`AMD_RADEON_ROCM_ADAPTATION_AND_OPTIMIZATION.md`](./AMD_RADEON_ROCM_ADAPTATION_AND_OPTIMIZATION.md) |
| Supplementary PPT | [`PrivatePlate_Track2_Submission.pptx`](./PrivatePlate_Track2_Submission.pptx) |
| Demo video | [YouTube, unlisted](https://youtu.be/2XIZmQV2vQk) (also linked from the project root README) |

## Benchmark evidence

Committed under the project root `benchmarks/` directory (paths relative to `submissions/track2-privateplate/`):

| Evidence | Directory |
| --- | --- |
| Sealed 21-case diagnostic re-run | [`../../benchmarks/c0/stage-b/sealed-suite-diag-16k-20260804T161006Z-brfix/`](../../benchmarks/c0/stage-b/sealed-suite-diag-16k-20260804T161006Z-brfix/) |
| Prefix-caching A/B | [`../../benchmarks/prefix-caching-ab-retry-20260803T071404Z/results/`](../../benchmarks/prefix-caching-ab-retry-20260803T071404Z/results/) |
| Trusted terminal presenter A/B | [`../../benchmarks/terminal-finalization-ab-20260803T094112Z-05/results/`](../../benchmarks/terminal-finalization-ab-20260803T094112Z-05/results/) |

Per-case SQLite databases are omitted by gitignore. Numerical results are project-recorded measurements within the documented experimental scope, not an official Track 2 leaderboard score.

## How to reproduce

From a clone of this contest repository:

```bash
cd submissions/track2-privateplate
npm install
```

Then follow the environment variables and `npm run dev:server` / `npm run dev:web` steps in the [project root README](../../README.md). Offline checks: `npm run typecheck` and `npm run test:eval-v2`. A full Radeon-backed run also requires the pinned local vLLM chat and embedding servers described in the Radeon adaptation document.
