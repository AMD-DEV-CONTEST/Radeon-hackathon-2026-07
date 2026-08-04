# External submission form draft

No separate official external form was found in the verified Luma page, Rules
and Conditions, Hugging Face announcement, or official upstream repository.
The documented submission mechanism is a fork and pull request to the official
AMD repository. These values are ready if an official form is later announced.

| Field | Prepared value |
|---|---|
| Project title | BrandPilot Local |
| Team name | **Private registered value still needs confirmation; do not guess** |
| Track | Track 1 - Multimodal AI / Development of Multimodal Content Creation Tools |
| Team members | Talal Khawaja; Aqeela Urooj |
| Short description | An AMD Radeon-powered creative studio prototype that converts product images and campaign briefs into reviewable, platform-ready marketing concepts. |
| Repository | https://github.com/kmt9967/brandpilot-local |
| Official fork/PR | Add after the official submission PR is created |
| Demo video | Add after user records/uploads the 3-5 minute demo |
| Project Profile | `submission/BrandPilot-Local-Project-Profile.pdf` |
| Presentation | `submission/BrandPilot-Local-Presentation.pptx` and PDF export |
| Live URL | Not required / local-first prototype |

## Long description

BrandPilot Local combines validated product-image intake, campaign objectives,
audience and benefits, brand tone and colors, creative direction, output
formats, generated concepts, copy, and persisted human review in one responsive
workspace. Mock mode is the default for safe local demonstration. Separately,
real SDXL image-to-image inference and authenticated FastAPI loopback generation
were verified on AMD Radeon with ROCm. Official rc-tunnel installation and
activation were also verified. The complete public browser edge remained
blocked because the platform-assigned hostname did not resolve in public DNS,
so no full browser-to-Radeon E2E claim is made.

## Problem / solution / innovation

- **Problem:** Small teams fragment campaign creation across prompt tools,
  design files, copy documents, and approval threads.
- **Solution:** One local-first, review-first campaign workflow from product
  asset and brief to disclosed concepts and a stored human decision.
- **Innovation:** Generation is embedded inside a coherent brand workflow with
  explicit provenance, platform framing, persistence, and accountability.

## AMD Radeon and ROCm usage

One real SDXL img2img run used an AMD Radeon `gfx1100` device, PyTorch ROCm/HIP,
fp16, exact pinned model revision, 768 x 768 output, 15 steps, and recorded
timing, memory, and SHA-256. A later authenticated FastAPI loopback job also
completed and persisted an Approved review state.

## Limitations

No permanent hosting, production readiness, completed public browser-to-Radeon
generation, product/logo/packaging-text preservation, IP-Adapter validation, or
commercial model clearance is claimed.

Personal contact fields must be completed only in the private official form and
must never be copied into this repository. Do not click any final Submit action
without explicit user approval.
