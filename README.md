# FrameForge - AI Video Keyframe Editor

> **Event**: AMD AI DevMaster Hackathon 2026 · Track 1: Multimodal Content Creation Tools
> **Hardware**: AMD Radeon GPU 48GB + ROCm 6.3 Software Stack
> **Author**: Zhao Yuzhe (赵毓哲)

Edit videos like editing photos - **Generate, Select Frame, Select Region, Repaint, Propagate, Export**.

After generating a video, users can select any frame, choose regions to modify by clicking on auto-detected areas, enter a prompt for local repaint, and the system automatically propagates edits to adjacent frames while maintaining temporal consistency.

---

## Key Features

- **Dual-Backend Video Generation**:
  - **Wan2.1 Image-to-Video (14B)**: Text prompt + reference image -> 4-6s video
  - **MiniMax H3**: High-quality generation with instruction-guided editing, 864x480 resolution, native audio
- **Contour Region Selection (replaces brush painting)**: Canny edge detection + connected component analysis auto-segments frames into numbered regions. Users click to select and generate precise masks - no manual painting required
- **Color Annotation Visualization**: Detected regions overlaid with semi-transparent colors and numbered labels. Selected regions highlighted. Multi-selection supported
- **Frame-Level Local Repaint**: SDXL Inpainting / H3 instruction-guided edit + ControlNet (Canny/Depth) in selected regions
- **Flexible Propagation Modes**:
  - **Current frame only**: Modify only the selected frame
  - **Forward propagation**: Edit one frame, subsequent frames auto-follow
  - **Bidirectional propagation**: Both forward and backward frames follow (RAFT optical flow warp + feathered blending)
- **Sampling Steps Control**: UI slider to adjust 5-50 steps. More steps = finer quality (H3 recommended 15-30, Wan2.1 recommended 20-40)
- **Bilingual UI**: Chinese / English language switcher
- **Session Persistence**: Auto-restore UI state after network reconnection
- **One-Click Export**: FFmpeg frame composition, optional original audio track

## System Architecture

```
Gradio Web UI --HTTP--> FrameForge Orchestrator (Python)
                          |-- Video Generator    --|
                          |-- Frame Editor       --|-- ComfyUI Inference Backend (ROCm)
                          |-- Edit Propagator    --|   Wan2.1 | MiniMax H3 | SDXL-Inpaint | ControlNet
                          +-- Video Composer    ---> FFmpeg + OpenCV
```

| Module | Technology |
|--------|-----------|
| Video Generation | Wan2.1 Image-to-Video 14B + MiniMax H3 (INT8 pruned) |
| Frame Repaint | SDXL Inpainting + H3 instruction-guided edit |
| Structure Control | ControlNet (Canny + Depth) |
| Region Extraction | Canny edge + morphological closing + connected components (OpenCV) |
| Optical Flow | RAFT (torchvision built-in) |
| Inference Backend | ComfyUI v0.30+ |
| Frontend | Gradio 6.x |
| Video Processing | FFmpeg + OpenCV |

## Directory Structure

```
FrameForge/
├── app.py                  # Gradio main entry
├── config.py               # Global config + backend workflow mapping
├── requirements.txt
├── core/                   # Core business logic
│   ├── video_generator.py  # Video generation (Wan2.1 + H3)
│   ├── frame_editor.py     # Frame editing (SDXL + H3 edit)
│   ├── edit_propagator.py  # Edit propagation (RAFT, supports forward/backward/bidirectional)
│   ├── video_composer.py   # Video composition & export
│   └── frame_utils.py      # Frame path management
├── backend/                # ComfyUI backend interaction
│   ├── comfyui_client.py   # ComfyUI API client (WebSocket progress)
│   └── workflows/          # Workflow templates (JSON)
├── ui/                     # Gradio interface
│   ├── components.py       # UI components (dual-image layout + region annotation + i18n)
│   ├── handlers.py         # Event handlers (generate/select/click/edit/propagate)
│   └── i18n.py             # Bilingual strings (zh/en)
├── utils/                  # Utility functions
│   ├── gpu_monitor.py      # GPU status monitor
│   ├── image_utils.py      # Contour extraction + region coloring + mask generation
│   └── video_utils.py      # Frame I/O + video split/compose
├── docs/                   # Documentation
│   ├── demo-assets/        # Demo video
│   ├── demo_script.md      # Demo recording script
│   ├── presentation.html   # Auto-play presentation slides
│   └── project_brief.html  # Project brief (print to PDF)
└── tests/
```

## Environment Setup (ROCm)

### Prerequisites

- AMD Radeon GPU (gfx1100 or compatible)
- ROCm 6.3+
- Python 3.10+
- Conda

### Installation

```bash
# 1. Create conda environment
conda create -n frameforge python=3.10 -y
conda activate frameforge

# 2. Install ROCm PyTorch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.3

# 3. Verify GPU
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# 4. Install ComfyUI
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI && pip install -r requirements.txt

# 5. Install FrameForge dependencies
cd ../FrameForge
pip install -r requirements.txt

# 6. Download models (see docs/rocm_setup.md)
#    Wan2.1 i2v 14B       -> ComfyUI/models/diffusion_models/
#    MiniMax H3 DiT       -> ComfyUI/models/diffusion_models/
#    MiniMax H3 Text Enc  -> ComfyUI/models/text_encoders/
#    MiniMax H3 Video VAE -> ComfyUI/models/vae/
#    SDXL Inpainting      -> ComfyUI/models/checkpoints/
#    ControlNet           -> ComfyUI/models/controlnet/
#    RAFT                  -> FrameForge/models/raft-things.pth

# 7. Start ComfyUI backend
cd ../ComfyUI && python main.py --listen 0.0.0.0 --port 8188

# 8. Start FrameForge
cd ../FrameForge && python app.py
```

## Usage Workflow

1. **Generate**: Enter prompt + upload reference image (optional) + select model (Wan2.1 / MiniMax H3) + adjust sampling steps -> Click "Generate Video"
2. **Select Frame**: Drag the timeline slider or click thumbnails to choose a keyframe
3. **Select Region**: System auto-extracts contours and displays a color-annotated region map -> Click regions to modify (multi-select supported)
4. **Edit**: Enter edit prompt -> Select propagation mode (current only / forward / bidirectional) -> Click "Apply Edit"
5. **Propagate**: System automatically propagates edits to adjacent frames
6. **Compare**: Side-by-side before/after comparison
7. **Export**: Click "Export Video" when satisfied

### Sampling Steps Guide

| Model | Quick Preview | Recommended | High Quality |
|-------|--------------|-------------|--------------|
| MiniMax H3 | 5 steps (~1min) | 15 steps (~8min) | 30 steps (~35min) |
| Wan2.1 | 10 steps | 20 steps | 40 steps |

> Note: More steps = finer quality, but generation time increases linearly. H3 frame count auto-expands based on step alignment.

## AMD Radeon GPU / ROCm Adaptation

- **GPU**: AMD Radeon 48GB (gfx1100)
- **ROCm**: 6.3 | **PyTorch**: 2.6.0+rocm6.3
- GPU utilization: 95-100% during inference, VRAM usage: ~99%
- H3 INT8 quantization fits 48GB VRAM single-card loading
- All inference runs locally on AMD Radeon GPU - no remote APIs

## Performance Data

| Steps | Frames | Duration | Generation Time | Use Case |
|-------|--------|----------|-----------------|----------|
| 5 | 5 | ~0.2s | ~1 min | Quick preview |
| 15 | 39 | ~1.6s | ~8 min | Recommended quality |
| 30 | 124 | ~5.2s | ~35 min | High quality |

## Submission Materials

| Deliverable | Location |
|-------------|----------|
| Project Brief (PDF) | `docs/project_brief.html` -> Print to PDF |
| Source Code | This repository |
| README | This file |
| Demo Video | `docs/demo-assets/demo_video.mp4` |
| Presentation | `docs/presentation.html` |
| Demo Script | `docs/demo_script.md` |

## License

This project is an entry for the AMD AI DevMaster Hackathon 2026.
