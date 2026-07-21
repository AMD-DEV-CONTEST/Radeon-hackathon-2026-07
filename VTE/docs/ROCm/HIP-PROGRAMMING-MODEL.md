[← Back to ROCm reference](README.md) · [← Back to README](../../README.md)

# HIP / ROCm programming model

Summarized from ROCm's official **"Introduction to the HIP programming model"** documentation: <https://rocm.docs.amd.com/projects/HIP/en/latest/understand/programming_model.html>. Original summary in this project's own words, framed around how it relates to VTE's own HIP usage (raw `ctypes` calls into `amdhip64.dll`, no C++ HIP compilation at runtime for the launch path itself — only for AOT kernel compilation via `hipcc`, see [Architecture](../ARCHITECTURE.md)).

## Why GPUs are shaped the way they are

The official docs frame the CPU/GPU split around **latency vs. throughput**: a CPU is built to finish a single instruction stream as fast as possible (few, powerful cores; high clocks; large per-core caches; complex branch prediction; expensive context switches since a thread's register state has to be spilled to memory to free the register file for another thread). A GPU is built to have as many operations in flight as possible, not to finish any single one quickly (many simple cores; lower clocks; small caches but *many* registers; and — importantly — near-free context switching, because "all threads that run on a core/compute unit have their registers on the compute unit, so they don't need to be stored to global memory, and each cycle one instruction from any wavefront that resides on the compute unit can be issued").

That last point is the direct hardware justification for why occupancy (how many wavefronts are simultaneously resident, see [RDNA3 architecture: Wave state and register files](RDNA3-ARCHITECTURE.md#wave-state-and-register-files)) is the primary latency-hiding mechanism on this hardware, and why this project's kernel investigation ([Performance](../PERFORMANCE.md#investigation-pushing-past-100-toks-2026-07)) treated "is occupancy already maximal" as the first and most important question before considering any instruction-level software-pipelining trick — a GPU with spare resident wavefronts can switch to one that has data ready essentially for free, which is a fundamentally cheaper way to hide a stalled memory load than anything a single wave's own instruction stream can do internally.

## SIMT: single instruction, multiple threads

Multiple ALUs execute a group of threads running the same instruction stream in lockstep — AMD's term for this group is a **wavefront** (elsewhere in the industry: a "warp"). The collection of ALUs that executes a wavefront is a **SIMD**. This is why divergent branches are expensive: when threads in the same wavefront take different paths, the hardware still walks every path for the whole wavefront, masking out the lanes that shouldn't be active on each path — cycles are spent on the *masked-out* lanes too, not skipped. The official guidance is direct: "Keep instructions consistent and leave conditionals out of threads [where possible]."

None of VTE's hot-path decode kernels (`gemv_q4k`, `rmsnorm`, the Split-KV attention family) have significant per-work-item branching in their inner loops — the closest thing is the boundary checks (`if (row >= out_features...) return;`) that only diverge at a wavefront's tail, not throughout the loop body.

## Heterogeneous programming: host and device execution contexts

A HIP program has two execution contexts, marked by `__host__` and `__global__`/`__device__` decorators in C++ HIP code: host code follows the ordinary C++ abstract machine (unified address space), while device code follows the SIMT model above, with its own memory namespaces (`__shared__`/LDS, global, constant) that don't mean anything from the host side.

VTE's actual architecture sidesteps writing `__host__` HIP C++ almost entirely: kernel *bodies* are HIP C++ compiled ahead-of-time by `hipcc` into `.hsaco` binaries (`vte/compiler/codegen.py`, `vte/compiler/templates/*.hip.template`), but the *launch* side — building the kernel-argument list, computing grid/block dimensions, calling `hipModuleLaunchKernel`/`hipGraphLaunch` — is plain Python via `ctypes` bindings directly against `amdhip64.dll` (`vte/bridge/hip_runtime.py`), not a compiled HIP host program. This is the project's core engineering bet described in the [Performance doc's Ollama/llama.cpp comparison](../PERFORMANCE.md#benchmark-vte-vs-ollama-llamacpp): that CPU-side dispatch overhead is an engineering problem you can profile and remove (HIP Graphs eliminate most of the per-launch Python/driver round-trip), not an inherent tax Python has to pay for driving the device context.

## Terminology bridge: HIP C++ ↔ RDNA3 hardware

For anyone reading VTE's `.hip.template` kernels alongside the [RDNA3 architecture](RDNA3-ARCHITECTURE.md) notes, the HIP/CUDA-style programming-model terms map onto AMD's own hardware terms roughly as:

| HIP C++ term | RDNA3 hardware term |
|---|---|
| Thread / work-item | One lane of a wavefront |
| Warp | Wavefront (32 or 64 work-items, see [Wave32 and Wave64](RDNA3-ARCHITECTURE.md#wave32-and-wave64)) |
| Block / work-group | A collection of wavefronts that can share LDS and synchronize via `__syncthreads()`/barriers |
| Grid / dispatch | The full launch: all blocks for one kernel invocation |
| `__shared__` memory | LDS (Local Data Share, see [LDS and GDS](RDNA3-ARCHITECTURE.md#local-data-share-lds-and-global-data-share-gds)) |
| SM (CUDA term, not used by AMD) | Compute Unit (CU) / Work-Group Processor (WGP), see [WGP and CU](RDNA3-ARCHITECTURE.md#work-group-processor-wgp-and-compute-unit-cu) |

Source: <https://rocm.docs.amd.com/projects/HIP/en/latest/understand/programming_model.html> (ROCm/HIP documentation). Read it directly for the sections not summarized here (unified memory management, virtual memory management, the Stream Ordered Memory Allocator).
