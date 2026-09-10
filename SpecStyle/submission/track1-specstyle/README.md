# SpecStyle - AMD AI DevMaster Track 1 Submission

SpecStyle is a local StyleOps engine for AMD Radeon GPUs. It turns a versioned
Style Spec into separate Preview and Production execution plans, records
generation evidence, applies layered verification contracts, routes outputs,
and supports bounded repair and replay workflows.

## Deliverables

- [`SpecStyle_Project_Profile.pdf`](SpecStyle_Project_Profile.pdf): English
  project profile submitted by `guan`, covering users and scenarios,
  architecture, model stack, and AMD/ROCm use.
- [`SpecStyle_Track1_Deck.pptx`](SpecStyle_Track1_Deck.pptx): editable English
  presentation submitted by `guan`.
- [`SpecStyle_Radeon_Demo.mp4`](SpecStyle_Radeon_Demo.mp4): 196.04-second
  H.264/AAC video showing current AMD command-line evidence, the real
  browser-driven Radeon run, the four outputs at inspectable size, and the
  stability/diversity claim boundaries. Only the inference wait is shown at
  4x; the raw capture remains available below.
- [`SpecStyle_Radeon_UI_Run.webm`](SpecStyle_Radeon_UI_Run.webm): raw 73.28
  second Gradio capture from candidate `fd4e45b`.
- [`PROJECT_PROFILE.md`](PROJECT_PROFILE.md): text source for the PDF.
- [`RADEON_EVIDENCE.md`](RADEON_EVIDENCE.md): evidence index and claim
  boundaries.
- [`ASSET_PROVENANCE.md`](ASSET_PROVENANCE.md): demo media provenance and
  redistribution notes.
- [`formal-study-kit/`](formal-study-kit/): exact formal L2/L3 study templates,
  blinded rater protocol, provenance register, approval roles, and fail-closed
  operator commands. It contains no approved labels.
- [`evidence/video_manifest.json`](evidence/video_manifest.json): codecs,
  duration, source hashes, and the exact composition timeline.
- [`evidence/amd_deployment_current.json`](evidence/amd_deployment_current.json):
  current reviewed AMD deployment SHA, GPU/runtime, UI health, and focused
  test result.
- [`evidence/radeon_production_stability_n4.json`](evidence/radeon_production_stability_n4.json):
  four Production-profile engineering jobs with L1/L2/L3 state and formal-gate
  boundaries.
- [`evidence/radeon_bold_preview_n4.json`](evidence/radeon_bold_preview_n4.json):
  a higher-variation Preview wall with exact seeds, hashes, runtime, and
  `NOT_EVALUATED` claim labels.
- [`SHA256SUMS`](SHA256SUMS): hashes for every submitted document, evidence
  record, image, and media artifact.

## Verified Radeon candidate

| Item | Result |
|---|---|
| Candidate commit | `fd4e45b3e62a837d4a613473abc9310ce0c9a1b4` |
| Stable service during validation | `657ac0b54248f0cd71b46c4d9576ef4eb0425104` |
| Runtime | ROCm 7.2.1, PyTorch `2.9.1+gitff65f5b`, HIP `7.2.53211-e1a6bc5663` |
| Application | Diffusers 0.39.0, Gradio 6.15.1 |
| AMD focused gate | 1,009 passed, 1 skipped; Ruff check and format passed |
| Actual UI wall | 4 requested, 4 completed, 4 unique content hashes, 0 failed |
| Evidence class | `ENGINEERING_ONLY` |
| Perceptual claims | quality `NOT_EVALUATED`, diversity `NOT_EVALUATED` |

The four Preview images are shown in
[`media/radeon-ui-preview-wall.png`](media/radeon-ui-preview-wall.png). The raw
records are under [`evidence/`](evidence/).

## Complementary Radeon evidence

### Production-profile engineering stability

![Production-profile stability wall](media/evidence/stability-production-n4-wall.png)

Four sequential 768x768 jobs completed and exported in 125.54 seconds on AMD
Radeon. All required L1 checks passed, while L2 remained `UNVERIFIABLE` and L3
was `NOT_APPLICABLE`. The runtime routed all four files to `approved/`, but that
route means the configured L1-required workflow gate passed; it is not formal
L2 or L3 approval. This retained `f60fd8e` engineering run used one source,
style reference, and compiled Spec. The formal Production threshold evidence
was still `DRAFT`, so the current formal gate remains closed.

### Creative variation: Bold Preview

![Bold Preview creative-variation wall](media/evidence/creative-preview-n4-wall.png)

Source commit `4482837` produced four 512x512 Preview outputs in 45.47 seconds
with four unique deterministic seeds and content hashes. The stronger
Preview settings visibly expose a broader range of composition, palette,
lighting, and background geometry while retaining the same source and style
inputs. This wall remains `ENGINEERING_ONLY`: Verification, Repair, and Export
were `NOT_RUN`, and quality and perceptual diversity are `NOT_EVALUATED`.

## Current reviewed deployment

The current AMD host checkout and service were independently read back at
`b0efb77ba265a317767598f2617ed40c0ad3af57`: the tracked worktree was clean,
the device was `AMD Radeon Graphics`, the UI returned HTTP 200 with Gradio
6.15.1 and 71 components, and 64 focused formal-approval/batch tests passed.
This deployment record does not reassign the four-image wall from its recorded
candidate `fd4e45b`.

## Reproduce

Use the pinned installation and launch commands in the repository root
[`README.md`](../../README.md). The installer uses `--no-deps`, rejects generic
Torch packages, and verifies that the AMD image's ROCm Torch installation did
not change.

Local model weights, immutable model revisions, content hashes, manifests, and
license approvals are mandatory runtime inputs and are intentionally not
included in Git.

## Claim boundary

The submission proves a real local Radeon UI workflow, deterministic execution
evidence, Preview/Production separation, Production export examples, and
fail-closed evaluation infrastructure. The new context v4, pinned
`structure_only` L3 gate, formal batch metric and atomic cohort publication are
CPU-validated but not yet evidenced on Radeon with approved thresholds. It does
not claim calibrated L2/L3 accuracy, human-rated perceptual diversity, or a
Radeon repair uplift study. The two complementary walls above demonstrate
engineering stability and visibly different Preview outcomes without changing
those formal claim boundaries.
Those results require approved held-out assets, independent labels, and a
trusted Production threshold package that are not available in this repository.

## Submission route

The official competition repository is
<https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07>. The submission PR
title is `Track 1, guan, SpecStyle`.
