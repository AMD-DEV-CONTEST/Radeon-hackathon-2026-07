# Submission Status

Track: **Track 1 — Multimodal Content Creation Tools**

Owner / team: **kaggle4youAMD**

Application: **SpriteFusion 2D**

## Included in this pull request

- Complete application source snapshot
- English project overview and reproducibility instructions
- Python backend, CLI, Electron frontend, tests, and ComfyUI integration
- AMD Radeon / ROCm deployment and validation notes
- Final 239-second Radeon GUI MP4 covering the implemented asset-production workflow
- Project profile PDF (`docs/SpriteFusion2D-profile.pdf`)
- Poster (`docs/SpriteFusion2D-poster.pdf`)
- AMD Radeon benchmark receipts (`benchmarks/receipts/`) backing every
  performance figure quoted in the profile and poster

All Track 1 required deliverables are now present in this branch.

## Known gaps, stated deliberately

- Video generation is not part of this submission; the application keeps an
  extension point for it but nothing is claimed as implemented.
- Three rows of the AMD acceptance matrix in `BENCHMARKS.md` (exact-palette
  correctness, legacy-exactness oracle, rocprof kernel profile) have not been
  run on the Radeon host. They are marked pending rather than assumed to
  pass; the throughput rows are complete and receipted.
