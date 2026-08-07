# Indic Heritage Studio v2

**A multimodal content creation tool that reimagines modern photos and prompts through the lens of 5 authentic Indian heritage art forms — running on SDXL + Stable Video Diffusion + ControlNet + per-style LoRAs.**

> **AMD AI DevMaster Hackathon 2026 - Track 1: Multimodal AI Content Creation**
> **Team:** TeamIndicForge

## Full Project Repository

**All code, models, datasets, and deliverables are hosted on HuggingFace:**

### https://huggingface.co/Dev2506/indic-heritage-studio

The HuggingFace repo contains:
- Complete source code (45 Python files)
- 5 trained LoRA weights (assets/loras/*.safetensors, ~460 MB total)
- Project Profile PDF (Project_Profile.pdf)
- PPT (Indic_Heritage_Studio_PPT.pptx)
- 200-image training dataset (assets/datasets/)
- 45 demo images (examples/1_text_to_image/)
- Benchmark reports (outputs/benchmarks/)

## Deliverables (Track 1 Requirements)

| Deliverable | Location | Status |
|---|---|---|
| Project Profile PDF | [Project_Profile.pdf](https://huggingface.co/Dev2506/indic-heritage-studio/blob/main/Project_Profile.pdf) | Complete |
| Source Code | [HuggingFace repo](https://huggingface.co/Dev2506/indic-heritage-studio/tree/main) | 45 Python files |
| PPT / Poster | [Indic_Heritage_Studio_PPT.pptx](https://huggingface.co/Dev2506/indic-heritage-studio/blob/main/Indic_Heritage_Studio_PPT.pptx) | 10 slides |
| Demo Video | Adding before Aug 5 - AMD Radeon Cloud recording | Pending |
| 5 Trained LoRAs | [assets/loras/](https://huggingface.co/Dev2506/indic-heritage-studio/tree/main/assets/loras) | Rank 32, 800 steps each |

## Benchmark Results

Tested on 8 x NVIDIA A100-SXM4-80GB (680 GB VRAM):

| Pipeline | Latency | Throughput | Peak VRAM |
|---|---|---|---|
| T2I (SDXL + LoRA) | 5.19 sec/image | 11.6 img/min | 11.33 GB |
| SVD-XT 1.1 (25-frame video) | 40.52 sec/video | 1.5 videos/min | 14.31 GB |

LoRA Training Results (5 LoRAs trained in parallel, 800 steps each, rank 32):

| Style | Initial Loss | Final Loss | Fidelity |
|---|---|---|---|
| Madhubani | 0.3254 | 0.1750 | 7/10 |
| Warli | 0.3354 | 0.1475 | 6/10 |
| Pattachitra | 0.3038 | 0.2005 | 8/10 |
| Mughal | 0.4716 | 0.1769 | 7/10 |
| Tanjore | 0.4505 | 0.1785 | 7/10 |

Style fidelity verified by independent GLM-4.6V vision-language model analysis.

## Tech Stack

- SDXL 1.0 + DreamShaper-XL turbo
- IP-Adapter XL (h94/IP-Adapter)
- Stable Video Diffusion XT 1.1
- ControlNet (Canny/Depth/OpenPose SDXL variants)
- PEFT 0.12, rank 32, 800 steps, AdamW 8-bit
- Gradio 4.x (6 tabs)
- Free AMD Qwen API for agent layer
- PyTorch 2.4.1 + Diffusers 0.30 + ROCm 6.2 / CUDA 12.1

## Quick Start

    git clone https://huggingface.co/Dev2506/indic-heritage-studio
    cd indic-heritage-studio
    pip install -r requirements.txt
    python app.py

## License
MIT for project code. Model checkpoints retain their original licenses.

Contact
Team: TeamIndicForge
Hackathon: AMD AI DevMaster Hackathon 2026
Track: Track 1 - Multimodal AI Content Creation
HuggingFace: https://huggingface.co/Dev2506/indic-heritage-studio
