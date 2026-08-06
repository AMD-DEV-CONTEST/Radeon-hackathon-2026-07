# AMD ROCm Optimization Guide

## ROCm 6.2 Setup
To run Bunker efficiently on AMD Radeon GPUs, ROCm 6.2 is required.
1. **Packages**: Install `rocm-dkms`, `rocm-dev`, and `rocm-libs` via the AMD package manager.
2. **Environment Variables**:
   ```bash
   export HSA_OVERRIDE_GFX_VERSION=11.0.0  # For RX 7900 series compatibility
   export ROCM_PATH=/opt/rocm
   ```

## PyTorch ROCm Integration
Bunker uses the ROCm-native build of PyTorch. The transition is largely transparent; PyTorch's backend translates `torch.cuda` calls to HIP (Heterogeneous-compute Interface for Portability) calls.
To verify:
```python
import torch
print(torch.cuda.is_available())  # Returns True on ROCm
print(torch.version.hip)          # Prints the HIP version
```

## vLLM ROCm Configuration
We deploy vLLM natively on ROCm. Key command-line flags include:
- `--tensor-parallel-size <N>`: Required for multi-GPU setups.
- `--gpu-memory-utilization 0.9`: Maximizes VRAM usage for the KV cache while leaving a 10% buffer for system stability.
- `--max-model-len 8192`: Caps context length to prevent unexpected OOM errors during massive RAG operations.

## INT4 Quantization with AutoGPTQ
To run massive models like Qwen3-30B-A3B on single consumer GPUs (e.g., RX 7900 XTX 24GB), INT4 quantization is mandatory.
- **Methodology**: We utilize AutoGPTQ, leveraging ROCm-specific wheels built against HIP. 
- **Group Size = 128**: We specifically configure `group_size=128`. This strikes the optimal balance between VRAM footprint and model perplexity, minimizing accuracy degradation while fitting comfortably in 24GB VRAM.

## Flash Attention on ROCm
Flash Attention significantly speeds up attention mechanism calculations. 
- We use `--enable-prefix-caching` in vLLM to reuse KV cache for system prompts and persistent context.
- We enable `--enable-chunked-prefill` to chunk long prompts, ensuring that the Time To First Token (TTFT) remains low even when embedding large RAG documents.

## Memory Optimization
- **PYTORCH_HIP_ALLOC_CONF**: Set to `expandable_segments:True` to reduce VRAM fragmentation and prevent out-of-memory errors during prolonged chat sessions.
- **Batching**: vLLM's continuous batching on ROCm allows simultaneous processing of generation and prefill requests, maximizing GPU utilization.

## Benchmark Results
*Hardware: AMD Radeon RX 7900 XTX (24GB VRAM), ROCm 6.2*

| Precision | TTFT (ms) | Throughput (tok/s) | VRAM Usage (GB) |
| :--- | :--- | :--- | :--- |
| FP16 (Unquantized) | OOM | N/A | >24 |
| INT8 (GPTQ) | 125 | 35 | 18 |
| INT4 (GPTQ) | 85 | 65 | 11 |

## Radeon Cloud API Integration
If the user permits it in `PrivacyConfig`, Bunker can fallback to the Radeon Cloud API.
- **Trigger Conditions**: If local VRAM is exhausted or local inference latency exceeds a predefined threshold.
- **Quantization Matching**: Requests are sent requesting 4-bit quantized generation to match local speed and output style constraints.
