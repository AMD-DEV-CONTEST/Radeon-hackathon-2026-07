# The AMD-AI substrate — 18 targets, with evidence status

The agent's `hardware.py` maps every AMD AI-capable target it knows how to reason about. This doc states, honestly, **which levers are MEASURED on real silicon here vs ASSUMED from the ISA census / vendor docs.** The agent itself never conflates the two — it re-runs the assembler ISA census (`llvm-mc`) on whatever part it detects and correctness-gates every number before reporting it. This table is the same discipline, written down.

**One part is physically present on the development machine: `gfx1201` (Radeon AI PRO R9700, ×2).** Everything measured lives there. Every other row is *capability-mapped* from the assembler + vendor documentation — real instructions, real levers, but not yet benchmarked on that silicon by us.

## GPU

| Target | Arch | Key levers | Status |
|---|---|---|---|
| `gfx1030` | RDNA2 | Wave32, **no WMMA** — dp4a/dequant only | ASSUMED (ISA) |
| `gfx1100` | RDNA3 | WMMA, Wave32 | ASSUMED (ISA; arch-specialist exists) |
| `gfx1151` | RDNA3.5 (Strix Halo iGPU) | unified-memory APU — bandwidth-starved, byte-width is everything | ASSUMED (ISA; arch-specialist exists) |
| `gfx1200` | RDNA4 | WMMA + SWMMAC + dot8 + native fp8 | ASSUMED (shares gfx1201 ISA) |
| **`gfx1201`** | **RDNA4 (R9700)** | **WMMA + SWMMAC(2:4) + dot8(int4) + native fp8** | **MEASURED — see below** |
| `gfx1250` | RDNA next-gen | RDNA4 levers **+ native MX-WMMA + `v_cvt_scalef32_*` + fp4-cvt** (the gfx1201-gated units) | ASSUMED (llvm-mc census) |
| `gfx908` | CDNA1 (MI100) | Wave64 MFMA | ASSUMED (docs) |
| `gfx90a` | CDNA2 (MI250/210) | Wave64 MFMA, big HBM | ASSUMED (docs) |
| `gfx942` | CDNA3 (MI300) | Wave64 MFMA, throughput/batch | ASSUMED (docs) |
| `gfx950` | CDNA4 (MI350) | MFMA **+ native MX** (MXFP4/6/8 hw scale) + fp4/fp8 scale-convert | ASSUMED (docs) |

## CPU · NPU · APU

| Target | Class | Key levers | Status |
|---|---|---|---|
| `znver3` | Zen3 CPU (Milan/Ryzen 5000) | AVX2 int8; vLLM-CPU; NUMA pin | ASSUMED (ISA/docs) |
| `znver4` | Zen4 CPU (Genoa/TR 7000/Ryzen 7000) | AVX-512-VNNI int8 + BF16; zentorch | ASSUMED (ISA/docs) |
| `znver5` | Zen5 CPU (Turin/TR 9000/Ryzen 9000) | AVX-512-VNNI int8 + BF16; zentorch; many-core Threadripper tier | ASSUMED (ISA/docs) |
| `xdna1` | XDNA1 NPU (Phoenix/Hawk Point) | int8 on the AIE (~10-16 TOPS); Ryzen AI / Lemonade | ASSUMED (docs) |
| `xdna2` | XDNA2 NPU (Strix) | int8/int4 on the AIE (~50 TOPS); Ryzen AI / Lemonade | ASSUMED (docs) |
| `strix-halo` | APU (Ryzen AI Max) | unified LPDDR5X (≤128 GB, zero-copy) + hybrid NPU+iGPU+CPU partition | ASSUMED (docs) |
| `strix-point` | APU (Ryzen AI 300) | unified memory + hybrid partition | ASSUMED (docs) |
| `phoenix` | APU (Ryzen 7040/8040) | unified memory + hybrid (XDNA1 + RDNA3 iGPU + Zen4) | ASSUMED (docs) |

APUs carry an `engines[]` field so the agent decomposes them into their constituent GPU/CPU/NPU rows and applies each engine's levers (e.g. Strix Halo = `znver5` + `gfx1151` iGPU + `xdna2` NPU).

## MEASURED on gfx1201 (Radeon AI PRO R9700)

Results produced on this hardware, correctness-gated bit-exact against a CPU reference before any speed was recorded:

| Lever | Result | How |
|---|---|---|
| `v_dot8_i32_iu4` int4 decode | **~2.2×** vs the dp4a route (0.038 ms vs 0.083 ms, N=14336×K=4096) | native 8-wide int4 dot; bit-exact vs CPU |
| `v_swmmac_i32_16x16x64_iu4` (K64 2:4 sparse) | **3.90×** kernel ceiling / **3.67×** full GEMM | wide-tile SWMMAC on RDNA4 |
| hipBLASLt int8 prefill (Q2_0) | **+15.6%** pp1024 | self-tuning per-shape algo cache |
| native fp8 (E4M3/E5M2) | weights + KV + MoE kernel, on-device | RDNA4 fp8 WMMA path |
| ISA exploitation sweep | **19/19** present matrix/dot instructions emitted (0 unused) | `unused-isa-sweep.sh` cross-ref |
| MXFP6 quant → GGUF bridge | PPL **11.12** (after fixing the build_ffn NULL-scale bug) | Quark → block_mxfp6 |

## The point

The agent is honest about this gap by construction: on any target, its first move is `detect` → `scan ISA` (assembler ground truth), so it *discovers* a part's real capability surface rather than trusting a table. The ASSUMED rows become MEASURED the moment the agent runs on that silicon. Never port a `gfx1201` conclusion to a part with different units — re-run the census.
