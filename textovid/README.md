# Textovid — AI Comic Studio

> **AMD AI DevMaster Hackathon 2026 — Track 1: Multimodal Content Creation Tools**

Textovid is a multimodal AI application that generates **unique, original comic books** from text prompts or category selections. It combines large language model storytelling with AI image generation, assembling full comic pages with speech bubbles, narration, sound effects, and a professional title page — all accelerated on AMD Radeon GPUs via ROCm.

## 🎯 Key Features

- **Dual Input Modes**: Free-text story prompts OR category-based generation (genre, art style, mood, theme)
- **Uniqueness Engine**: Every comic is structurally distinct — randomized plot structures, character traits, setting mashups, and plot twists ensure no two outputs are alike. SHA-256 fingerprint proves uniqueness.
- **Multimodal Pipeline**: Text (LLM) → Images (Stable Diffusion XL + Refiner) → Comic Pages (automated layout)
- **High-Res Fix**: 2x refiner pass using SDXL Refiner for 4K-quality panel artwork
- **4K Comic Pages**: 2480×3508px output with title/cover page, speech bubbles, narration boxes, SFX text
- **Optional Video Panels**: LTX Video animation of comic panels (experimental)
- **AMD ROCm Optimization**: Float16 inference, Karras scheduler, memory-efficient attention
- **Sci-Fi UI**: Cyberpunk-themed Gradio interface with 4K video background, animated grid, neon accents, HUD elements
- **Built-in Benchmark**: One-click GPU performance measurement for the 20-point optimization score

## 🏗️ Architecture

```
User Input (text or categories)
    ↓
┌─────────────────────────────────────┐
│  Uniqueness Engine                  │  ← CPU (randomization)
│  Plot/character/setting/twist gen   │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│  Story Engine (Qwen LLM via API)   │  ← Zero GPU cost (free API)
│  Generates structured comic script  │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│  Image Engine (SDXL on ROCm)       │  ← AMD Radeon GPU
│  Base pass: 1024×1024              │
│  Refiner pass: 2048×2048 (4K)     │
└──────────────┬──────────────────────┘
               ↓
┌─────────────────────────────────────┐
│  Comic Layout Engine (CPU/PIL)     │  ← Pillow
│  Title page + panel composition     │
│  Speech bubbles, narration, SFX    │
└──────────────┬──────────────────────┘
               ↓
         4K Comic Pages (PNG)
```

## 🚀 Quick Start on Radeon Cloud

### Prerequisites
- AMD Radeon GPU instance on Radeon Cloud
- Python 3.10+
- Free API key from [Radeon Cloud Model APIs](https://developer.amd.com.cn/radeon/modelapis)

### Method 1: Shell Script (Recommended)

```bash
# 1. Upload textovid/ folder to /workspace/
# 2. Run the install script
cd /workspace/textovid && bash install.sh

# 3. Start the app
python app.py
```

### Method 2: Manual Install

```bash
# Install PyTorch ROCm
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2

# Install dependencies
pip install -r requirements.txt

# Run
cd /workspace/textovid && python app.py
```

### Getting Your API Key
1. Go to [developer.amd.com.cn/radeon/modelapis](https://developer.amd.com.cn/radeon/modelapis)
2. Click **Token Factory**
3. Generate a new token
4. Paste it into the Textovid UI or set `TEXTOVID_API_KEY` environment variable

## 🎮 Usage

1. Open the Textovid URL (typically `http://0.0.0.0:7860`)
2. **Text Mode**: Type a story premise and click Generate
3. **Category Mode**: Select genre, sub-genre, art style, theme, mood, and length
4. For best results, keep **High-Res Fix** enabled (slower but 4K quality)
5. Use **Short (3 pages)** for testing — only 12 panels
6. Run the **GPU Benchmark** to capture performance metrics for your submission

## 🖥️ AMD Radeon GPU / ROCm Optimizations

| Optimization | Description |
|-------------|-------------|
| PyTorch ROCm Backend | All tensor ops via HIP/ROCm |
| Float16 Inference | 2x speedup, 50% VRAM reduction |
| Karras Noise Schedule | Better quality in fewer steps |
| SDXL Refiner (Hi-Res Fix) | 2x upscale with denoising refinement |
| Memory-Efficient Attention | xformers when available |
| GPU Benchmarking | Built-in timing + VRAM measurement |

## 📁 Project Structure

```
textovid/
├── app.py              # Main Gradio application + pipeline
├── config.py           # Configuration and constants
├── story_engine.py     # LLM story generation (free Qwen API)
├── image_engine.py     # SDXL + Refiner image generation (GPU)
├── video_engine.py     # LTX Video panel animation (optional)
├── comic_layout.py     # Comic page composition (CPU/PIL)
├── uniqueness.py       # Randomization engine for unique content
├── gpu_utils.py        # GPU detection and benchmarking
├── style.css           # Sci-fi UI theme
├── install.sh          # Quick install script
├── deploy_notebook.py  # JupyterLab one-paste deployer
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── output/             # Generated comics (auto-created)
```

## 📤 Submission

- **Track**: Track 1 — Development of Multimodal Content Creation Tools
- **Hackathon**: AMD AI DevMaster Hackathon 2026 (July 15 – Aug 6)

## 📄 License

MIT
