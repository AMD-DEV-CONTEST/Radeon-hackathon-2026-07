# AMD Radeon GPU / ROCm Adaptation

This document describes how IndieGen Asset Studio is adapted to run on AMD
Radeon GPUs with ROCm, and the measured performance from a live run.

## 1. Why the project targets ROCm

The heavy workflows (W1/W6 SDXL diffusion, W4 MusicGen) are PyTorch programs.
PyTorch on AMD GPUs is supported through **ROCm**, which maps the PyTorch
`cuda` API onto AMD hardware — so `torch.cuda.is_available()` returns `True` on
an ROCm build even though the silicon is AMD. ComfyUI, transformers and the
ControlNet/MiDaS ecosystem are all hardware-agnostic at the Python layer, which
means the entire stack runs on AMD once PyTorch is an ROCm build.

## 2. Automatic GPU detection in the setup script

`scripts/setup_comfyui.sh` selects the correct PyTorch wheel family at install
time:

```bash
if command -v nvidia-smi >/dev/null 2>&1; then
  # NVIDIA -> CUDA 12.8 wheels
  pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 torchaudio==2.11.0+cu128 \
    --index-url https://download.pytorch.org/whl/cu128
elif [ -e /dev/kfd ] || command -v rocminfo >/dev/null 2>&1; then
  # AMD -> ROCm 7.1 wheels
  pip install torch==2.11.0+rocm7.1 torchvision==0.26.0+rocm7.1 torchaudio==2.11.0+rocm7.1 \
    --index-url https://download.pytorch.org/whl/rocm7.1
else
  # CPU fallback
  ...
fi
```

The three branches pin **matching** torch/torchvision/torchaudio builds to avoid
ABI mismatch failures on startup — the most common ROCm pitfall. All model
code paths (SDXL, MiDaS, ControlNet, MusicGen, MarianMT, TripoSR) run unchanged
on the ROCm build; no per-model `cuda` vs `hip` branching is required.

## 3. Verified hardware & software configuration

Live environment used for all measurements:

| Item | Value |
|------|-------|
| GPU | AMD Radeon, `gfx1100` (Navi 31, 96 CUs, 1760 MHz) |
| VRAM | 48 GiB (51,522,830,336 bytes reported by ROCm) |
| ROCm userspace | `rocminfo`, `rocm-smi` present, `/dev/kfd` + `renderD133` |
| PyTorch | `2.11.0+rocm7.1`, `torchvision 0.26.0+rocm7.1`, `torchaudio 2.11.0+rocm7.1` |
| Device seen by ComfyUI | `cuda:0 AMD Radeon Graphics : native` |
| ComfyUI | 0.30.0 |
| Python | 3.12 |

```bash
$ rocm-smi --showproductname --showmeminfo vram --showuse
GPU[0]: Card Series:  AMD Radeon Graphics
GPU[0]: GFX Version:  gfx1100
GPU[0]: VRAM Total Memory (B): 51522830336
GPU[0]: VRAM Total Used Memory (B): 28053504
GPU[0]: GPU use (%): 0
```

## 4. Performance measurement methodology

1. Start ComfyUI (`:8188`) and the web backend (`:8000`).
2. `scripts/benchmark_amd.py` submits each workflow through the **real web API**
   (`POST /api/jobs`), exactly as the browser UI does.
3. The script polls `GET /api/jobs/{id}` until completion and computes wall
   time; exact GPU execution time is read from ComfyUI
   `/history/{prompt_id}` `execution_start` / `execution_success` timestamps.
4. `rocm-smi --showuse --showmeminfo vram --showtemp --showpower` is sampled
   every second while each workflow runs.

Run it yourself:

```bash
./ComfyUI/.venv/bin/python scripts/benchmark_amd.py --out deliverables/perf/benchmark.json
```

## 5. Measured results (single live run, 2026-08-06)

| Workflow | Configuration | GPU execution | End-to-end wall | GPU use (max/avg) | VRAM peak | Power peak | Temp max |
|----------|---------------|---------------|-----------------|-------------------|-----------|------------|----------|
| W1 concept art | SDXL 1024x1024, 25 steps, CFG 7 | **14.6 s** | 15.3 s | 100 / 52 % | 9.6 GB | 270 W | 39 °C |
| W2 depth map | MiDaS DPT-Hybrid, 512 | **1.1 s** | 7.7 s | 93 / 22 % | 12.2 GB | 115 W | 36 °C |
| W3 PBR set | 4 maps from depth, strength 2.0 | **1.0 s** | 1.6 s | 50 / 25 % | 12.2 GB | 57 W | 33 °C |
| W4 background music | MusicGen-small, 8 s, seed 777 | **9.6 s** | 10.7 s | 100 / 69 % | 12.6 GB | 124 W | 36 °C |
| W5 ambient SFX | glass clink, 4 s | **0.04 s** | 1.5 s | 0 / 0 % | 12.4 GB | 63 W | 34 °C |
| W6 sprite sheet | 8 frames, SDXL 512x512, 20 steps, ControlNet | **20.9 s** | 21.3 s | 100 / 91 % | 21.7 GB | 271 W | 49 °C |

Interpretation:

- W1 produces a 1024x1024 concept image in **≈ 15 s** end-to-end, i.e.
  **~1.7 images/minute**, and W6 produces an **8-frame engine-ready sprite
  atlas in ≈ 21 s (~2.6 s/frame)** — interactive enough for iteration.
- The whole W1..W6 demo chain (one concept, one depth, one material set, one
  music track, one SFX, one 8-frame atlas) completed in **≈ 57 s of GPU
  execution time**.
- Peak VRAM across the chain is 21.7 GB (W6), well within a 24 GB card such as
  the RX 7900 XTX; with `--lowvram`/model offloading even 8-16 GB Radeon cards
  can run the chain.
- The GPU is genuinely exercised (100% utilization peaks, 270 W power draw),
  confirming native ROCm acceleration rather than CPU fallback.

## 6. ROCm-specific engineering notes

- **Wheel pinning**: all three install branches pin the exact matching wheel
  family, eliminating ABI/`libtorch_hip` errors.
- **VRAM headroom**: SDXL (6.5 GB checkpoint) + ControlNet (4.7 GB) + VAE peak
  at ~21.7 GB; the MusicGen and translation models are loaded lazily and
  released after use, so W1-W7 can share one card.
- **Determinism**: seeds are fixed per job and logged with prompts in SQLite;
  ROCm and CUDA paths use the same scheduler parameters, so outputs are
  reproducible across machines.
- **Diagnostics**: `rocm-smi` sampling is built into the benchmark script, and
  `ComfyUI/system_stats` exposes the native device name for verification.
- **Fallback**: if no `/dev/kfd` is present the stack runs on CPU, so the same
  repo works on cloud VMs without a GPU (slower, but complete).
