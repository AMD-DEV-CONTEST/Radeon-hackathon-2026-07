# MeshSmith benchmark — Quadro RTX 8000 (NVIDIA CUDA 12.4)

Preset: `standard` · seed 7 · torch 2.6.0+cu124

| Prompt | Image (s) | 3D shape (s) | Total (s) | Faces | Print score |
|---|---:|---:|---:|---:|---:|
| a chess knight piece, ornate baroque style | 42.6 | 263.5 | 352.6 | 1,107,120 | 90/100 |
| a cute robot mascot with round head | 2.7 | 196.3 | 240.8 | 866,162 | 80/100 |
| a replacement drawer knob, fluted cylinder | 1.2 | 72.4 | 130.2 | 1,466,374 | 90/100 |
| a low-poly fox figurine | 1.3 | 72.1 | 129.2 | 870,080 | 90/100 |
| a Greek amphora vase with two handles | 1.2 | 76.7 | 181.3 | 2,184,874 | 100/100 |

**Average end-to-end: 206.8s per asset.**

Notes: the first row includes one-time model loading (SDXL-Turbo + Hunyuan3D-2 into
VRAM); warm steady state is ~2s image + ~75s shape at `standard`. The `draft` preset
(Hunyuan3D-2mini-turbo) generates in ~25s warm. "Faces" is the full-detail repaired
mesh; the game GLB is decimated to the preset budget.