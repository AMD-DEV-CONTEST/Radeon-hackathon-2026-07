[← Back to ROCm reference](README.md) · [← Back to README](../../README.md)

# RDNA3 hardware architecture

Summarized from AMD's official **"RDNA3" Instruction Set Architecture Reference Guide** (document #70650, 15-August-2023), hosted at [docs.amd.com](https://docs.amd.com/v/u/en-US/rdna3-shader-instruction-set-architecture-feb-2023_0). This is an original summary in this project's own words, organized around what actually mattered for VTE's kernel work (`gemv_q4k`'s design, the LDS double-buffering question in [Performance](../PERFORMANCE.md#investigation-pushing-past-100-toks-2026-07), occupancy/VGPR budgets) — not a full reproduction of the reference guide, which runs to ~600 pages. Read the PDF directly for anything beyond this.

## Work-Group Processor (WGP) and Compute Unit (CU)

The GPU's processor array is organized as a set of independent **Work-Group Processor (WGP)** pipelines running in parallel. A WGP is "the basic unit of shader computation hardware, including scalar & vector ALUs and memory, as well as LDS and scalar caches" (ISA reference, §1.1 terminology table). A **Compute Unit (CU)** is *half* of a WGP: it contains 2 SIMD32 units that share one path to memory, so a full WGP has 4 SIMD32 units total.

This CU/WGP split matters for reading kernel-resource-usage output (`hipcc -Rpass-analysis=kernel-resource-usage`, used throughout the [Performance investigation](../PERFORMANCE.md)): occupancy is reported in "waves/SIMD", and a WGP has 4 SIMDs, not 2 — CU-count-based occupancy math (e.g. "blocks per CU") needs to account for that, and this project's own grid-sizing code (`HIPRuntime.get_num_cus()`, see [Performance: portability](../PERFORMANCE.md#portability-dynamic-compute-unit-detection-rdna2rdna3-not-just-the-rx-7600)) already treats CU count as the real hardware CU count (WGP-doubled), not WGP count.

The GPU hides memory latency "by keeping track of potentially hundreds of work-items in various stages of execution, and by overlapping compute operations with memory-access operations" (ISA reference, §1.2.1) — this is the hardware mechanism behind why `gemv_q4k`'s occupancy (16 waves/SIMD, hundreds of blocks queued per CU on this project's RX 7600) already does most of the latency-hiding work that explicit software prefetching or LDS double-buffering would otherwise be needed for. See the LDS double-buffering rejection in [Performance](../PERFORMANCE.md#investigation-pushing-past-100-toks-2026-07) for where this showed up concretely.

## Wave32 and Wave64

A **wave** (wavefront) is a collection of 32 or 64 work-items executing in lockstep. RDNA3 supports both wave32 and wave64, but a shader must be *compiled* for one or the other; it's a static choice, not something that varies per-dispatch based on how many work-items happen to be active.

- **Wave32**: each vector instruction is issued once, covering all 32 work-items.
- **Wave64**: vector/vector-memory instructions are issued *twice* (once for work-items 0-31, once for 32-63) while scalar ALU/memory, branches, and messages are issued once regardless of wave size.

VTE's kernel templates consistently use `warpSize` (32 on RDNA3/wave32) for reductions (`__shfl_down`, `__shfl_xor`) rather than a hardcoded constant, which is what makes those reductions portable to CDNA/wave64 hardware in principle, though this project has only ever measured on wave32 RDNA hardware (see the RDNA2 portability discussion in [Known limitations](../LIMITATIONS.md#hardware-portability) for how far that portability claim has actually been tested: simulated CU-count scaling, no real RDNA2 silicon).

## Local Data Share (LDS) and Global Data Share (GDS)

Each WGP has a **128KB** LDS ("local data share"), organized as 64 banks × 512 entries × 4 bytes, described in the ISA reference as usable "as a software cache for predictable re-use of data, a data exchange machine for the work-items of a work-group, or as a cooperative way to enable efficient access to off-chip memory" (§1.2.2.1). A single work-group may allocate up to 64KB of it. This 128KB-per-WGP figure is independently confirmed by ROCm's own [GPU specifications table](RX7600-SPECS.md) (`LDS (KiB): 128` for every RDNA3 SKU including the RX 7600).

Two LDS allocation modes exist, selectable per-dispatch:

- **CU mode**: LDS is split into separate upper/lower halves, each serving 2 SIMD32s (one CU). Faster (both halves run independently in parallel) but a work-group's waves must all stay within one CU's half, with no cross-CU data sharing within the WGP.
- **WGP mode**: LDS is one contiguous space all 4 SIMD32s in the WGP can access, letting a work-group's waves spread across both CUs. Required for cross-CU sharing within a WGP, at the cost of the parallelism CU mode gets from independent halves.

**GDS** (Global Data Share) is a separate, much smaller (4KB) memory shared across *all* WGPs on the device, intended for cross-WGP coordination (reductions, append/consume operations) rather than bulk data caching, which is not something VTE's current kernels use.

This is the primary-source backing for the structural argument in [Performance's LDS double-buffering rejection](../PERFORMANCE.md#investigation-pushing-past-100-toks-2026-07): LDS is genuinely scoped to a work-group/CU, not the whole device, so it categorically cannot help with the *cross-block* redundant reads of the activation vector `X` that `gemv_q4k` has (every block reads the same `X`, but LDS can't be shared between blocks unless they're explicitly co-scheduled and the kernel is restructured around it); only the hardware L1/L2 cache hierarchy (below) can serve that role automatically.

## Memory hierarchy

On the read path: **L2 cache** (multiple channels, device-wide) → **L1 caches** (read-only) → **L0 caches** (per-WGP). The ISA reference notes that "specific cache-less load instructions can force data to be retrieved from device memory" bypassing this hierarchy when needed, and that overlapping load requests within the same clause are cached with respect to each other (§1.2.3).

On the write/atomic path, there are two cache levels: a write-combining cache (batches scatter/store operations into efficient memory-access patterns) and a read/write cache with atomic units supporting unordered atomic accesses that return the pre-operation value.

For the RX 7600 specifically, [ROCm's GPU specifications table](RX7600-SPECS.md) gives concrete sizes: 32MB Infinity Cache (this document's ISA reference doesn't name it "Infinity Cache" directly, which is AMD's marketing term for the large last-level cache; the ROCm spec table uses it as a column header), 2MB L2, 256KB "Graphics L1 Cache", plus per-WGP L0 vector/scalar/instruction caches. The 32MB Infinity Cache figure is the same number this project's [Performance doc](../PERFORMANCE.md#batched-decode) already cited (from general knowledge, not an official source at the time) as the likely explanation for the batch=8 batched-decode regression, which is now backed by an official citation instead.

## Wave state and register files

Each wave has its own private register state (ISA reference, Chapter 3, "Wave State"):

- **VGPR** (Vector General Purpose Registers): V0-V255, 32 bits each, private per work-item. This is what `hipcc -Rpass-analysis=kernel-resource-usage`'s "VGPRs: N" line reports per kernel, representing the number of these 32-bit registers a single work-item's share of the kernel actually uses. This project's kernel-resource-usage audit ([Performance](../PERFORMANCE.md#investigation-pushing-past-100-toks-2026-07)) found `gemv_q4k` at 37 VGPRs, the attention kernels at 11-22, which are all far below the 256 architectural maximum, consistent with the zero-spill, max-occupancy result measured there.
- **SGPR** (Scalar General Purpose Registers): S0-S105 plus 16 TTMPs, 32 bits each, shared by all work-items in a wave (used for control flow and values uniform across the wave).
- **EXEC**: a 64-bit per-wave mask controlling which work-items are active for a given vector instruction (the hardware mechanism behind divergent branches: inactive lanes execute as a NOP rather than the GPU actually branching).

[ROCm's GPU specifications table](RX7600-SPECS.md) gives the RX 7600's total per-SIMD register file sizes: 512KiB VGPR file, 32KiB SGPR file. How many waves can be simultaneously resident on a SIMD (occupancy) is ultimately bounded by how many waves' worth of VGPRs/SGPRs/LDS fit in these fixed-size files, which is exactly what `hipcc`'s "Occupancy [waves/SIMD]" resource-usage line is computing for a given kernel's register footprint.
