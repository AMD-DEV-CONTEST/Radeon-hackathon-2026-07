# Submission Checklist

Rule sources: AMD AI DevMaster Track 2 screenshot supplied on 2026-08-03 and
the official `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` repository.
Status values: `PASS` / `PENDING` / `BLOCKED` / `N/A`.

## 1. Track 2 Requirements

| Requirement | Evidence | Status |
|---|---|---|
| Runs on AMD Radeon GPU + ROCm | benchmark evidence plus V4 terminal/UI proof | PASS |
| Core inference is local; no remote model API | `privacy_security.md`, security JSON, loopback logs | PASS |
| Scenario-based task execution | Golden Case and UI/E2E | PASS |
| Tool use and workflow orchestration | LangGraph, rules, RAG, Verifier | PASS |
| Local stability and response performance | concurrency and 30-minute reports | PASS |
| At least two minimum capabilities | all five: RAG, tools, planning, local memory, privacy/control | PASS |

## 2. Scoring Coverage

| Scoring area | Points | Submission evidence | Status |
|---|---:|---|---|
| Clear task positioning and creative scenario | 20 | English PDF; value-led PPT; video opening | PASS |
| Complete core capabilities including tools/RAG/memory | 20 | PDF, architecture, README, UI | PASS |
| Smooth multi-turn experience | 20 | UI, Golden Case, V4 video | PASS |
| Core inference on AMD Radeon | 20 | localhost evidence, `amd-smi`, V4 Demo | PASS |
| Targeted inference optimization | 20 | AMD report, charts, concurrency/stability | PASS |

## 3. Required Files

| File/link | Expected location | Status | Note |
|---|---|---|---|
| Project specification | `docs/submission/project_description.pdf` | PASS | 20-page V4-aligned English PDF rendered and inspected page by page |
| Application scenario | English PDF/PPT | PASS | value and target-user narrative complete |
| Agent architecture | `architecture.png` + `architecture.svg` | PASS | English 2400x1350 PNG and editable SVG visually verified |
| Core capabilities | English PDF/PPT/README | PASS | source content complete |
| Models and local deployment | README + `model_license.md` | PASS | English and locally reproducible |
| AMD inference optimization | `amd_optimization.md` | PASS | English; references existing measurements only |
| Complete source repository | final GitHub submission link | PENDING | no early push or PR |
| README environment/start/dependencies | `README.md` | PASS | English; fresh install already validated |
| 3-5 minute Demo video | `docs/submission/demo_video.mp4` | PASS | 4:54 Mac-compatible H.264 candidate included in the submission branch |
| Actual AMD execution | UI + `amd-smi` + localhost in video | PASS | visible in the approved V4 narrative |

## 4. Supplementary Material

| Material | Status | Note |
|---|---|---|
| PPT | PASS | 11-slide English value-led deck; rendered, inspected, notes verified, no overflow |
| Poster | N/A | PPT satisfies the optional supplementary-material choice |

## 5. Engineering and Compliance

| Check | Status | Evidence/action |
|---|---|---|
| Test report | PASS | `test_report.md` in English |
| Privacy and security | PASS | `privacy_security.md` in English |
| Model licenses | PASS | `model_license.md` in English |
| Project source license | PASS | root Apache-2.0 `LICENSE` |
| Mock vs local vLLM clearly separated | PASS | README, launch scripts, presentation |
| No real personal data | PASS | synthetic fixtures + SEC-03 + V4 visual review |
| No public model endpoint | PASS | scan and localhost evidence |
| Human Approval | PASS | `draft` / `pending`; no automatic external action |
| Legal disclaimer | PASS | README/PDF/report |
| Raw benchmark traceability | PASS | JSON/CSV/log evidence and hashes |

## 6. Release and Pull Request

| Check | Status | Note |
|---|---|---|
| Feature-freeze audit | PASS | `release_check/freeze_audit.md` |
| Fresh install | PASS | automatic legal-index build, UI HTTP 200, Golden 0 failures |
| Golden Case | PASS | fresh Mock and Radeon local vLLM both 0 failures |
| Candidate tag | PENDING | create locally only after final candidate commit |
| Final readiness | PASS | reviewed material set is `READY = TRUE`; remote submission still requires owner approval |
| PR title | PREPARED | exact user-approved title: `Track2，DataLink，Accident Rights Agent` |
| PR body and materials | PREPARED | English draft only; no remote action taken |
| Push / GitHub PR / ModelScope submission | BLOCKED BY POLICY | requires explicit user confirmation |

## 7. Final Video Review

```text
[x] 3-5 minutes (4:54)
[x] Mac-compatible H.264 candidate and playable
[x] Shows the real AMD Radeon GPU and ROCm environment
[x] Shows the loopback local-vLLM deployment boundary
[x] Shows materials -> evidence -> liability -> rights -> Verifier -> Human Approval
[x] Shows AMD before/after results and 30-minute stability evidence
[x] Clearly labels synthetic materials and legal boundaries
[x] No exposed SSH credential, private key or personal claim data
[x] No false "automatically submitted", "guaranteed result", or equivalent claim
[x] English voice-over and bilingual subtitles included
```

## 8. Current Decision

`READY = TRUE` for the reviewed material set.
`REMOTE_SUBMISSION_AUTHORIZED = TRUE` (owner confirmation received on 2026-08-05).

The V4 video, V4-aligned English PDF and PPT, architecture, corrected README,
Apache-2.0 license, and English PR draft have passed their current material QA
gates. The owner authorized the candidate commit, fork push, and Pull Request
on 2026-08-05. Final hashes and the Pull Request URL are recorded during the
release execution.
