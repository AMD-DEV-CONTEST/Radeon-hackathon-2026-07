# Zivra Vision

**Multimodal AI Hackathon Submission — AMD AI DevMaster Hackathon 2026**

Zivra Vision is a text-to-image generation app built with SDXL-Turbo, delivering fast, high-quality image synthesis from natural language prompts through a simple, interactive web interface.

## Team
Zivra

## Track
Multimodal AI

## Overview
Zivra Vision takes a text prompt and generates a corresponding image in just a few inference steps, using the SDXL-Turbo model — optimized for speed without sacrificing visual quality. The app is built with a clean Gradio interface, making it accessible to anyone without needing to write code.

## Features
- Text-to-image generation using SDXL-Turbo
- Adjustable inference steps (1–8) for speed/quality trade-off
- Adjustable guidance scale for prompt adherence
- Simple, shareable web interface via Gradio
- Automatic GPU/CPU device detection — runs on AMD Radeon (ROCm) or CPU with no code changes

## Tech Stack
- Python
- PyTorch
- Hugging Face Diffusers (SDXL-Turbo)
- Hugging Face Transformers
- Gradio (UI)

## Setup
```bash
pip install -r requirements.txt
```

## Run
```bash
python app.py
```
This launches a local web interface and prints a shareable public link.

## Usage
1. Enter a text prompt describing the image you want (e.g. "a cyberpunk city at sunset, digital art")
2. Adjust inference steps and guidance scale if desired
3. Click **Generate**
4. View and download the generated image

## Hardware
Developed and demonstrated on CPU (local machine) due to GPU access setup issues during the hackathon window. The code is fully ROCm-compatible and will run unmodified on an AMD Radeon GPU with ROCm-enabled PyTorch — simply swap the CPU torch install in `requirements.txt` for the ROCm build:

```bash
pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
```

No other code changes are required; device selection is automatic (`torch.cuda.is_available()`).

## Future Improvements
- Add image-to-image and inpainting modes
- Batch generation support
- Prompt history and gallery view
- ROCm-optimized inference benchmarking
