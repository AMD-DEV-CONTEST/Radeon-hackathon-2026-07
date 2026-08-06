# Radeon Cloud validation report

Validated on AMD Radeon Cloud instance `u-14509-356ae880`.

## Runtime

| Check | Result |
|---|---|
| Python | 3.12.3 |
| pip | `/workspace/venv/bin/pip` |
| PyTorch | `2.13.0+rocm7.2` |
| HIP reported by PyTorch | `7.2.53211` |
| `torch.cuda.is_available()` | `True` |
| GPU | AMD Radeon Graphics |
| Total VRAM | 47.98 GiB |
| Jupyter kernel | `Python (AI Photographer ROCm)` |

`torch.cuda` is the expected PyTorch frontend name on ROCm. The non-null
`torch.version.hip` value confirms that this is the HIP backend, not an NVIDIA
CUDA build.

## Qwen2.5-VL-3B demo

Input: `/workspace/b69343b9c09aadfa684347124910121c.JPG`

| Metric | Result |
|---|---|
| Inference time | 27.534 seconds |
| Peak allocated VRAM | 10.184 GiB |
| Peak reserved VRAM | 11.387 GiB |
| Total VRAM | 47.98 GiB |
| Critic result | pass |

The model was loaded from the local Hugging Face snapshot with offline mode.
No model download or external AI API was required for the successful run.

Full structured output: `demo/demo_result.json`.
