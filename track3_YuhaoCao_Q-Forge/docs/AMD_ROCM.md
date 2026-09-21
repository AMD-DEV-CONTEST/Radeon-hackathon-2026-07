# AMD Radeon and ROCm Notes

## Tested platform

```text
GPU architecture: gfx1100
Compute units:    96
VRAM:             51,522,830,336 bytes (~48 GiB)
ROCm runtime:     7.2.4
PyTorch build:    2.8.0+rocm6.4
Python:           3.11
Rendering:        EGL / headless MuJoCo
```

The server's product string is generic (`AMD Radeon Graphics`, device `0x744b`),
so this report does not infer a retail board name beyond the authoritative
`gfx1100`, CU, and memory values.

## Environment

```bash
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export LIBERO_CONFIG_PATH="$PWD/configs/libero"
export TOKENIZERS_PARALLELISM=false
export SMOLVLA_ATTENTION_BACKEND=sdpa
python scripts/verify_rocm_torch.py
```

The PyTorch package was compiled with the ROCm 6.4 build target and runs on the
newer runtime/driver stack. Always validate kernels on the actual target rather
than assuming that the package suffix equals the installed runtime.

## Training stability decision

Residual training initially encountered a native segmentation fault in a frozen
FP32 critic Linear kernel before the first optimizer update. The stable path uses
SDPA MATH for SmolVLA training and executes the frozen critic on CPU only to form
detached guidance targets. It preserves the student Action Expert's gradient while
avoiding the unstable frozen-critic GPU path.

## Attention backend decision

Benchmark each execution phase. On this `gfx1100` setup:

- CK FlashAttention is fastest for forward-only inference and rollout;
- PyTorch SDPA is fastest for backward and a complete training step;
- AMD Triton has the smallest peak allocation at sequence length 4096.

For FP16 causal `B=8, H=16, D=64, S=4096`, CK reaches 57.71 forward
TFLOP/s versus 12.23 for SDPA, while SDPA completes the full step in 66.82 ms
versus 88.20 ms for CK. This is why the project does not select a backend from
forward TFLOP/s alone.

## Known compatibility details

- The CK varlen wrapper required a Python/C++ argument-alignment patch.
- CK and Triton numerical comparisons pass FP16/BF16 forward/backward and packed
  varlen finite-gradient checks.
- Compile binary extensions for the evaluator's exact torch ABI; do not reuse an
  unrelated CUDA or ROCm wheel.
- Keep `MUJOCO_GL=egl` and `PYOPENGL_PLATFORM=egl` in headless environments.

