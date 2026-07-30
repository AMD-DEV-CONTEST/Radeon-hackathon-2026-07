# AMD-Optimized-Qwen-VL-PartialInpainting
## AMD Optimized Partial Inpainting WebUI

> Open-source local image partial re-drawing tool based on ComfyUI workflow + Gradio, optimized exclusively for AMD ROCm GPU.
> only modify masked area while keeping the rest of the original image completely unchanged. One-click deployment, out-of-box usage.

## Table of Contents
- [Project Overview](#project-overview)
- [Key Features & Performance Optimization](#key-features--performance-optimization)
- [Hardware & Software Requirements](#hardware--software-requirements)
- [Project Structure](#project-structure)
- [Quick Start Guide](#quick-start-guide)
- [User Operation Tutorial](#user-operation-tutorial)
- [Function Modes Introduction](#4-built-in-function-modes)
- [Advanced Parameter Explanation](#advanced-parameter-explanation)
- [License](#license)

---

## Project Overview
This project integrates **Qwen-Image-Edit 2511**, RMBG background removal, wrapped into an independent Gradio WebUI based on ComfyUI backend.
Common application scenarios: stylized local redrawing, clothing replacement, text-guided local generation, object erasure.
Fully optimized memory allocation strategy for AMD Radeon GPU, solved video memory fragmentation issue, reduced VRAM occupation by 40% compared with original model, and accelerated average inference speed from 85s to 25s.

## Key Features & Performance Optimization
### ⚡ Performance Upgrade
- Original average inference time: 85s | Optimized average inference time: 25s
- FP8 model quantization cuts base VRAM usage by 40%
- Lightning LoRA reduces sampling steps to 4 without obvious quality loss

### 🧠 AMD VRAM Optimization (Core Advantage)
- Custom ROCm memory allocation environment variables to avoid VRAM fragmentation
- Preload all models on first warm-up run, no repeated model loading during subsequent inference
- Strict model cache limit, automatic tensor & garbage collection after each generation
- Stable runtime VRAM: Idle ~30GB, peak inference ~36GB, fully compatible with AMD 48GB GPU

### 🎨 Image Editing Capabilities
- Mask expansion & blur node for natural edge fusion between modified & original area
- Auto crop masked region to minimize re-drawing area, balance speed & picture quality
- Auto switch reference feature injection logic: disable ref mode when no reference image uploaded to avoid ghost artifacts

### 🖥 Deployment & Experience
- Pure one-click installation script, auto pull ComfyUI, install dependencies & move model files
- Mobile & desktop responsive Gradio WebUI
- Independent tunnel script for one-click intranet penetration for remote access
- Auto manage ComfyUI backend execution, no manual workflow operation required

## Hardware & Software Requirements
### Minimum & Recommended Specs
| Component | Minimum Requirement | Recommended Configuration |
|-----------|--------------------|-----------------------|
| AMD GPU VRAM | 48GB (ROCm Enabled) | 48GB+ AMD Radeon GPU |
| System RAM | 32GB | 64GB |
| Storage | 60GB | 100GB |
| Python Version | 3.10 | 3.12 |

> Tested Data: Single inference only consumes ~36GB VRAM; all models can be fully cached within 48GB total video memory.

## Project Structure
```
AMD-Optimized-Qwen-VL-PartialInpainting/
├── Radeon-Cloud-User Guide/              # hackathon def
├── docs/          # Project Introduction Document
├── images/             # Test image collection
├── app.py              # Main service entry
├── install.sh          # One-click environment deployment script
├── tunnel.sh           # Intranet penetration script for remote access
├── workflow.json       # Encapsulated ComfyUI full workflow template
└── README.md           # Project documentation
```

## Quick Start Guide
### 1. Clone Repository
```bash
git clone http://github.com/gao-jie-ai/Track-1-gaojie-AMD-Optimized-Qwen-VL-PartialInpainting.git
cd Track-1-gaojie-AMD-Optimized-Qwen-VL-PartialInpainting
```

### 2. One-Click Environment Installation
```bash
chmod +x install.sh
./install.sh
```
Script function list:
1. Create isolated Python virtual environment
2. Auto download ComfyUI core files
3. Install all PyTorch ROCm, ComfyUI custom node dependencies
4. Auto download all required model weights
5. Automatically move model files to ComfyUI standard model directory

### 3. Launch Local Editing WebUI
```bash
source /workspace/comfyuipy/bin/activate
python app.py
```
Default access address: http://127.0.0.1:7860
All devices in LAN can access via your host IP: `http://[Your-IP]:7860`

### 4. Remote Access (Intranet Penetration)
Open a new window
```bash
chmod +x tunnel.sh
./tunnel.sh
```
After execution, public network link will be output for external device access.

## User Operation Tutorial
### Standard Operation Flow
```
① Upload Source Image → ② Generate Mask (SAM Auto / Manual Brush) → ③ Upload Reference Image (Optional)
→ Select built-in prompt template / Custom edit instruction → Adjust advanced parameters → Click Generate → View comparison result
```
1. Upload your original image to the left upload box
2. Mask generation: Use white brush to paint target area directly
3. Upload reference image (required for swap mode; skip for erase mode)
4. Fill edit prompt or click one-click template button
5. Tune advanced parameters (default values work for most scenarios)
6. Click `Start Generate` button

## 4 template
| Mode | Source Image | Mask Required | Reference Image | Usage Scenario |
|------|:------------:|:-------------:|:---------------:|----------------|
| 🔄 Style-based partial redrawing | ✅ | ✅ | ✅ | Optional  Replace the masked area with a certain artistic style (such as oil painting, watercolor, cyberpunk) |
| 👗 Garment Replacement | ✅ | ✅ | ✅ | Change clothes, dresses, suits of characters |
| 💇 Text-guided partial generation | ✅ | ✅ | ❌ | Generate content in the masked area based on the text description (text-to-mask-inpainting) |
| 🧹 Object Erase | ✅ | ✅ | ❌ | Remove redundant objects, stains, text from image |

> Core logic: If no reference image is uploaded, the system automatically closes reference feature injection (`to_ref=False`) to avoid white placeholder ghost artifacts.

## Advanced Parameter Explanation
| Parameter | Default | Value Range | Detailed Description |
|-----------|---------|-------------|----------------------|
| Random Seed | -1 | -1 ~ 2⁶³-1 | -1 = fully random every run; fixed seed for reproducible output |
| Sampling Steps | 4 | 1 ~ 20 | Lightning LoRA only needs 4 steps; higher steps bring richer details but slower speed |
| CFG Scale | 2.0 | 0.5 ~ 6.0 | Prompt guidance strength; higher value makes result strictly follow edit text |
| Denoising Strength | 0.75 | 0.0 ~ 0.95 | Control modification intensity; higher = larger change to masked area; lower = keep original texture |
| Mask Expand Pixels | 35 | 0 ~ 200 | Expand mask boundary outward for smoother transition between edited & original image |
| Mask Blur Radius | 10 | 0 ~ 100 | Edge feather strength of mask; larger value eliminates hard boundary lines |


## License
MIT License
Free for personal & commercial secondary development, please retain original project author & model source citation.
