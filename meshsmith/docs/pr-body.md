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
| Demo video (4m50s, recorded live on AMD Radeon) | `meshsmith/assets/demo.mp4` |
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

## Verified on AMD Radeon hardware

**This submission was built, run and recorded on an AMD Radeon GPU.** On 6 August 2026 it
ran on a Radeon Cloud instance — Radeon Graphics `gfx1100` (Navi 31), 48 GB VRAM,
ROCm 7.2.53211, torch 2.9.1 — with **no source changes of any kind**. The same commit
that runs on CUDA produced watertight, print-ready assets on ROCm.

```
Device: {'backend': 'AMD ROCm 7.2.53211-e1a6bc5663', 'torch': '2.9.1+gitff65f5b',
         'device': 'cuda:0', 'gpu': 'AMD Radeon Graphics', 'vram_gb': 48.0}
SMOKE TEST PASSED
```

- **Demo video** (`meshsmith/assets/demo.mp4`, 4m50s) is a live recording of that Radeon
  instance: `rocm-smi` identifying the hardware, the ROCm banner, a full generation with
  per-stage timings, and the printability report.
- **Benchmark**: 5 prompts, average **48.7 s per asset**, 4 of 5 at 90/100 printability
  (`docs/benchmark.md`). Peak VRAM 10.8 GB, so it fits 16 GB Radeon cards too.
- **Auto-orientation** cut support volume by 6.6–78.3% across those runs.

Thanks to @chejh-amd for issuing the Radeon Cloud credits that made this possible
(see issue #135).

## Team

Bradley Grubbs (solo) · GitHub: `bgrubbs1` · AMD AI Developer Program member

MIT licensed. Model weights keep their upstream licences (SDXL-Turbo: Stability AI
community licence; Hunyuan3D-2: Tencent Hunyuan community licence).
