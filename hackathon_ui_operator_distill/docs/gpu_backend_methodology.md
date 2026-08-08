# GPU Backend Methodology: CUDA and HIP/ROCm

Screen-AI borrows another important idea from `codiii` / Colibri:

```text
one backend source + one vendor compatibility shim
```

The goal is to avoid building two separate projects:

```text
NVIDIA version
AMD version
```

Instead, Screen-AI should have:

```text
CPU default runtime
CUDA optional backend
HIP/ROCm optional backend
```

The default path remains lightweight and dependency-minimal. GPU support is an acceleration tier, not a requirement for basic screen control.

## Design Rule

Vendor-specific differences must live in one compatibility file.

```text
native/gpu_compat.h
```

The backend implementation should stay clean:

```text
native/screen_gpu_backend.cpp
```

Rule:

```text
No scattered CUDA/HIP conditionals inside the algorithm code.
```

This follows the same methodology as Colibri's `backend_gpu_compat.h` approach: compile the same backend for CUDA or HIP/ROCm by mapping the small runtime surface in a shim.

## Build Modes

| mode | purpose | expected platform |
|---|---|---|
| CPU | default local scanner, works everywhere | Windows/Linux |
| CUDA | optional NVIDIA dev/testing path | Linux/Windows where available |
| HIP/ROCm | AMD hackathon acceleration path | Linux ROCm |

## What GPU Accelerates in Screen-AI

GPU should not control the mouse or keyboard.

GPU accelerates perception:

- image preprocessing
- visual candidate scoring
- tiny UI detector inference
- OCR preprocessing
- batch screenshot labeling
- teacher/student distillation

The control loop remains:

```text
screen scan -> element map -> action executor -> verification
```

## Runtime Environment Variables

Use neutral names first, then map internally:

```text
SCREENAI_GPU=0|1
SCREENAI_GPU_BACKEND=cpu|cuda|hip
SCREENAI_GPU_DEVICE=0
SCREENAI_GPU_MEMORY_MB=1024
SCREENAI_GPU_RELEASE_HOST=1
```

For AMD ROCm:

```bash
export SCREENAI_GPU=1
export SCREENAI_GPU_BACKEND=hip
export HIP_VISIBLE_DEVICES=0
```

For NVIDIA:

```bash
export SCREENAI_GPU=1
export SCREENAI_GPU_BACKEND=cuda
export CUDA_VISIBLE_DEVICES=0
```

## 4 GB Laptop Policy

On a 4 GB RAM laptop:

```text
GPU backend is optional
CPU scanner stays resident
OCR/detector are lazy-loaded
heavy parser remains SSD/cloud tier
```

If memory is low, Screen-AI must fall back to:

```text
UI Automation + OpenCV + cached maps
```

## AMD Hackathon Validation

For eligibility, collect proof from AMD cloud:

```bash
rocm-smi
rocminfo | head
python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no gpu")
PY
```

Then run a Screen-AI perception benchmark:

```text
CPU preprocessing time
HIP/ROCm preprocessing or detector time
end-to-end screenshot parse time
```

## Known Behavior

GPU outputs may differ slightly from CPU due to floating-point rounding and different kernels. For Screen-AI, exact byte-identical numeric output is less important than:

```text
same target chosen
same click center within tolerance
same verification result
```

Validation should compare element boxes using IoU and click-center distance, not exact tensor values.

## Future Native Backend

The native backend should expose a tiny C API:

```c
screenai_gpu_init(device_id, memory_budget_mb)
screenai_gpu_preprocess_rgba(...)
screenai_gpu_detect_candidates(...)
screenai_gpu_shutdown()
```

Python/C#/desktop code can call this backend through:

- CLI subprocess first
- Python ctypes later
- C# P/Invoke later

This keeps the hackathon version simple while leaving a serious path to a compiled AMD ROCm backend.

