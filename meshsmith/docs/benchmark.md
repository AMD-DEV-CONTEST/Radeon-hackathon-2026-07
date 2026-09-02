# MeshSmith benchmark — AMD Radeon Graphics (ROCm 7.2.53211)

Measured on an **AMD Radeon Cloud** instance: Radeon Graphics `gfx1100` (Navi 31),
48 GB VRAM, ROCm 7.2.53211, torch 2.9.1. Preset `draft`, seed 7.
Reproduce with `python scripts/benchmark.py --quality draft --seed 7`.

| Prompt | Image (s) | 3D shape (s) | Total (s) | Faces | Print score |
|---|---:|---:|---:|---:|---:|
| a chess knight piece, ornate baroque style | 13.0 | 46.5 | 71.3 | 332,260 | 90/100 |
| a cute robot mascot with round head | 0.2 | 25.2 | 38.2 | 368,208 | 90/100 |
| a replacement drawer knob, fluted cylinder | 0.2 | 24.5 | 58.0 | 1,179,984 | 90/100 |
| a low-poly fox figurine | 0.2 | 24.1 | 39.4 | 353,640 | 90/100 |
| a Greek amphora vase with two handles | 0.2 | 24.2 | 36.5 | 815,560 | 70/100 |

**Average end-to-end: 48.7 s per asset on the Radeon.**

The first row carries the one-time cost of loading SDXL-Turbo into VRAM (13.0 s versus
0.2 s once resident) — MeshSmith keeps both models loaded on cards with ≥30 GB, which
is why every later row is faster.

Per-stage detail from a single warm run on the same Radeon (`a low-poly fox figurine`,
draft), as shown in the demo video:

| Stage | Time (s) | Peak VRAM (GB) |
|---|---:|---:|
| Text → image (SDXL-Turbo) | 13.39 | 7.55 |
| Background removal (u2net) | 1.48 | 6.64 |
| Image → 3D (Hunyuan3D draft) | 45.42 | 10.78 |
| Mesh cleanup & repair | 0.99 | 10.42 |
| Decimate + UV unwrap | 2.58 | 10.42 |
| Print analysis + orientation | 7.50 | 10.42 |
| Export GLB/STL/OBJ | 0.20 | 10.42 |
| **Total** | **71.55** | |

Peak VRAM stays near 10.8 GB, so the pipeline fits comfortably on 16 GB Radeon cards
as well as this 48 GB one.

## Cross-vendor reference (NVIDIA, same code, no modifications)

The identical source ran on an NVIDIA Quadro RTX 8000 (48 GB, CUDA 12.4) during
development. These figures were taken at the **`standard`** preset, so they are *not*
a like-for-like comparison with the Radeon table above — they are included only to show
the same code path producing equivalent-quality results on both vendors.

| Prompt | Image (s) | 3D shape (s) | Total (s) | Print score |
|---|---:|---:|---:|---:|
| a chess knight piece, ornate baroque style | 42.6 | 263.5 | 352.6 | 90/100 |
| a cute robot mascot with round head | 2.7 | 196.3 | 240.8 | 80/100 |
| a replacement drawer knob, fluted cylinder | 1.2 | 72.4 | 130.2 | 90/100 |
| a low-poly fox figurine | 1.3 | 72.1 | 129.2 | 90/100 |
| a Greek amphora vase with two handles | 1.2 | 76.7 | 181.3 | 100/100 |

The point of this table is portability, not a speed contest: **not one line of code
changed between the two runs.** `meshsmith/device.py` detects the backend through
`torch.version.hip` purely to label the run; every GPU stage uses the same
`torch.cuda` API, which ROCm maps to HIP.
