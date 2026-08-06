# Inference Module - Maintainer Guide

**Module purpose**: Manages the multi-tiered inference pipeline for the Bunker agent, prioritising local execution on AMD ROCm hardware via vLLM, with a seamless cloud fallback.

## Public API

| Class | Key Methods | Purpose |
|-------|-------------|---------|
| `ModelManager` | `initialize()`, `generate()`, `stream_generate()`, `get_stats()` | Orchestrates the fallback chain and tracks usage metrics. |
| `VLLMServer` | `start()`, `stop()`, `generate()`, `stream_generate()` | Manages local vLLM subprocesses. |
| `RadeonCloudAPI` | `generate()`, `stream_generate()`, `is_available()` | Interfaces with AMD's cloud API. |
| `ModelQuantizer` | `quantize_model()`, `verify_rocm()` | Utilities for AutoGPTQ quantisation and ROCm validation. |

## Fallback Chain

1. Primary local vLLM (`config.primary_model`)
2. Secondary local vLLM (`config.secondary_model`)
3. Radeon Cloud API (`RadeonCloudAPI`)
4. Fail (`RuntimeError`)

## Critical Invariants

*   `extra_body: {"quantization": "4bit"}` MUST be included in every `RadeonCloudAPI` generate request payload (for Track 2 bonus points).
*   `fallback_stats` MUST be incremented in `ModelManager` on every successful `generate()` or `stream_generate()` call to accurately track local vs cloud execution.
*   `HIP_VISIBLE_DEVICES=0` and `PYTORCH_HIP_ALLOC_CONF=max_split_size_mb:512` MUST be set in the environment before launching the vLLM subprocess.

## Adding a New Inference Backend

1.  Create a new class (e.g., `OllamaServer`) implementing `generate(messages, max_tokens, temperature)` and `stream_generate(...)`.
2.  Add a health check method (e.g., `is_available()`).
3.  Initialise the class in `ModelManager.initialize()`.
4.  Insert the new backend into the `generate` and `stream_generate` try-catch blocks in `model_manager.py`, updating `fallback_stats` accordingly.

## Key ROCm vLLM Flags

```bash
python -m vllm.entrypoints.openai.api_server \
  --model <model_path> \
  --quantization gptq \
  --dtype float16 \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.85
```

## Wiring

*   Instantiated and managed by [model_manager.py](file:///c:/Users/USER/Desktop/James%20Projects/Bunker/src/inference/model_manager.py)
*   Wired into the main application lifecycle in [main.py](file:///c:/Users/USER/Desktop/James%20Projects/Bunker/src/main.py)
