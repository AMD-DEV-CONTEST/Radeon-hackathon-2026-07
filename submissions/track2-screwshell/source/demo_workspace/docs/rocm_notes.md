# ROCm Field Notes (Platform Team)

Rolling notes from the W7900 pilot. Newest first.

## 2026-07-25 — adapter hot-swap latency

Measured PEFT `set_adapter` between three LoRA experts on the frozen
Qwen3.5-9B base: mean 4-40 ms depending on target_modules overlap. A full
model reload for comparison costs ~90-180 s from the read-only NFS mount.
Conclusion: hot-swap is 3-4 orders of magnitude cheaper than reload, and
VRAM stays flat (base resident, adapters are MB-scale).

## 2026-07-22 — GDN Triton kernels

Qwen3.5's gated-delta-network layers JIT-compile their Triton kernels on
first forward. On ROCm 7.2.4 the first token is slow (compile), afterwards
steady state. Cache persists per process only — warm up at server start.

## 2026-07-18 — CPU fallback incident

A stray `torch.float64` tensor in a custom sampler forced a CPU dispatch
and tokens/s dropped 20x. Fixed by forcing bf16 end-to-end. Action: add
dispatch assertion to the benchmark harness (see risk #3 in the plan).

## 2026-07-15 — VRAM budgeting

9B bf16 base ~19-21 GB resident. With KV cache at 8k context plus three
LoRA adapters we stay under 26 GB of the 48 GB budget — comfortable
headroom for batch 4 serving.
