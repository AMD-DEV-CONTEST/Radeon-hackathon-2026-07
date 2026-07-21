# 1bit.systems — Local Multimodal Content Creation Platform
## AMD AI DevMaster Hackathon 2026 · Track 1: Multimodal Content Creation Tools

---

## 1. Project Background

1bit.systems is an open-source, model-agnostic inference engine supporting NPU, GPU, and CPU backends on AMD hardware. Originally built to reverse-engineer and replace AMD's closed-source XDNA 2 NPU stack (FastFlowLM), it has grown into a full multimodal content creation platform capable of:

- **Image understanding** via vision-language models (Qwen3-VL, Llama3.2-Vision)
- **Speech-to-text** via faster-whisper
- **Text-to-speech** via Piper TTS
- **Text generation** via 20+ LLM architectures (dense, MoE, Mamba, ternary)
- **Voice-driven interaction** combining STT → LLM → TTS in a single pipeline

All capabilities run **entirely locally** on AMD Radeon GPUs / AMD Instinct MI300X — no cloud APIs, no data leaves the device.

## 2. Target Users & Application Scenarios

| User | Scenario |
|------|----------|
| **Content creators** | Generate image captions, transcribe audio/video, create voiceovers, draft/edit text — all locally on AMD hardware |
| **Journalists** | Record interviews (STT), analyze images, generate summaries, produce audio versions |
| **Accessibility** | Describe images for visually impaired users, convert speech to text, generate audio from text |
| **Educators** | Create multimodal learning materials — annotated images, narrated slides, transcribed lectures |
| **Privacy-conscious users** | Use AI content tools without sending data to any cloud service |

## 3. System Architecture

```
User Input (Image / Voice / Text)
        │
        ▼
┌─────────────────────────────────────────────┐
│            Jarvis Agent Server               │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │ Vision   │  │ STT      │  │ TTS       │  │
│  │ (VL Ms)  │  │ (Whisper)│  │ (Piper)   │  │
│  └────┬────┘  └────┬─────┘  └─────┬─────┘  │
│       │            │              │         │
│  ┌────┴────────────┴──────────────┴────┐    │
│  │      Model Router & Planner         │    │
│  │  Routes to best model per subtask   │    │
│  └────────────────┬───────────────────┘    │
└───────────────────┼────────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌────────┐   ┌────────────┐   ┌──────────┐
│ NPU    │   │ GPU/ROCm   │   │ CPU      │
│ XDNA 2 │   │ AMD Radeon │   │ Fallback │
│ 32     │   │ MI300X     │   │          │
│ tiles  │   │ / Radeon   │   │          │
└────────┘   └────────────┘   └──────────┘
```

## 4. Models & Algorithms

| Model | Size | Backend | Content Creation Use |
|-------|------|---------|---------------------|
| Qwen3-VL-4B | 4B | NPU / GPU | Image captioning, visual Q&A |
| Llama3.2-Vision | 11B | GPU | Visual content analysis |
| Qwen3-4B/8B/35B | 4-35B | NPU / GPU | Text generation, editing, summarization |
| Llama3.1-8B | 8B | GPU | Long-form content |
| DeepSeek-R1-8B | 8B | GPU | Reasoning-enhanced content |
| Phi-4-mini | 4B | NPU / GPU | Lightweight content |
| faster-whisper | — | CPU/GPU | Speech-to-text (recording → transcript) |
| Piper TTS | — | CPU | Text-to-speech (script → voiceover) |

## 5. AMD Radeon GPU / ROCm Adaptation

Deployed and validated on **AMD DevCloud** with **AMD Instinct MI300X VF** (192 GB HBM3):

- **ROCm 6.2** + PyTorch 2.5.1 — full `device_map="auto"` support
- **Training throughput**: Qwen3-4B LoRA at **3.18 it/s** (67 min for 12,811 steps)
- **Inference**: OpenAI-compatible API works with Ollama/ROCm or vLLM on any AMD Radeon GPU
- **Zero code changes** needed between local ROCm and cloud MI300X deployment
- **Cost**: $1.99/hr for MI300X on AMD DevCloud (DigitalOcean)

## 6. Source Code

**Repository**: https://github.com/bong-water-water-bong/1bit-systems

Key modules for content creation:
- `jarvis/server.py` — Multimodal agent server (vision, voice, text)
- `jarvis/stt.py` — Speech-to-text module
- `jarvis/tts.py` — Text-to-speech module
- `jarvis/planner.py` — Multi-step task planner
- `jarvis/routing.py` — Model routing across NPU/GPU backends
- `tools/vision_server.cpp` — Standalone vision inference server
- `include/vl_processor.h` — Vision preprocessing pipeline
- `kernels/vl_resize_norm.hip` — GPU vision kernels (ROCm/HIP)

## 7. Team

Solo developer — bong-water-water-bong
