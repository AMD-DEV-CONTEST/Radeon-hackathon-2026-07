# Submission — Candy Sticker Generator

> 中文版：[README.zh.md](README.zh.md)

> **Track 1 · Development of Multimodal Content Creation Tools** ·
> AMD AI DevMaster Hackathon 2026

This `submission/` directory is the consolidated judging package for **Candy Sticker Generator**
(糖果番剧Q版贴纸生成器). The full source tree lives at `../src/`; this folder contains everything
a reviewer needs to **read, run, and verify** the project — written strictly against the **real
functional architecture** (no fabricated features).

## Real Functional Architecture (verified in code)

| Mode | Path | Evidence |
|---|---|---|
| **Text → sticker set** | Type a character description → SDXL Animagine XL 4.0 (with self-trained `stkstyle` LoRA) → 8 expressions → flood-fill background removal → EDT die-cut border → 2×4 sheet + ZIP (WeChat 500 / Telegram 512 / print 300dpi+bleed) | `../src/webui/gradio_app.py` (mode=`文字`) |
| **Image → sticker set** (the "图生图" path) | Upload reference image or sketch → **Qwen2.5-VL-3B-Instruct** parses character description → fills prompt box → same SDXL pipeline as text mode | `../src/multimodal/img2prompt.py` (mode=`参考图`/`草图`) |
| **Style LoRA** | Self-trained `stkstyle` LoRA adapter (animagine-xl-4.0 base, rank 32, 2000 steps); weights ship with the repo; training loss curve in evidence | `../src/lora/models/stkstyle_lora_diffusers/` + `docs/evidence_gpu/fig_lora_training.png` |

**Explicitly NOT in scope (removed):** live / animated sticker generation — the LTX-Video prototype
was abandoned after ROCm compatibility issues, and is **not** part of the submission.

## Contents

```
submission/
├── README.md                          ← this file (English)
├── README.zh.md                       ← 中文版
└── docs/
    ├── Project_Profile.md / .pdf      ← 5-element profile (overview / stack / innovation / AMD / results)
    ├── presentation.pptx              ← demo slides (incl. LoRA on AMD ROCm + GPU evidence)
    └── evidence_gpu/                  ← AMD Radeon GPU evidence (see below)

```

## Running the project

```bash
pip install -r ../requirements.txt
python ../src/webui/gradio_app.py --port 7860
# open http://localhost:7860
```

Models are downloaded separately — see `../MODELS.md`. The `stkstyle` LoRA ships inside the
repository (`../src/lora/models/stkstyle_lora_diffusers/`) so no extra download is required for it.

## Scoring map (where each scoring point lives)

| Scoring dimension | Location in this package |
|---|---|
| Complete end-to-end workflow (40) | `../src/webui/gradio_app.py` + `../src/generation/` + `../demo_output/` (8 stickers) |
| Image-to-image / multimodal loop | `../src/multimodal/img2prompt.py` (Qwen-VL on AMD) |
| Style LoRA on AMD ROCm (training + inference) | `../src/lora/models/stkstyle_lora_diffusers/` + `docs/evidence_gpu/fig_lora_training.png` |
| Real-world value (20) — print, WeChat, Telegram export | `../src/generation/make_sheet_export.py` |
| AMD ROCm compliance (all GPU workloads on Radeon) | `docs/evidence_gpu/` (four charts + device snapshot) |
| Diversity | 8 emotion expressions + custom character + self-trained style |

## AMD ROCm evidence (`docs/evidence_gpu/`)

All GPU evidence was **re-generated today** on the same AMD Radeon (Navi 31, gfx1100, 48 GB, ROCm
7.2) that runs the demo. `rocm-smi --showuse` and sysfs `gpu_busy_percent` both report the GFX
(graphics) engine and read 0 % for UNet compute on RDNA3, so the sampler records **board power
draw (W)** via `rocm-smi --showpower` instead: idle ≈ 16 W, jumping to 200–300 W during inference
is the unambiguous proof that the Radeon GPU is doing the work.

| File | What it proves |
|---|---|
| `fig_sdxl_gpu.png` | SDXL sticker generation — board power jumps to 200–300 W during 3 generations, VRAM ramps to ~10 GB |
| `fig_img2prompt_gpu.png` | **Image-to-prompt (Qwen2.5-VL-3B)** — board power sustained ~150–200 W during the 图生图 multimodal leg |
| `fig_lora_training.png` | `stkstyle` LoRA training — loss curve + per-step time over the full 2000-step run (from `train.log`) |
| `fig_overview.png` | All three ROCm workloads compared on the same AMD Radeon |
| `device_info.txt` | Hardware snapshot (Navi 31, 48 GB, ROCm-smi, torch) |
| `gpu_evidence.json` | Raw **board-power(W) + VRAM** time-series (machine-readable) |