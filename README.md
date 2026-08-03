# CesarOps Inference Engine + Forge

A pure-Rust + wgpu/Vulkan LLM inference engine targeting older GPUs (Tesla P100, GTX 10xx) plus a self-healing agent harness ("forge") with cluster control panel.

## What's here

```
src/                    # cesarops-inference: Rust+wgpu inference engine
shaders/                # WGSL compute shaders (matmul, attention, dequant kernels)
forge_src/              # cesarops-forge-v2: agent harness + cluster panel
fleet_prompts/          # Multi-model dispatch infrastructure
DEBUG_LOG.md            # Session debug history
```

## Status

**Inference engine**: produces coherent output on Qwen2.5-Coder-1.5B Q6_K (`"What is 2+2?" → "2+2 equals 4."`). Currently 0.2 t/s on P100 — speed work in progress (vec4 matvec, INT8 DP4A, fused kernels).

**Forge**: self-healing agent harness with corrector cascade (14B → P1000 TinyLlama → laptop M2200), close-enough code fixer, cluster control panel with per-card vector injection / backend / memory pool / engine selection.

## Engine support

Quant types: F32, F16, BF16, Q4_0, Q4_K, Q5_K, Q6_K, Q8_0, IQ4_XS

Architectures (auto-detected from GGUF metadata): Qwen2/2.5/3, Gemma 2/3/4, Llama 3, Phi 3, DeepSeek V2

## Key fixes in this session

- Q6_K dequant: corrected to match llama.cpp's block-structured layout (was producing garbled output)
- IQ4_XS, Q5_K, Q8_0 dequant added (enables Gemma 4 MoE IQ4_XS)
- GGUF arch auto-detection (no per-model hardcoding)
- Submit batching: 12 submits/layer vs 20+ on P100 Vulkan
- Diagnostic readbacks gated behind `cfg!(diagnostics)` feature

## Hardware

Tested on Tesla P100-PCIE-16GB via Vulkan/wgpu on Ubuntu 24.04.
Designed to also run on GTX 1060/1070/P1000/M2200 via the same backend.

## P100 multi-GPU operations (cesarops2)

Use the helper scripts in `scripts/` to operate remote P100 lanes from this host:

- `scripts/sync_forge_to_cesarops2.sh [host]` — rsync Forge source/config/scripts to remote.
- `scripts/start_remote_llama_worker.sh <host> <model> <port> <gpu_ids_csv> [tensor_split] [ctx] [threads] [ngl]`
- `scripts/start_cesarops2_p100_profiles.sh [host] [tp2|tp3|tp4]` — launch common 2/3/4-GPU profiles.
- `scripts/stop_remote_llama_port.sh <host> <port>` — stop a remote lane by port.
