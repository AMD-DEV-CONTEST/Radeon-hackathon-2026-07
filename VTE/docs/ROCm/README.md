[← Back to README](../../README.md)

# ROCm / RDNA3 architecture reference

Original notes distilled from AMD's own official documentation, kept here as background for anyone (including future sessions) working on VTE's HIP kernels without wanting to re-read AMD's full reference manuals from scratch. These are summaries and interpretations in this project's own words, not reproductions of AMD's text; follow the links to the primary sources for the authoritative, complete version of anything here.

Written with VTE's specific kernels in mind (`gemv_q4k`, the FlashAttention/Split-KV family, `rmsnorm`, `RoPE`) on the hardware this project actually runs on: an RX 7600 (`gfx1102`, RDNA3, 32 CUs). Where a note ties back to something measured in this project, it links to [Performance](../PERFORMANCE.md) or [Known limitations](../LIMITATIONS.md).

On this page:

- [RDNA3 hardware architecture](RDNA3-ARCHITECTURE.md): work-group processors, compute units, SIMD32, LDS/GDS, the memory hierarchy, wave32/64, occupancy-relevant register file sizes
- [RX 7600 (gfx1102) official specifications](RX7600-SPECS.md): the exact numbers for the GPU this project is developed and measured on
- [HIP / ROCm programming model](HIP-PROGRAMMING-MODEL.md): how HIP's C++ abstractions (grid/block/thread) map onto the RDNA3 hardware concepts above

## Primary sources

Everything in this folder is derived from AMD's own official documentation, all still live at the time of writing:

- **"RDNA3" Instruction Set Architecture Reference Guide** (AMD document #70650, 15-August-2023): the canonical low-level reference for RDNA3's instruction set, register model, and hardware organization. Hosted at [docs.amd.com](https://docs.amd.com/v/u/en-US/rdna3-shader-instruction-set-architecture-feb-2023_0), also linked from [GPUOpen's architecture documentation index](https://gpuopen.com/amd-gpu-architecture-programming-documentation/) and [ROCm's own architecture docs](https://rocm.docs.amd.com/en/latest/conceptual/gpu-arch.html).
- **AMD GPU specifications** (ROCm documentation): official per-model hardware tables (compute units, LDS, cache sizes, register file sizes) for Instinct, Radeon, and Ryzen GPUs: <https://rocm.docs.amd.com/en/latest/reference/gpu-specs.html>.
- **Introduction to the HIP programming model** (ROCm/HIP documentation): the official CPU-vs-GPU and SIMT programming-model explanation: <https://rocm.docs.amd.com/projects/HIP/en/latest/understand/programming_model.html>.
- **GPUOpen AMD GPU architecture programming documentation** (index of official PDFs: ISA manuals for every generation, the RDNA3 MES scheduler firmware document, machine-readable ISA specs): <https://gpuopen.com/amd-gpu-architecture-programming-documentation/>.

AMD's ISA reference guide is published under AMD's own Specification Agreement (reproduced in the document itself): it may be used as a reference for designing products/software that interface with AMD hardware, and to give AMD feedback. It is not a license to redistribute the document itself. Nothing from it is reproduced verbatim here beyond short attributed phrases; read the PDF directly for anything beyond what's summarized in this folder.
