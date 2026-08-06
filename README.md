# Candy Sticker Generator · Anime Chibi Q-version Sticker Generator

> 中文版：[README.zh.md](README.zh.md)
>
> A simple anime Q-version sticker generator built **entirely on the AMD Radeon + ROCm stack**
> (training + inference + post-processing + serving).
> In one line: feed in a reference image or an emotion keyword → get a complete set of stickers
> with white borders, transparent backgrounds, ready to print or publish.

---

## 1. Project Positioning

This is a **complete software project**, not a single script. It chains
"style-LoRA training → sticker base-image generation → background removal / white border / sheet
layout / export → multimodal image→text loop → WebUI serving → GPU benchmark proof" into a creative
pipeline that runs end-to-end on AMD ROCm.

Highlight: **both training and inference run entirely on AMD Radeon (ROCm)**, with built-in GPU
proof, fitting the "AMD adaptation" theme.

---

## 2. Overall Architecture (layered)

```
┌─────────────────────────────────────────────────────────────┐
│                      User entry points                       │
│   WebUI (src/webui/gradio_app.py)   ·   CLI (scripts/)       │
└───────────────┬───────────────────────────┬─────────────────┘
                │                           │
        ┌───────▼────────┐          ┌───────▼────────┐
        │ Multimodal loop │          │ Sticker pipeline│
        │ src/multimodal │          │ src/generation │
        │ img2prompt.py  │          │ sticker_pipeline│
        └───────┬────────┘          └───────┬────────┘
                │ image→text→image prompt    │
                └─────────────┬───────────────┘
                              ▼
                    ┌─────────────────────┐
                    │  SDXL + self-trained │  ← src/lora (trained on ROCm)
                    │  LoRA (stkstyle)     │     animagine-xl-4.0 base
                    └─────────┬───────────┘
                              ▼
        ┌─────────────────────────────────────────────┐
        │            Post-processing (src/generation)   │
        │  matting (bg removal) → border (EDT white) →  │
        │  sheet (layout) → export (ZIP/WeChat/TG/print)│
        └─────────────────────┬───────────────────────┘
                              ▼
                    demo_output/ (8-expression results)
                              ▼
              src/bench/gpu_benchmark.py  (ROCm proof)
```

---

## 3. Directory Structure

```
candy-sticker-generator/
├── README.md                  # this file: English overview & architecture (default)
├── README.zh.md               # Chinese overview & architecture (zh)
├── ARCHITECTURE.md            # module responsibilities, data flow, ROCm adaptation details
├── MODELS.md                  # model list & download commands (Animagine / Qwen-VL / LoRA)
├── requirements.txt           # Python dependencies (pip packages; not model weights)
├── src/                       # ★ all source code (split by responsibility)
│   ├── generation/            # core generation & post-processing
│   │   ├── sticker_pipeline.py        # SDXL+LoRA main generation
│   │   ├── matte_floodfill_batch.py   # floodfill background removal
│   │   ├── add_sticker_whiteborder.py # EDT white border expansion
│   │   ├── build_sheet.py             # sticker sheet layout
│   │   └── make_sheet_export.py       # export ZIP / WeChat / TG / print
│   ├── multimodal/            # multimodal image→text loop
│   │   └── img2prompt.py             # Qwen2.5-VL: image→prompt→reverse enhancement
│   ├── lora/                  # ★ LoRA 风格适配器（自训于 ROCm）
│   │   ├── README.md                 # LoRA 说明文档
│   │   └── models/stkstyle_lora_diffusers/  # 训练好的权重（~185MB, Git LFS）
│   └── webui/                 # serving layer
│       └── gradio_app.py             # Gradio WebUI (three modes + LoRA + print export)
├── scripts/                   # CLI entry points / ops
│   ├── run_one.py  run_8expr.py      # single / 8-expression batch generation
│   └── setup.sh                      # 环境安装脚本
├── demo_output/               # 8 finished expression stickers + contact sheet (demo)
└── submission/                # official submission package (English)
    ├── README.md  README.zh.md
    └── docs/
        ├── Project_Profile.md/.pdf       # official 5-element profile
        ├── presentation.pptx             # 10-page deck
        └── evidence_gpu/                 # 4 ROCm power/VRAM charts + gpu_evidence.json + device_info.txt
```

> **Single source of truth**: formal documents and GPU evidence live only under `submission/docs/`.
> No duplicate copy is kept at the project root, so the two can never drift apart.

---

## 4. Quick Start

### 4.1 Launch the WebUI (recommended for demo)

> **⚠️ Environment activation**: Project dependencies are installed in a venv. Activate the virtual environment before running:

```bash
# Create and activate venv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/webui/gradio_app.py --port 7860
```

> 🌐 Open http://localhost:7860 in a browser
> 
> ⚠️ Model weights are **not** installed by `requirements.txt`: first download the Animagine base
> and Qwen2.5-VL to `models/` per `MODELS.md` (in China set `HF_ENDPOINT=https://hf-mirror.com`).
> The self-trained `stkstyle` LoRA is bundled in the repo.
> 
> 💡 Add `--share` flag to get a temporary public Gradio URL.

### 4.2 Batch generation from CLI
```bash
python scripts/run_8expr.py          # generate the 8-expression sticker set
```

### 4.3 Multimodal prompt enhancement
```bash
python src/multimodal/img2prompt.py --image ref.png
```

---

## 5. Tech Stack

| Layer | Technology |
|---|---|
| Base model | SDXL (animagine-xl-4.0) + self-trained `stkstyle` LoRA |
| Training framework | Diffusers + PEFT (LoRA), ROCm 7.x |
| Post-processing | NumPy / Pillow / SciPy (floodfill bg removal + EDT white border) |
| Multimodal | Qwen2.5-VL (image→text prompt reverse) |
| Serving | Gradio |
| Hardware | AMD Radeon (ROCm), 48 GB VRAM |

---

## 6. Scoring Map

- **AMD ROCm adaptation**: training + inference + benchmark all on ROCm, with `submission/docs/evidence_gpu/` proof.
- **Complete workflow**: from training to generation to export to serving, end-to-end reproducible.
- **Real-world value**: export covers WeChat / Telegram / print specs, directly usable.
- **Diversity**: multiple expressions (8) + self-trained style LoRA, extensible to multiple characters.

See `ARCHITECTURE.md` and `submission/docs/Project_Profile.pdf` for more.
