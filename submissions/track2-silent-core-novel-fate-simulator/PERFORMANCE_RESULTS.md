# Silent Core Inference Performance Results

**Date:** 2026-08-06  
**Hardware:** one AMD Radeon `gfx1100` GPU with 48 GiB VRAM  
**Runtime:** ROCm 7.2.1

## Final architecture

```text
OpenAI-compatible gateway
  -> Qwen3-8B Q4_K_M / llama.cpp HIP / Radeon GPU
  -> Z-Image-Turbo / Diffusers model CPU offload / Radeon GPU
  -> Kokoro-82M / PyTorch / 16 CPU threads
```

Stable application model IDs are `silent-core/llm`, `silent-core/image`, and
`silent-core/tts`. Chat Completions, Responses, Image Generations, Audio Speech,
and MiniMax-compatible sentence-streaming TTS contracts were exercised.

## LLM A/B results

All trials used the same English prompt, one warm-up, streaming output, and 256
generated tokens. Values are medians of direct-engine trials.

| Engine and precision | TTFT | Decode | Decision |
|---|---:|---:|---|
| vLLM BF16 eager | 137 ms | 23.76 tok/s | Baseline |
| vLLM BF16 full-decode graph | 132 ms | 25.63 tok/s | Faster fallback |
| vLLM BF16 piecewise graph | 135 ms | 25.33 tok/s | Rejected |
| vLLM AWQ | 66 ms | 18.23 tok/s | Low-memory fallback only |
| llama.cpp HIP Q4_K_M | **42 ms** | **91.60 tok/s** | **Selected default** |

The selected engine is 3.57x faster than the best BF16 vLLM graph result and
3.86x faster than the original eager baseline by single-stream decode rate.
Five llama.cpp API trials ranged from 91.43 to 91.66 tok/s. A separate
`llama-bench` run measured 92.55 tok/s generation and 3,073 tok/s prompt
processing.

An external temporary-tunnel test measured a 1.325-second median TTFT over three
runs, versus 42 ms at the engine. This difference is reported as a transport
bottleneck and is not attributed to GPU inference.

## Image results

The application requires portrait output such as `1024x1536`, not only square
images. The selected service renders a memory-safe internal image at the target
aspect ratio and performs high-quality Lanczos fitting to the requested output
dimensions.

| Configuration | Latency | Result |
|---|---:|---|
| BF16 1024x1024 under original co-resident layout | 320.438 s | memory cliff at about 46.4/48 GiB |
| CPU-offload cold compatibility request | 26.759 s | HTTP 200 |
| CPU-offload warm compatibility request | 10.827 s | HTTP 200 |
| External warm `1024x1536` URL request | 11.694 s | valid downloadable PNG |

The warm application-compatible path is 29.6x faster than the original
memory-cliff reference. This is an end-to-end application endpoint comparison,
not a like-for-like native-resolution model benchmark.

## TTS A/B results

The benchmark text produces approximately 7.2 seconds of audio and exercises
both the OpenAI binary response and the two-sentence streaming adapter.

| Backend | Threads | Median RTF | Median first sentence | Decision |
|---|---:|---:|---:|---|
| sherpa-onnx INT8 | 8 | 1.091 | 4.160 s | Rejected |
| sherpa-onnx INT8 | 16 | 1.057 | 3.885 s | Rejected |
| PyTorch CPU | 4 | 0.629 | 2.716 s | Rejected |
| PyTorch CPU | 8 | 0.528 | 2.089 s | Good |
| PyTorch CPU | 16 | **0.514** | **1.988 s** | **Selected default** |

The production verification measured RTF 0.516, first sentence 2.001 seconds,
final stream status `[1, 2]`, and valid MP3 output. TTS is isolated from GPU
contention.

## Resource result

With llama.cpp, the offloaded image service, and CPU TTS healthy, idle GPU
memory was 10.86 GB in decimal ROCm reporting, approximately 10.1 GiB. A mixed
test with two LLM requests and one image request observed 98% GPU utilization at
approximately 216 W without an out-of-memory failure.

## Claim boundary

These measurements describe one Radeon host and this fixed workload. They
support a best-measured configuration claim for this project. They are not a
claim to beat multi-GPU datacenter systems in absolute performance.

