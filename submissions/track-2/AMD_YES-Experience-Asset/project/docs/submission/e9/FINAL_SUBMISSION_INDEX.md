# Experience Asset - Final Submission Index

> **Status:** `SUBMISSION_PACKAGE_READY / DEMO_LINK_ADDED`
>
> **Official requirements checked against:**
> `AMD-DEV-CONTEST/Radeon-hackathon-2026-07@d95240359c837717230b36bdab12df94f1669cf6`
>
> **Last updated:** 2026-08-06

This page is the single handoff for every submission item other than the Demo
video. It maps the project package directly to the official Track 2
requirements and separates finished content from publication-time actions.

## Required package

| Official Track 2 requirement | Project deliverable | Status |
|---|---|---|
| Project Specification Document | [`deliverables/Experience_Asset_Project_Specification.pdf`](deliverables/Experience_Asset_Project_Specification.pdf) with editable source at [`source/PROJECT_SPECIFICATION_EN.md`](source/PROJECT_SPECIFICATION_EN.md) | Ready |
| Complete source code repository | Repository root, application code, tests, scripts and evidence under `kinnyuww/amd-devmaster-track2-agent` | Ready; public access still required |
| README with environment, startup and dependencies | [`../../../README.md`](../../../README.md) | Ready |
| Demo Video, recommended 3-5 minutes | [Google Drive Demo folder](https://drive.google.com/drive/folders/1_cOmcYBIJuPfkoJ4VuA7ZuBYV8nYB8yr?usp=drive_link) | Added; Drive sharing must allow signed-out viewing |
| PPT or Poster | [`deliverables/Experience_Asset_Track2_Deck.pptx`](deliverables/Experience_Asset_Track2_Deck.pptx) | Ready |
| English submission and organizer PR | [`source/OFFICIAL_PR_DRAFT.md`](source/OFFICIAL_PR_DRAFT.md) | Copy ready; team name confirmed as `AMD_YES` |

The PDF, PPT, specification source, judge entry and organizer-PR copy use the
same product, model, device, evidence and limitation boundaries. The current
PPT is submission-ready as it stands. Replacing slide 5 with a later English
WebUI capture is optional presentation polish, not a missing requirement.

## Judge reading route

1. [`source/JUDGE_ENTRY.md`](source/JUDGE_ENTRY.md) - one-minute product and
   evidence summary.
2. [`deliverables/Experience_Asset_Project_Specification.pdf`](deliverables/Experience_Asset_Project_Specification.pdf)
   - application scenario, architecture, capabilities, local deployment and
   Radeon optimization.
3. [`../../../README.md`](../../../README.md) - environment, dependencies, startup,
   reproduction and tests.
4. [`deliverables/Experience_Asset_Track2_Deck.pptx`](deliverables/Experience_Asset_Track2_Deck.pptx)
   - seven-slide English presentation.
5. [`source/EVIDENCE_CARD.md`](source/EVIDENCE_CARD.md) - exact W7900 and
   bounded performance evidence.

## Frozen evidence identity

- Tested application implementation:
  `c9ec07489d17a2abb74bac66a23ade2c775c1b06`
- Current repository `main` before the documentation PR merges:
  `c4d14bf042ad53baa9b726a0e11fbd9ffd37e5fd`
- Model: `Qwen/Qwen3.5-9B` revision
  `460979c3d11864dd16408d860ac930a360a2fac2`, BF16, no quantization
- Runtime: vLLM 0.26.0, ROCm/HIP 7.2
- Device: Radeon PRO W7900, 48 GiB
- Complete-product evidence:
  `evidence/milestones/e8-a0-w7900/20260806T122806Z/`
- Stage 2 evidence:
  `evidence/performance/stage2-minimal/20260806T124938Z/`
- Launch profile: P1-prefix-cache; S0 is the one-command rollback

## Publication-time actions, not missing documents

1. Merge or otherwise integrate PR #54 so the final documents are present in
   the submission source.
2. Use the confirmed registered team name `AMD_YES` in the PR title.
3. Make the complete source and material links accessible to a signed-out
   reviewer. The team repository is currently private; either publish an
   approved clean source repository or copy the complete source and package
   into the public organizer-repository submission branch.
4. Verify the Demo folder is set to "Anyone with the link - Viewer" and opens
   in a signed-out browser.
5. Open the English PR against the organizer repository using
   `Track 2, AMD_YES, Experience Asset`.

Do not commit credentials, private prompts, model weights, caches, databases,
raw private evidence or recording source files. Opening the organizer PR and
changing repository visibility remain owner-authorized publication actions.
