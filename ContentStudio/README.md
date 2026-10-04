# Content Studio

> AI-Powered Multimodal Content Creation Tool Built on AMD Radeon GPU + ROCm
>
> 2026 AMD AI DevMaster Hackathon · Track 1: Multimodal Content Creation

## Overview

Content Studio is a web-based AI content creation tool that transforms photos + themes + text into ready-to-publish WeChat Official Account articles and Xiaohongshu (RedNote) posts — complete with AI-styled images, intelligent image placement, and direct draft-box publishing.

**Key differentiator:** The entire pipeline — text generation (LLM), image styling (img2img), and text-to-image — runs on **AMD Radeon GPU via ROCm**, addressing the four track evaluation pillars: inference acceleration, lightweight deployment, style customization, and image quality optimization.

## Features

| Feature | Description | Engine |
|---|---|---|
| **AI Article Writing** | Generates 1000+ word articles with structured sections, titles, summaries, and image captions | Qwen LLM (AMD GPU via Radeon Cloud) |
| **Photo Style Transfer** | 8 visual styles: anime, cyberpunk, watercolor, retro, minimal, oil painting, ink wash, pixel art — per-photo selection | ComfyUI img2img on ROCm (AMD GPU) |
| **Text-to-Image** | Generates brand-new illustrations based on article themes | ComfyUI txt2img on ROCm (AMD GPU) |
| **AI Cover Generation** | Creates 2.35:1 WeChat card covers matching the article theme | ComfyUI on ROCm |
| **Vision-Based Image Placement** | Vision model reads each photo's content (text, labels, scenes) and places it in the most relevant section | Vision LLM (AMD GPU) |
| **Direct Draft Publishing** | One-click publish to WeChat Official Account draft box via official API | WeChat API |
| **Article Templates** | Product review / Event promo / Tutorial / Industry analysis | LLM |
| **Editable Preview** | Edit text, drag images, regenerate — full control before publishing | FastAPI + Jinja2 |
| **Export** | Standalone HTML with embedded images / Print-to-PDF | — |
| **History** | All generated articles persisted, searchable, deletable | Disk + Memory |
| **Self-Diagnostic** | One-click health check for LLM / ComfyUI / WeChat connectivity | FastAPI |

## Architecture

```
User Web UI (FastAPI + Jinja2 + PyWebView)
  │
  ├── Text Generation ──→ Radeon Cloud API (AMD GPU)
  │                        ├── Free shared: Qwen3.6-35B-A3B
  │                        └── Dedicated vLLM: Qwen2.5-VL-7B-Instruct
  │
  ├── Image Generation ──→ ComfyUI on ROCm (AMD GPU)
  │                        ├── Style Transfer (img2img, DreamShaper 8)
  │                        └── Text-to-Image (txt2img)
  │
  ├── Vision Understanding → Vision model reads photos → logical image placement
  │
  └── Publishing ────────→ WeChat Official Account /draft/add API
```

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn
- **Frontend:** Server-rendered HTML (Jinja2), vanilla JS, SSE (Server-Sent Events)
- **Desktop:** PyWebView (native window, no browser dependency)
- **LLM:** OpenAI-compatible client (Radeon Cloud Qwen / GLM / DeepSeek / Kimi)
- **Image:** ComfyUI (ROCm 6.2), Pillow, OpenCV, pillow-heif (HEIC support)
- **OCR:** PaddleOCR (optional)
- **Publishing:** WeChat Official Account API
- **Testing:** pytest (92 tests)

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run (Web)

```bash
python -m content_studio.web.app
# Open http://127.0.0.1:8000
```

### 3. Run (Desktop App)

```bash
python desktop_app.py
```

Or double-click `run_web.bat` / desktop shortcut.

### 4. Configure

Open Settings (gear icon) and fill in:
- **LLM Provider:** Select `radeon` → Get API Key from [Token Factory](https://developer.amd.com.cn/radeon/modelapis)
- **ComfyUI:** Set Base URL (default `http://127.0.0.1:8188`) if deployed
- **WeChat:** Enter AppID / AppSecret (verified account required)

## AMD Radeon GPU + ROCm Integration

### Track Evaluation Pillars

| Pillar | Implementation |
|---|---|
| **Inference Acceleration** | Dedicated vLLM instance on Radeon Cloud (exclusive GPU, no queue); per-stage timing displayed in UI |
| **Lightweight Deployment** | Single Python process; deferred imports (startup ~1.4s); INT4 quantization-ready; desktop or server |
| **Style Customization** | 8 preset styles driving ComfyUI workflows + LLM writing tone + t2i prompts; customizable workflows |
| **Image Quality** | Auto-cropping (2.35:1 covers, 3:4 portraits), width-limited compression, watermarks, captions, AI covers |

### Deployment Paths

**Path 1: Free Shared API (text only)**
- Radeon Cloud provides a free OpenAI-compatible endpoint running Qwen/DeepSeek on AMD GPU
- No instance needed, no quota consumed
- Base URL: `https://developer.amd.com.cn/radeon/api/v1`

**Path 2: Dedicated vLLM Instance (text + vision)**
- Create a vLLM Model API template on Radeon Cloud
- Serve command: `vllm serve Qwen/Qwen2.5-VL-7B-Instruct --host 0.0.0.0 --port 8000`
- Get dedicated Base URL + API Key from instance details

**Path 3: ComfyUI on ROCm (image styling)**
- Launch a JupyterLab instance on Radeon Cloud
- Run the one-click setup script: `bash scripts/setup_comfyui_rocm.sh`
- Pre-built workflows (DreamShaper 8, img2img + txt2img) included
- Connect via SSH tunnel or Cloudflare tunnel

See [`docs/ROCm_Migration_Guide.md`](docs/ROCm_Migration_Guide.md) for complete details.

## Project Structure

```
content_studio/
├── core/                   # Core logic (no UI dependencies)
│   ├── models.py           # LLM client (OpenAI-compatible, vision, auto-fallback)
│   ├── prompts.py          # WeChat / Xiaohongshu prompt construction
│   ├── generator.py        # Generation orchestration + JSON parsing + fallback
│   ├── pipeline.py         # End-to-end pipeline + image weaving
│   ├── image_pipeline.py   # Image processing (crop/watermark/compress/HEIC)
│   ├── comfy.py            # ComfyUI HTTP client (workflow injection + polling)
│   └── ocr.py              # PaddleOCR wrapper (optional)
├── publish/                # Publishing layer
│   └── wechat.py           # WeChat draft box API (token/upload/draft)
├── styles/                 # Style presets
│   ├── registry.py         # Style registry + workflow loader
│   └── workflows/          # ComfyUI workflow JSON templates
├── web/                    # Web layer (FastAPI)
│   ├── app.py              # FastAPI entry point
│   ├── routes.py           # All routes (generate/preview/publish/history/export/SSE)
│   ├── jobs.py             # In-memory + disk-persisted job store
│   └── templates/          # Jinja2 templates
├── config.py               # Configuration load/persist
├── desktop_app.py          # PyWebView desktop entry
└── tests/                  # 92 pytest tests
```

## Testing

```bash
python -m pytest -q
# 92 passed
```

## License

MIT
