# 1bit.systems — Multimodal Content Creation Tools on AMD Radeon

**Team**: 1bit.systems
**Track**: Track 1 — Development of Multimodal Content Creation Tools
**Application**: 1bit Studio — image & video generation from one C++ binary
**Date**: August 2026
**Hardware**: AMD Ryzen AI Max+ 395 (Strix Halo) — Radeon 8060S GPU (gfx1151, ROCm) + 128 GB unified LPDDR5X

---

## 1. Project Background

Cloud content-generation tools are expensive, leak data, and depend on external APIs.
Local tools exist but are fragmented — separate Python stacks for image gen, video gen,
and LLM features, each with its own environment, dependencies, and GPU quirks.

**1bit.systems** is a single C++23 binary that runs AI models on AMD hardware — NPU, GPU,
and CPU in one process, zero Python in the engine. The **image_server** entry point adds
multimodal content creation on top of the same binary: text-to-image, image-to-image,
and text-to-video, exposed as an OpenAI-compatible API and as ComfyUI custom nodes.

Everything in this submission was run on the team's own AMD Strix Halo laptop
(Radeon 8060S, ROCm) — not a cloud instance.

## 2. Target Users & Application Scenarios

| User | Scenario |
|------|----------|
| Streamers / content creators | Local image + video generation, no per-use cloud fees, no upload of unpublished content |
| ComfyUI users | Native `1BP Image Generate` / `1BP Video Generate` nodes alongside existing LLM/VLM/TTS nodes |
| AI hobbyists on AMD hardware | One binary instead of a Python environment with fragile ROCm bindings |
| Privacy-sensitive studios | Full generation pipeline offline, on-device |

## 3. System Architecture

```
                 ┌────────────────────────────────────────────┐
   OpenAI API    │              build/1bit (single ELF)        │
  POST /v1/images/generations │  ┌──────────────────────────┐  │
  POST /v1/images/edits       ├──┤  image_server (C++23)    │  │
  POST /v1/video/generations  │  └──────────┬───────────────┘  │
  POST /v1/chat/completions   │             │ stable-diffusion.cpp (submodule, pure C++)
                 │             │  SD / SDXL / FLUX / Qwen-Image / Z-Image + LoRA  │
                 │             │  Wan / LTX / Hunyuan video · WebM/AVI encode    │
                 │             └──────────┬───────────────────┘
                 └────────────────────────┼───────────────────────┘
                                          ▼
                              ROCm HIP (gfx1151) / Vulkan / CUDA / Metal / CPU
                                          ▼
                           AMD Radeon 8060S · Strix Halo (this demo)
```

- **One binary, every entry point** — `1bit` dispatches by subcommand (`image`, `zaya`,
  `unified`, `vision`, …) or legacy symlink; image generation is a server, not a plugin.
- **No Python in the engine** — the C++ server links stable-diffusion.cpp directly;
  a Python process is never spawned.
- **OpenAI-compatible API** — drop-in for existing tooling; ComfyUI nodes wrap the same API.

## 4. Model & Algorithm Introduction

| Capability | Models | Notes |
|-----------|--------|-------|
| Text-to-image | SD1.x, SDXL, FLUX.1, Qwen-Image, Z-Image | LoRA adapters supported; verified on ROCm |
| Image-to-image | same family | `init_image_b64` in the API |
| Text-to-video | Wan2.1 T2V 1.3B, LTX-Video, HunyuanVideo | WebM/AVI encode built in |
| Video LoRA | video-lora (pure C++ Vulkan backend) | conv2d / group_norm / silu / attention / lora_merge kernels, GPU-verified |

**Measured on Radeon 8060S (ROCm), this machine:**
- SD1.5 txt2img, 512×512, 20 steps: **~10.8 s** (~2.3 it/s — see demo video)
- Wan2.1 T2V 1.3B: **2 m 38 s** end-to-end on ROCm vs **8 m 48 s** CPU (verified)

## 5. AMD Radeon GPU / ROCm Adaptation

- Backend auto-detect with explicit ROCm (HIP) path for gfx1151; all kernels run through
  the ROCm runtime with unified memory on Strix Halo.
- The same binary also runs Vulkan (ZINC), CUDA (sm_70+), Metal, and CPU — the
  generation stack is backend-agnostic.
- Pure C++ avoids the Python-wheel ROCm dependency chain entirely: no `torch` + ROCm
  wheel pairing, no venv, no CUDA-vs-ROCm fork of the runtime.

## 6. Deliverables

| # | Deliverable | Status | Location |
|---|------------|--------|----------|
| 1 | Project profile (this document) | ✅ | `PROJECT_PROFILE.md` |
| 2 | Project source code | ✅ | https://github.com/1bit-systems/1bit-systems (MIT, README with build/run guide) |
| 3 | Demo video | ✅ | `demo_track1.mp4` (2:29 — real commands against the live server on Radeon 8060S) |
| 4 | Poster | ✅ | `POSTER.md` |

**Demo video contents** (all real, recorded on-device):
1. `image_server` startup on ROCm, model list via `/v1/models`
2. Text-to-image: *"a red dragon flying over a mountain lake at sunset"* → PNG
3. Text-to-image: *"an astronaut riding a horse on Mars"* → PNG
4. Image-to-image: same dragon edited to night scene via `/v1/images/edits`
5. Generated outputs displayed

*Generated for AMD AI DevMaster Hackathon 2026-07 — Track 1 submission.*
