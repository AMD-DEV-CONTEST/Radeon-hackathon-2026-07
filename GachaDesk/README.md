# GachaDesk

> Track 1 — Multimodal Content Creation Tool on AMD Radeon GPU (ROCm)

A one-line description of what GachaDesk does.

## Project Structure

```
GachaDesk/
├── README.md                              # This file (English, submission entry)
├── README.zh-CN.md                        # Chinese version
├── .gitignore                             # Ignores .env / .bat and other sensitive files
├── requirements.txt                       # Main project dependencies
├── scripts/                               # Launch / deployment scripts
└── src/                                   # Source code
    ├── app.py                             # Main entry (thin client, calls remote sub-service APIs)
    ├── requirements.txt                   # Main project dependencies
    ├── app/                               # Application entry & UI (reserved package)
    │   └── __init__.py
    ├── models/                            # Model & algorithm (reserved package)
    │   └── __init__.py
    ├── Qwen-Image-2512-AMD-MI308X/        # Text-to-Image sub-service (deployed on MI308X)
    │   ├── app.py                         # Qwen-Image-2512 inference entry
    │   ├── requirements.txt
    │   ├── README.md                      # English version
    │   └── README.zh-CN.md                # Chinese version
    ├── Qwen-Image-Edit-2511-AMD-MI308X/   # Image-to-Image sub-service (deployed on MI308X)
    │   ├── app.py                         # Qwen-Image-Edit-2511 inference entry
    │   ├── requirements.txt
    │   ├── images/                        # Example images (t1-1.png / t1-2.png)
    │   ├── README.md                      # English version
    │   └── README.zh-CN.md                # Chinese version
    └── Wan2.2-14B-I2V-LoRA-AMD-MI308X/    # Image-to-Video sub-service (deployed on MI308X)
        ├── app.py                         # Wan2.2-I2V inference entry
        ├── requirements.txt
        ├── images/                        # Example images (t1.jpg / t2.jpg / t3.jpg)
        ├── README.md                      # English version
        └── README.zh-CN.md                # Chinese version
```

## Environment Requirements

- Hardware: AMD Radeon GPU (ROCm)
- OS: Linux (ROCm supported)
- Python: 3.10+
- ROCm: See [Radeon Cloud User Guide](../Radeon-Cloud-User%20Guide/README.md)

## Dependencies

```bash
pip install -r requirements.txt
```

> Note: The ROCm-enabled PyTorch wheel must be installed separately according to the
> official ROCm documentation before running the command above.

## Quick Start

```bash
# 1. Enter the source code directory
cd src

# 2. Launch the application
python app.py
```

The web UI will be available at `http://localhost:7860` by default.

## Demo Video

- Video link: (to be added, Bilibili / YouTube recommended)

## Project Profile Document

- [GachaDesk-Profile.pdf](docs/GachaDesk-Profile.pdf)

## AMD Radeon GPU / ROCm Adaptation

All three submodules run on a single **AMD Instinct MI308X (192GB HBM3)** card, on top of **ROCm 6.3.0+** and the ROCm build of PyTorch, fully local inference without any remote API calls. Each submodule adopts a different ROCm optimization combination tailored to its own model characteristics:

### 1. Qwen-Image-2512 (Text-to-Image)

- **Precision**: bfloat16 (native ROCm support)
- **Attention**: `attn_implementation="flash_attention_2"`, with `torch.backends.cuda.preferred_rocm_fa_library("aotriton")` preferring the AOTriton backend
- **MatMul**: `torch.backends.cuda.matmul.allow_tf32 = True` + `set_float32_matmul_precision("high")` (significant TF32 speedup on MI300+ series)
- **VRAM**: Full GPU loading — the 20B MMDiT is entirely loaded into 192GB HBM3, zero paging
- **Fallback**: VAE float16 decoding automatically falls back to float32 on failure; `torch.cuda.synchronize()` is called at key points to avoid ROCm async errors

### 2. Qwen-Image-Edit-2511 (Image Editing)

- **Precision**: bfloat16
- **Attention**: `enable_flash_sdp(True)` + `enable_mem_efficient_sdp(True)` enabled, `math_sdp` disabled, forcing the Triton Flash Attention kernel
- **Key Environment Variables**:
  - `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` — enable experimental AOTriton kernels
  - `FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE` — enable AMD Triton Flash Attention
  - `HIP_FORCE_DEV_KERNARG=1` — force device-side kernel arguments
  - `PYTORCH_HIP_ALLOC_CONF=garbage_collection_threshold:0.8,max_split_size_mb:512` — optimize VRAM fragmentation
- **Cache Persistence**: `TRITON_CACHE_DIR` / `TORCH_EXTENSIONS_DIR` are redirected to `/mnt/workspace`, avoiding AMD GPU kernel recompilation after container restart (first compile ≈ 20 minutes, subsequent runs instant)
- **Acceleration**: Loads the `lightx2v/Qwen-Image-Edit-2511-Lightning` distillation LoRA, producing images in just 4 steps
- **Resolution Lock**: Fixed at 1664×928 to avoid kernel recompilation triggered by different shapes

### 3. Wan2.2-14B-I2V-LoRA (Image-to-Video)

- **Precision**: float16
- **Attention**: `attn_implementation="xformers"` (falls back to default implementation on failure)
- **Acceleration**: Loads both `high_noise` and `low_noise` adapters from `lightx2v/Wan2.2-Distill-Loras` (50% weight each), enabling 4-step ultra-fast inference
- **Output**: Fixed 16 FPS, supports 1280×720 / 832×480 / 768×432 resolutions and 81 or 121 frames
- **Monitoring**: Integrates `rocm-smi` to obtain real-time temperature and core/memory clock — information unavailable via `torch.cuda`

### Common Optimizations

- **Full Local Inference**: Models in all three modules are entirely loaded into MI308X VRAM, without quantization sharding or CPU offload
- **Gradio + MCP**: All modules enable `mcp_server=True`; each API endpoint is automatically mapped to an MCP tool, ready for agent invocation
- **Dual-Channel Logging**: `logger.info` / `print` output to both the console and the Gradio runtime log panel simultaneously
- **VRAM Hygiene**: `gc.collect()` + `torch.cuda.empty_cache()` before and after each inference to prevent fragment accumulation

### Deployment Architecture (Main Project + Remote Sub-Services)

The main project `src/app.py` adopts a **thin-client + remote GPU service** deployment architecture. It does not load any model itself; instead, it calls three independently deployed submodules via the Gradio API provided by ModelScope Studio:

- **Main Project (Thin Client)**: Runs in any environment (local / edge / low-spec machine), responsible for user interaction, storyboard orchestration, video merging and watermarking. Zero GPU dependency — only depends on `requests`, `gradio`, `imageio`, `PIL`.
- **Three Remote Sub-Services (Heavy GPU Side)**: Each deployed on AMD MI308X, exposing Gradio API + SSE streaming responses via ModelScope Studio:
  - `studio-xihuyisheng-qwen-image-2512-amd-mi308x` — Text-to-Image
  - `studio-xihuyisheng-qwen-image-edit-2511-amd-mi308x` — Image-to-Image
  - `studio-xihuyisheng-wan2-2-14b-i2v-lora-amd-mi308x` — Image-to-Video

The main project encapsulates the full remote invocation flow via the `ModelScopeImageClient` class: `/config` endpoint discovery → task submission → SSE stream listening for results → API-gateway-authenticated artifact download, plus `upload_image` for uploading images to be edited. Authentication uses a Bearer Token (read from `MODELSCOPE_API_TOKEN` in `.env`).

This architecture decouples compute from interaction: **the actual ROCm inference compute is concentrated in the cloud MI308X sub-services, while the main project can run on any low-spec terminal**, suitable for scenarios with limited terminal resources such as rural teaching aids and live-commerce broadcasting.

## Team Information

- Team: xihuyisheng
- Members: (to be added)
