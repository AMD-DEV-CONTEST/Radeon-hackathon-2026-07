# Radeon Evidence

## Candidate identity

- Candidate: `fd4e45b3e62a837d4a613473abc9310ce0c9a1b4`
- Stable service during validation:
  `657ac0b54248f0cd71b46c4d9576ef4eb0425104`
- Candidate and stable `/config`: HTTP 200 before and after the UI run
- Candidate Gradio: 6.15.1, 71 components, 12 dependencies

## Runtime

- ROCm: 7.2.1
- PyTorch: `2.9.1+gitff65f5b`
- PyTorch HIP: `7.2.53211-e1a6bc5663`
- Diffusers: 0.39.0
- Python: 3.12

## Current reviewed deployment

- Deployed/source SHA: `b0efb77ba265a317767598f2617ed40c0ad3af57`
- Tracked worktree: clean
- Device: `AMD Radeon Graphics`
- UI: HTTP 200, Gradio 6.15.1, 71 components
- Focused formal-approval/batch tests on the AMD host: 64 passed

This is a current deployment readback. The four-image wall below remains bound
to candidate `fd4e45b`; the current record does not relabel historical output.

## Actual browser-driven Preview wall

Wall ID: `preview-wall-3a18518754104e71ab06f32050c2e3bf`

| Variation | Seed | Status | Content SHA-256 |
|---:|---:|---|---|
| 0 | 8387657995075258963 | `COMPLETED` | `2ea5dcbe18a5697d53b840f5b5c6f71ea60e84d9e4649056fe3db4a75308be54` |
| 1 | 9099601000186757298 | `COMPLETED` | `d053b7359a65b0668d1584dc727229a461be0e2d18b56eac26c4b8b7df7f4388` |
| 2 | 3199624802890984311 | `COMPLETED` | `3465123192ecef5e17266ba1b522b184ec332945a4307bc816b09cb51a323e8b` |
| 3 | 5529225881622334695 | `COMPLETED` | `2084fb939d0a8a1d487c09a7d27a9b229565a05ac657fc83d2d0e0ba210396d6` |

The Gradio capture completed in 65.38 seconds. The workflow manifest records
38.45 seconds inside the wall run, four requested and completed items, four
unique content hashes, zero failures, and completed cleanup. The difference is
browser upload, readiness, queue, rendering, and capture overhead.

This is execution evidence. It does not establish human-perceived quality or
diversity. The machine-readable records truthfully retain:

```text
evidence_class=ENGINEERING_ONLY
verification=NOT_RUN
repair=NOT_RUN
export=NOT_RUN
quality=NOT_EVALUATED
diversity=NOT_EVALUATED
```

## Complementary stability and creative-variation walls

These two runs answer different demonstration questions and are not combined
into one metric claim.

| Evidence | Source commit | Runtime result | Claim boundary |
|---|---|---|---|
| Production-profile stability | `f60fd8e` | 4/4 completed exports, 125.54 s, four unique seeds and hashes | L1 `PASS`; L2 `UNVERIFIABLE`; L3 `NOT_APPLICABLE`; formal threshold `DRAFT` |
| Bold Preview creative variation | `4482837` | 4/4 completed images, 45.47 s, four unique seeds and hashes | `ENGINEERING_ONLY`; Verification/Repair/Export `NOT_RUN`; quality/diversity `NOT_EVALUATED` |

### Production-profile stability

![Production-profile stability wall](media/evidence/stability-production-n4-wall.png)

This wall shows one synthetic source, one style reference, and four sequential
768x768 Production-profile jobs from the same compiled Spec. The runtime route
was `approved/` for all four because the configured required L1 checks passed.
That routing result is not calibrated L2/L3 approval, and this independent-job
wall is not the formal L2 cohort gate. The current formal Production gate stays
closed while its threshold evidence is `DRAFT`.

### Bold Preview creative variation

![Bold Preview creative-variation wall](media/evidence/creative-preview-n4-wall.png)

This wall uses the submitted generated source/style pair and stronger Preview
settings to expose more visible changes in framing, palette, lighting, and
background geometry. It records actual AMD execution at commit `4482837`, one
pipeline load, four deterministic seeds, four unique content hashes, zero
failures, and completed cleanup. It does not enter the Production package or
establish human-rated quality or perceptual diversity.

## Verification gates

- AMD focused tests: 1,009 passed, 1 skipped
- Ruff check: passed
- Ruff format check: 292 files already formatted
- Candidate service after gates: HTTP 200
- Stable service during candidate deployment: HTTP 200

## Files

- [`evidence/amd_deployment_current.json`](evidence/amd_deployment_current.json)
- [`evidence/amd_environment.json`](evidence/amd_environment.json)
- [`evidence/radeon_preview_wall.json`](evidence/radeon_preview_wall.json)
- [`evidence/radeon_production_stability_n4.json`](evidence/radeon_production_stability_n4.json)
- [`evidence/radeon_bold_preview_n4.json`](evidence/radeon_bold_preview_n4.json)
- [`evidence/radeon_ui_capture.json`](evidence/radeon_ui_capture.json)
- [`evidence/video_manifest.json`](evidence/video_manifest.json)
- [`media/radeon-ui-preview-wall.png`](media/radeon-ui-preview-wall.png)
- [`media/evidence/stability-production-n4-wall.png`](media/evidence/stability-production-n4-wall.png)
- [`media/evidence/creative-preview-n4-wall.png`](media/evidence/creative-preview-n4-wall.png)
- [`SpecStyle_Radeon_Demo.mp4`](SpecStyle_Radeon_Demo.mp4)
- [`SpecStyle_Radeon_UI_Run.webm`](SpecStyle_Radeon_UI_Run.webm)

## External inputs still required for stronger claims

- Legally approved held-out assets and independent human labels
- Label-approval and test-reveal authorization receipts
- A trusted Production threshold package and owner approval
- Independent raters for blind usable-yield evaluation
- A frozen equal-budget five-arm Radeon repair study

The repository implements fail-closed protocols for these inputs; it does not
fabricate them.
