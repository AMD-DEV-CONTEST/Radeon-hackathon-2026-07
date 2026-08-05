<!-- PR title: Track 1, Bradley Grubbs, MeshSmith -->

# MeshSmith — a local 3D asset foundry

**Track 1 · Multimodal Content Creation Tools**

Text or image in → **print-ready STL + game-ready GLB** out. Fully local on AMD Radeon
(ROCm): SDXL-Turbo → u2net cutout → Hunyuan3D-2 (shape-only, pure PyTorch — no custom
CUDA extensions) → automatic mesh repair → decimation + xatlas UVs + PBR → and a
printability engine that scales to real millimetres, searches 26 orientations to minimise
support material, ray-samples wall thickness, and scores the part before you print it.

Generated meshes normally fail at the point of use — not watertight, no UVs, no physical
scale, floating debris, and orientations that drown an FDM print in support. MeshSmith is
the last mile between "look at this mesh" and "here is the STL your slicer accepts".

## Submission contents (this PR adds `meshsmith/`)

| Requirement | Where |
|---|---|
| Project Profile Document (PDF) | `meshsmith/docs/project-profile.pdf` |
| Complete source code + README (env config, startup, dependencies) | `meshsmith/` · `meshsmith/README.md` |
| Demo video (5m38s, full pipeline run) | `meshsmith/assets/demo.mp4` — see note below |
| Supplementary material (poster) | `meshsmith/docs/poster.pdf` |
| Reproducible benchmark | `meshsmith/docs/benchmark.md` · `scripts/benchmark.py` |
| Example outputs (GLB + printability reports) | `meshsmith/assets/examples/` |
| Output-diversity gallery | `meshsmith/assets/gallery.png` |

## Reproducing it

```bash
pip install -r requirements.txt          # torch + torchvision come from the ROCm container
python scripts/smoke_test.py             # mesh stack check, no GPU or weights needed, ~5 s
python app.py                            # Gradio UI with 3D viewer
python -m meshsmith.cli "a chess knight piece" --quality standard
```

`docker/Dockerfile.rocm` builds the whole thing on the official `rocm/pytorch` base.
`docker/Dockerfile.deptest` is a clean-room install test (fresh `python:3.12-slim`, CPU
wheels, full import chain + smoke test) that proves the dependency list is complete.

## AMD Radeon / ROCm

- Core inference (SDXL-Turbo, Hunyuan3D-2 DiT + ShapeVAE, fp16) runs **locally on the
  Radeon GPU**. No cloud API is involved in any core function.
- **Zero vendor-specific code** — every GPU stage goes through the portable `torch.cuda`
  API, which ROCm maps to HIP. Backend detection is used only to label the run.
- Shape-only Hunyuan3D **by design**: the texture stage needs a custom CUDA rasterizer,
  so it is excluded and the whole pipeline installs with plain `pip` in a ROCm container —
  no compiler, no HIP porting.
- Every run reports per-stage wall time and peak VRAM; `scripts/benchmark.py` regenerates
  the results table on any machine.

## A note on the demo video — please read

**The attached demo video was recorded on an NVIDIA GPU, not an AMD Radeon, and I want
to flag that up front rather than let a reviewer discover it.**

I have not been able to obtain any Radeon GPU time. I registered for the hackathon and
the AMD AI Developer Program, confirmed my Radeon Cloud login email matches my Luma
registration email exactly as `#devmaster-faq` instructs, and my Radeon Cloud balance is
still 0 credits while my Luma registration still reads "pending host approval." I have
escalated to the organizers — see
[issue #135](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/issues/135)
and by email to ai_dev_contests@amd.com.

**If credits are issued before the deadline I will immediately re-record on Radeon
hardware and update this PR.** I am submitting now so a complete entry exists either way.

What this does *not* affect is the ROCm engineering, which stands on its own:

- **No vendor-specific code.** Every GPU stage runs through the portable `torch.cuda`
  API that ROCm maps to HIP. Backend detection only labels the run.
- **Shape-only Hunyuan3D by design**, specifically so no custom CUDA rasterizer is
  needed and the stack installs with plain `pip` in a `rocm/pytorch` container.
- **`docker/Dockerfile.rocm`** builds the whole thing on the official ROCm base and
  asserts the ROCm torch survives the install.
- **`docker/Dockerfile.deptest`** proves from a bare `python:3.12-slim` image, with no
  compiler and none of my local packages, that the dependency set installs and the
  pipeline runs — it is what caught two real install blockers (an undeclared
  `torchvision` dependency and a missing `libGL.so.1`).

<!-- SUPERSEDED CONTINGENCY TEXT — kept for reference

## A note on the demo video

This submission's demo video was recorded on an NVIDIA GPU rather than an AMD Radeon,
and I want to flag that plainly rather than let a judge discover it.

I registered for the hackathon and the AMD AI Developer Program, confirmed my Radeon
Cloud login email matches my Luma registration email as the #devmaster-faq instructs,
and contacted the organizers via Discord and ai_dev_contests@amd.com. My Luma
registration remained in "pending host approval" and my Radeon Cloud balance stayed at
0 credits through the deadline, so no Radeon GPU time was ever available to me.

What this does *not* change: MeshSmith carries no vendor-specific code. Every GPU stage
runs through the portable `torch.cuda` API that ROCm maps to HIP, shape generation is
deliberately shape-only so no custom CUDA rasterizer is involved, and
`docker/Dockerfile.rocm` builds the whole stack on the official `rocm/pytorch` base.
`docker/Dockerfile.deptest` proves from a bare `python:3.12-slim` image that the
dependency set installs and the pipeline runs with no compiler and no vendor packages.
The ROCm path is engineered and documented; it is only the recording that is on the
wrong vendor, and I will happily re-record on Radeon hardware if given access.
-->

## Team

Bradley Grubbs (solo) · GitHub: `bgrubbs1` · AMD AI Developer Program member

MIT licensed. Model weights keep their upstream licences (SDXL-Turbo: Stability AI
community licence; Hunyuan3D-2: Tencent Hunyuan community licence).
