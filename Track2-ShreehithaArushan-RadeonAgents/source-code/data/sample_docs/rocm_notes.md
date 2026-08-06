# Running Large Language Models on AMD Radeon with ROCm

ROCm (Radeon Open Compute) is AMD's open-source software platform for GPU computing. PyTorch has official ROCm builds that expose the familiar `torch.cuda` API, making it relatively straightforward to run existing CUDA-oriented code on AMD GPUs.

## Key Points for Agent Developers

- Install the matching ROCm version of PyTorch from the official wheels.
- Use `device_map="auto"` and 4-bit quantization (bitsandbytes) to fit larger models into consumer VRAM.
- Prefer models in the 1B–7B parameter range for interactive agent loops on 8–16 GB cards.
- Measure tokens/s and VRAM with a dedicated benchmark script – this is the best way to demonstrate optimization quality to judges.
- SDPA (scaled dot-product attention) generally works well and improves throughput.

## Recommended Models for RadeonAgents

- microsoft/Phi-3-mini-4k-instruct (excellent quality/size trade-off)
- Qwen2.5-3B-Instruct
- Llama-3.2-3B-Instruct

Always verify the model license and chat template compatibility.
