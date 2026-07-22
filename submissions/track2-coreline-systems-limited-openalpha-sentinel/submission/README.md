# OpenAlpha Sentinel Official Submission Package

This directory is the English-only entry point for the official AMD AI DevMaster Hackathon submission.

## Submission Identity

| Field | Value |
|---|---|
| Team | Coreline Systems Limited |
| Track | Track 2 - Development & Local Deployment of Private AI Agents |
| Application | OpenAlpha Sentinel |
| Source repository | https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon |
| Team details | [TEAM.md](TEAM.md) |
| Demo video | [VIDEO.md](VIDEO.md) - recorded, validated, and publicly available |

## Official Deliverables

| Requirement | Package location | Status |
|---|---|---|
| Project specification | `artifacts/PROJECT_SPECIFICATION.md` and `.docx` | Ready; video link remains pending |
| Complete source code and reproducibility README | Repository root, `src/`, `scripts/`, `deploy/`, `tests/` | Ready |
| Demo video | `VIDEO.md` | Recorded, locally validated, and publicly available |
| Supplementary material | `artifacts/OpenAlpha-Sentinel-Slides.en.pptx` | Selected and generated |
| Architecture | `artifacts/ARCHITECTURE.md` | Ready |
| Benchmark report | `artifacts/BENCHMARK_REPORT.md` | Ready with unmeasured results labeled honestly |
| Third-party notices | `artifacts/THIRD_PARTY_NOTICES.md` | Ready |
| Pull Request text | `PR_BODY.md` | Ready except video URL and final official-fork URL |
| Radeon evidence | `evidence/` | Curated final evidence set |

The official repository requires submission materials, project descriptions, and the Pull Request to be in English. Chinese counterparts remain under `docs/submission/` for internal review and are not part of this official package.

## Build And Verify

Regenerate this package after changing canonical submission sources:

```bash
./scripts/build_official_submission_package.sh
cd submission
shasum -a 256 -c SHA256SUMS
```

## Official Pull Request Target

Copy this repository once into the forked official repository under:

```text
submissions/track2-coreline-systems-limited-openalpha-sentinel/
```

Use this Pull Request title:

```text
Track 2, Coreline Systems Limited, OpenAlpha Sentinel
```

The remaining external gates are team registration confirmation and the final official-fork/PR links. Optional or unmeasured engineering results must remain labeled as such.
