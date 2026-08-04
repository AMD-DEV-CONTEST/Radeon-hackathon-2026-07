Document ID: RP-KB-002
Revision: 1.0
Classification: competition-public

# vLLM Local Deployment Playbook (ROCm)

> Deployment reality on the competition instance: vLLM 0.26.0 ships no ROCm wheel
> (its PyPI wheel is CUDA-only), and the Docker-less gfx1100 box would need a
> source build. The verified engine for this submission is therefore llama.cpp with
> HIP (see below for the vLLM reference flags when a ROCm build is available).

RadeonPilot deploys the agent model with vLLM inside a Python virtual environment
on the Radeon instance. There is no Docker daemon on the competition instance, so
container images are not used.

## Reference launch

Serve Qwen3-8B in BF16 on a single gfx1100 GPU:

    vllm serve /root/models/Qwen3-8B \
        --host 127.0.0.1 --port 8000 \
        --served-model-name qwen3-8b \
        --max-model-len 8192 \
        --gpu-memory-utilization 0.85 \
        --enable-prefix-caching \
        --enable-chunked-prefill

Bind to 127.0.0.1 only. Record the host PID of the endpoint; it is required for
process-level Radeon attestation via `amd-smi process --pid`.

## Why these flags

- `--max-model-len 8192` keeps the KV-cache footprint inside the 48 GB budget while
  still covering agent evidence packs and multi-turn context.
- `--gpu-memory-utilization 0.85` leaves headroom so concurrent specialist requests
  do not evict the KV cache under continuous batching.
- `--enable-prefix-caching` reuses the shared system prompt and policy preamble
  across the four specialist sessions, cutting prefill tokens.
- `--enable-chunked-prefill` overlaps prefill and decode for smoother latency when
  several agents run concurrently.

## Speed optimisation levers

Continuous batching, prefix caching, compact evidence packs, tool-first routing,
and bounded agent output all reduce tokens-per-request. Measure TTFT, decode
throughput, and VRAM before and after each change with the benchmark runner and
commit only the measured JSON.

## Quantized comparison (bonus)

A Q4_K_M GGUF served by llama.cpp provides the optional quantized profile. Only
report it if the frozen quality gate passes against the same evaluation prompts.

## llama.cpp engine flags (verified path)

Serve the Qwen3-8B GGUF with llama-server, full GPU offload and thinking disabled:

    llama-server --model Qwen3-8B-Q4_K_M.gguf \
        --host 127.0.0.1 --port 8000 \
        --ctx-size 8192 --n-gpu-layers 99 \
        --parallel 4 --flash-attn auto \
        --chat-template-kwargs '{"enable_thinking":false}' \
        --alias qwen3-8b

Optimization levers here are `--flash-attn on`, higher `--parallel` slots, and a
bounded `--ctx-size`, measured before/after by the benchmark runner.
