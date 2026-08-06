# E9 Submission Materials Hub

This directory is the shared entry point for the AMD AI DevMaster Hackathon
Track 2 submission package. It contains editable sources, evidence boundaries,
recording guidance and reviewable binary artifacts.

> **Current material status:** `SUBMISSION PACKAGE READY / DEMO LINK ADDED`
>
> **Last refreshed:** 2026-08-06
>
> **Material snapshot ID:** `EA-SUBMISSION-E9-20260806-R8`

## Read this first

1. [`FINAL_SUBMISSION_INDEX.md`](FINAL_SUBMISSION_INDEX.md) maps every file to
   the official Track 2 requirements and is the submission handoff.
2. [`source/SUBMISSION_FACTS.md`](source/SUBMISSION_FACTS.md) is the compact
   claim source for this package.
3. [`source/PROJECT_SPECIFICATION_EN.md`](source/PROJECT_SPECIFICATION_EN.md)
   is the editable English specification behind the final-content PDF.
4. [`source/DEMO_SCRIPT.md`](source/DEMO_SCRIPT.md) is the recording-ready
   approximately four-minute demo runbook.
5. [`source/OFFICIAL_PR_DRAFT.md`](source/OFFICIAL_PR_DRAFT.md) contains the
   organizer-repository PR copy.
6. [`HANDOFF.md`](HANDOFF.md) states exactly what teammates must finish today.

The English PDF and PPT below are the submission artifacts. The current PPT's
authentic M1 screenshot is acceptable for submission; a later English WebUI
capture may optionally replace slide 5 without changing the claims. Older
drafts and Chinese files are references, not submission deliverables.

## Current repository and evidence boundary

| Item | Current state |
|---|---|
| Current product `main` at refresh | `c4d14bf042ad53baa9b726a0e11fbd9ffd37e5fd` |
| Exact tested implementation | `c9ec07489d17a2abb74bac66a23ade2c775c1b06`, merged through PR #52 |
| Complete W7900 product result | PASS: local Qwen3.5-9B generated M1-M4, evidence was inspected, an upstream correction invalidated/regenerated downstream work, and M5 completed route/privacy review plus private HTML/Markdown/JSON delivery |
| W7900 environment | Radeon PRO W7900 `gfx1100`, 96 CUs, 48 GiB; ROCm/HIP 7.2; vLLM 0.26.0; BF16; 20K max context |
| Exact model | `Qwen/Qwen3.5-9B` revision `460979c3d11864dd16408d860ac930a360a2fac2` |
| Complete-product evidence | `evidence/milestones/e8-a0-w7900/20260806T122806Z/` on `main` |
| Stage 2 decision | S0 PASS at approximately 120 s; P1 PASS at 109.21 s on the same one-case journey. P1 selected; S0 rollback. This is not a generalized performance claim |
| Stage 2 evidence | `evidence/performance/stage2-minimal/20260806T124938Z/` on `main` |
| Final launcher | PR #58 merged; `bash scripts/serve_final_vllm.sh` launches P1 and `SERVING_PROFILE=S0` provides rollback |
| Demo navigation polish | PR #59 open at refresh; useful for the recording, not required for product evidence |
| Media plan | PR #55 defines seven English slides and an approximately four-minute demo centered on real Web UI operation |
| Official submission | English copy ready; organizer PR not yet opened |

## Generated artifacts

| Deliverable | Status | SHA-256 |
|---|---|---|
| [English Project Specification](deliverables/Experience_Asset_Project_Specification.pdf) | R8 final content; formal architecture diagram included | `d83929e2714c39d159991cc7ec56f2a846477883c5dbaee1357558f573e63307` |
| [English Track 2 presentation](deliverables/Experience_Asset_Track2_Deck.pptx) | R8 submission artifact; slide 5 replacement is optional | `9bbb5d67447e2f7044e3f99a0564ba0e6ec48a1caa3ccf8a7274ead74d963019` |

### Archived references - do not submit by default

| Reference | Status | SHA-256 |
|---|---|---|
| [Earlier English specification draft](deliverables/Experience_Asset_Project_Specification_Draft.pdf) | retained reference | `807fe0043e02e5a3b88ecf684729cf408240b0ff429ab576f32af404b30fd89d` |
| [Earlier English presentation draft](deliverables/Experience_Asset_Track2_Deck_Draft.pptx) | retained reference | `e817b264f1625edef81ffa28eb88eba0608ff64c21259de5d30489682c574b21` |
| [Chinese specification reference](deliverables/Experience_Asset_项目规格说明_中文初稿.pdf) | optional | `9edbed4feb90f9caf768a670ac318bc4992595ad80e38cc981f0e40b35ee77b9` |
| [Chinese presentation reference](deliverables/Experience_Asset_赛道二_中文初稿.pptx) | optional | `c34629b78821091c02a71a52ed92e8a75e53c8b50d2d88ff15dca1747427ba5d` |

When a binary and text source disagree, use the current source facts and
regenerate or edit the binary. Never weaken an evidence boundary to make two
artifacts appear consistent.

## Product story

**Experience Asset is a private local Agent that turns fragmented first-person
experience into an evidence-bound, editable and reusable asset, then prepares
audience-specific deliverables without surrendering user control over facts,
privacy or approval.**

```text
M1 Experience Brief
-> M2 Critical Moment Map
-> M3 Decision and Evidence Ledger
-> M4 Insight and Boundary Map
-> M5 Route Readiness Matrix
-> private preview / approved HTML / Markdown / JSON
```

React and FastAPI provide the product surface. LangGraph owns the durable
multi-step graph. The deterministic Runtime owns tool permissions, argument
validation, phase-gated retrieval, privacy, approval, retries, persistence and
verification. Model output is a proposal, never execution authority. The core
inference path is local through loopback vLLM, ROCm and Radeon PRO W7900.

## What remains before official publication

- verify the 3-5 minute Demo folder opens while signed out;
- integrate PR #54 and decide whether optional PR #59 is included in the Demo;
- provide signed-out public access to the complete source and materials; the
  team repository is currently private;
- use the confirmed PR title `Track 2, AMD_YES, Experience Asset`;
- verify all public links while signed out;
- open the English PR against the organizer repository with the required title;
- complete submission before 2026-08-06 23:59 UTC+8.

Raw recording media, credentials, private prompts, model weights, caches and
private evidence must not be committed here. Updating this package does not
authorize publication, merge or the official contest PR.
