# Textovid — Multimodal AI Comic Studio

**AMD AI DevMaster Hackathon 2026 — Track 1 ($30K Prize)**

> Turn any story idea into a full AI-generated comic page in minutes.
> Powered by **AMD ROCm 7.2**, **Radeon RX 7900 XTX**, **Stable Diffusion XL**,
> **LTX Video**, and **Qwen 35B LLM**.

---

## Features

- **AI Story Generation** — Qwen 35B LLM breaks your prompt into structured comic panels
- **SDXL + High-Res Fix** — Each panel generated at ~2048px using base + refiner pipeline
- **4K Comic Page Assembly** — Panels assembled into a print-ready 2480×3508px A4 page
- **Speech Bubbles & SFX** — Automatic overlay of dialogue, captions, and sound effects
- **Panel Animation** — Optional LTX Video animation for any panel
- **SHA-256 Fingerprinting** — Provable uniqueness for every generated panel
- **AMD ROCm Optimized** — Runs entirely on Radeon RX 7900 XTX (24GB VRAM)

## Architecture

```
User Prompt
     │
     ▼
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│ Story Engine │────▶│ Image Engine  │────▶│ Comic Layout   │
│ (Qwen 35B)   │     │ (SDXL+Refiner)│     │ (4K Assembly)  │
└─────────────┘     └──────────────┘     └───────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │ Output Gallery  │
                                          │ + Fingerprints  │
                                          └─────────────────┘
```

## Quick Start

```bash
# 1. Upload textovid.tar.gz to the instance
# 2. Extract to /workspace/textovid/
tar xzf textovid.tar.gz -C /workspace/textovid/

# 3. Run the installer
bash /workspace/textovid/install.sh

# 4. Launch
source /opt/venv/bin/activate
cd /workspace/textovid && python app.py
```

## Hardware Requirements

- **GPU**: AMD Radeon RX 7900 XTX (24 GB VRAM)
- **Driver**: ROCm 7.2+
- **RAM**: 32 GB minimum
- **Disk**: 50 GB free (model weights)

## Environment

- Python 3.11+ (venv at `/opt/venv/`)
- PyTorch 2.11.0+rocm7.2
- Gradio 6.20.0
- Diffusers 0.32.0

## File Structure

```
/workspace/textovid/
├── app.py              # Main Gradio web interface
├── config.py           # All configuration constants
├── story_engine.py     # LLM story panel generation
├── image_engine.py     # SDXL + Refiner image generation
├── video_engine.py     # LTX Video panel animation
├── comic_layout.py     # 4K page assembly, bubbles, SFX
├── uniqueness.py       # SHA-256 fingerprint engine
├── gpu_utils.py        # GPU/VRAM detection (PyTorch 2.11 compat)
├── style.css           # Custom dark theme
├── install.sh          # Dependency installation script
├── deploy_notebook.py  # Jupyter deployment helper
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── outputs/            # Generated images & pages
```

## License

MIT — Built for the AMD AI DevMaster Hackathon 2026
