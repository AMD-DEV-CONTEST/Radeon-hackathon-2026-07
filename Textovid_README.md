# Textovid — AI Comic Studio

> **AMD AI DevMaster Hackathon 2026 — Track 1: Multimodal Content Creation Tools**

Textovid is a multimodal AI application that generates **unique, original comic books** from text prompts or category selections. It combines large language model storytelling with AI image generation, assembling full comic pages with speech bubbles, narration, sound effects, and a professional title page — all accelerated on AMD Radeon GPUs via ROCm.

## Key Features

- **Dual Input Modes**: Free-text story prompts OR category-based generation (genre, art style, mood, theme)
- **Uniqueness Engine**: Every comic is structurally distinct — randomized plot structures, character traits, setting mashups, and plot twists ensure no two outputs are alike. SHA-256 fingerprint proves uniqueness.
- **Multimodal Pipeline**: Text (LLM) -> Images (Stable Diffusion XL) -> Comic Pages (automated layout)
- **High-Resolution Generation**: Single-pass SDXL inference at 2048x2880px for near-4K panel artwork
- **4K Comic Pages**: 2480x3508px output with title/cover page, speech bubbles, narration boxes, SFX text
- **AMD ROCm Optimization**: Float16 inference, attention slicing, memory-efficient GPU utilization
- **Sci-Fi UI**: Cyberpunk-themed Gradio 6.x interface with animated grid, neon accents, and HUD elements
- **Built-in Benchmark**: One-click GPU performance measurement for the 20-point optimization score
- **Video Panel Animation**: LTX Video integration planned as a future enhancement (code scaffold in place)

## Architecture

```
User Input (text or categories)
    |
+-------------------------------------+
|  Uniqueness Engine                  |  <- CPU (randomization)
|  Plot/character/setting/twist gen   |
+---------------------+---------------+
                      |
+-------------------------------------+
|  Story Engine (Qwen LLM via API)   |  <- Zero GPU cost (free API)
|  Generates structured comic script  |
+---------------------+---------------+
                      |
+-------------------------------------+
|  Image Engine (SDXL on ROCm)       |  <- AMD Radeon GPU
|  Single-pass: 2048x2880px (Hi-Res) |
+---------------------+---------------+
                      |
+-------------------------------------+
|  Comic Layout Engine (CPU/PIL)     |  <- Pillow
|  Title page + panel composition     |
|  Speech bubbles, narration, SFX    |
+---------------------+---------------+
                      |
                4K Comic Pages (PNG)
```

## Quick Start on Radeon Cloud

### Prerequisites
- AMD Radeon GPU instance on Radeon Cloud (tested on Radeon RX 7900 XTX, 51.52 GB VRAM)
- Python 3.10+ (tested on Python 3.12)
- ROCm 7.2+
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
# Install PyTorch ROCm 7.2
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.2

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

### Sharing the Gradio UI (if needed)

On some cloud platforms, the Gradio `share=True` tunnel may fail to download `frpc` automatically. In that case:

1. Download the Linux amd64 `frpc` binary from [HuggingFace CDN](https://cdn-media.huggingface.co/frpc-gradio-0.3/frpc_linux_amd64)
2. Place it at `~/.cache/huggingface/gradio/frpc/frpc_linux_amd64_v0.3`
3. Make it executable: `chmod +x ~/.cache/huggingface/gradio/frpc/frpc_linux_amd64_v0.3`
4. Restart the app — it will now generate a `*.gradio.live` public URL

## Usage

1. Open the Textovid URL (typically `http://0.0.0.0:7860`)
2. **Text Mode**: Type a story premise and click Generate
3. **Category Mode**: Select genre, sub-genre, art style, theme, mood, and length
4. For best results, keep **High-Res Fix** enabled (generates at 2048px for sharper panels)
5. Use **Short (3 pages)** for testing — only 12 panels
6. Include quoted dialogue in your story for speech bubbles: `"I will save this city!"`
7. Add color keywords to prompts for vibrant output: `vibrant colors, full color illustration`
8. Run the **GPU Benchmark** to capture performance metrics for your submission

## AMD Radeon GPU / ROCm Optimizations

| Optimization | Description |
|-------------|-------------|
| PyTorch ROCm 7.2 Backend | All tensor ops via HIP/ROCm 7.2 |
| Float16 Inference | 2x speedup, 50% VRAM reduction vs FP32 |
| Attention Slicing | Reduces peak VRAM usage during generation |
| Single-Pass Hi-Res | Direct 2048x2880px generation (no refiner needed) |
| GPU Benchmarking | Built-in timing + VRAM measurement |
| Gradio 6.x | Modern UI framework with share link support |

## Project Structure

```
textovid/
+-- app.py              # Main Gradio application + pipeline
+-- config.py           # Configuration and constants
+-- story_engine.py     # LLM story generation (free Qwen API)
+-- image_engine.py     # SDXL single-pass image generation (GPU)
+-- video_engine.py     # LTX Video panel animation (future enhancement)
+-- comic_layout.py     # Comic page composition (CPU/PIL)
+-- uniqueness.py       # Randomization engine for unique content
+-- gpu_utils.py        # GPU detection and benchmarking
+-- style.css           # Sci-fi UI theme
+-- install.sh          # Quick install script
+-- deploy_notebook.py  # JupyterLab one-paste deployer
+-- requirements.txt    # Python dependencies
+-- README.md           # This file
+-- output/             # Generated comics (auto-created)
```

## Technical Notes

### Why Single-Pass SDXL (No Refiner)

The original design used a two-pipeline approach (SDXL Base + SDXL Refiner) for high-resolution output. However, `diffusers` 0.32+ removed `StableDiffusionXLRefinerPipeline`. The image engine was rewritten to use a single SDXL Base pipeline generating directly at 2048x2880px, which produces comparable quality with simpler code and fewer failure points.

### Compatibility

- **GPU**: AMD Radeon RX 7900 XTX (51.52 GB VRAM reported on Radeon Cloud)
- **ROCm**: 7.2
- **PyTorch**: 2.11.0+rocm7.2
- **diffusers**: 0.32+
- **Gradio**: 6.20.0 (theme/css must be in `launch()`, not `Blocks()`)
- **Python**: 3.12

## Submission

- **Track**: Track 1 — Development of Multimodal Content Creation Tools
- **Hackathon**: AMD AI DevMaster Hackathon 2026 (July 15 - Aug 6)
- **Prize**: $30,000 USD

## License

MIT
