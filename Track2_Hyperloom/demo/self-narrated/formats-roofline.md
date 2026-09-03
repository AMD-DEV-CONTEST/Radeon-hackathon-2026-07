# Formats mainline llama.cpp can't run — graded against the decode roofline

Two claims, both measured on one AMD Radeon AI PRO R9700 (gfx1201, roc9 build):

1. **The fork adds native RDNA4 kernels for formats absent in mainline llama.cpp** — `Q1_0`,
   `Q2_0` (ternary), native `fp8` (E4M3), and `2:4-sparse iu4`. These are custom GGML type IDs
   (43-49 + the ternary types) beyond mainline's enum — a stock llama.cpp build refuses them.
2. **Each is graded against its *mathematical maximum*** — for decode that's the memory-bandwidth
   ceiling, `max t/s = usable_VRAM_BW / bytes-read-per-token`. Usable BW = **512 GB/s** (80% of the
   640 GB/s spec), confirmed because fp8-27B decode sits right at that roofline.

| Format | Model | Size | Decode t/s | **Ceiling (goal)** | % of peak | Bound |
|---|---|---|---|---|---|---|
| **Q1_0** (1-bit) | Bonsai-27B-Q1_0 | 3.5 GB | 41.4 | 145 | 29% | dispatch/compute — **+104 headroom** |
| **Q2_0** (ternary) | Ternary-Bonsai-27B-Q2_0 | 6.7 GB | 49.8 | 77 | 65% | dispatch/compute — +27 |
| **2:4-sparse iu4** | sparse-llama-8B-2of4 | 5.6 GB | 62.5 | 91 | 68% | dispatch/compute — +29 |
| **fp8 E4M3** | **Qwen3.6-27B-Quacken (AMD Quark)** | 29.3 GB | 17.0 | 18 | **97%** | **MEMORY — at roofline** |

The fp8 model is a **genuine AMD Quark** quantization (`Qwen3.6-27B-Quacken-F8E4M3`, 2 Quark markers in
its metadata) — the "Quark → runnable on Radeon" story — and its decode is **97% of the memory ceiling**,
i.e. the native-fp8 kernel is already optimal; fp8 is just a heavy (8-bit) format for decode.

## What the roofline tells the optimizer
- **fp8 = done** (memory-bound). The only faster-decode lever is a lighter quant.
- **Q1_0 / Q2_0 / iu4 = big headroom** (dispatch/compute-bound, 29-68% of peak). They read few bytes/token
  but don't saturate bandwidth — the bottleneck is the batch-1 **kernel-boundary tax**. Closing it (a
  fused/persistent-chain kernel — card 180) chases each toward its ceiling: Q2_0 50→77, Q1_0 41→145.

*Decode is memory-bound → a clean ceiling. Prefill is compute-bound (INT4 765 / INT8=FP8 382.7 /
FP16 191.4 TOPS-class) and harder to bound — see `rdna4-peak-targets.md`. The optimizer's primary
graded target is the decode roofline above.*
