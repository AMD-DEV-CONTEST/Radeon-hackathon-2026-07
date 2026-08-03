# StagePoster Submission Assets

Generated poster images and demo screenshots for the AMD AI DevMaster Hackathon 2026, Track 1 submission.

## Structure

| Directory | Contents |
|---|---|
| `demo-screenshots/` | End-to-end demo workflow screenshots (Playwright E2E capture) |
| `candidates/` | GPU-generated candidate images from Z-Image Turbo (shown to user for selection) |
| `generated-posters/` | Final composed posters with deterministic text + logo overlay + AI review |

## Demo Screenshots

| Screenshot | Description |
|---|---|
| `generate-start.png` | Project creation form — event info + visual language input |
| `candidates.png` | 3 parallel GPU-generated candidates presented for selection |
| `result.png` | Selected candidate, review score, and composition result |
| `final-complete.png` | Final poster with text, logo, barcode composed deterministically |
| `step4.png` | Step 4 — output confirmation before generation |
| `after-submit.png` | Post-submission state |

## GPU Candidates (Z-Image Turbo on W7900)

`candidates/z-image-turbo_0000{1,2,3}_.png` — Three visual candidates generated in parallel (~90s) by ComfyUI + Z-Image Turbo BF16 on AMD Radeon PRO W7900 via ROCm 7.2.

## Final Posters

`generated-posters/final-poster.png` — AI-reviewed and composed final poster (1024×1536, 300 DPI).

`generated-posters/review-round-2-final_poster.png` — After Qwen3.5-9B Vision auto-optimization round 2.
