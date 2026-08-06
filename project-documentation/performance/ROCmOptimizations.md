# AMD RDNA3 Inference Optimization

## Summary

FastAgentFactory maintains an immutable Official llama.cpp baseline and an AMD implementation built from the same source revision. The AMD path targets RDNA3/gfx1100 with native HIP kernels and fusion work while preserving the same model files, inference profiles, and public APIs.

The measured work has two distinct layers:

1. **Kernel and graph improvements** reduce memory traffic, launch overhead, or per-token work in the AMD implementation.
2. **MTP speculative decoding** changes the decode schedule by validating multiple candidate tokens in one target-model forward pass.

Normal service benchmarks provide user-facing throughput. rocprof and GGML traces are used only to attribute cost and confirm dispatch; profiler duration is never presented as normal service speed.

The performance claim is intentionally split into two scopes:

- **Non-MTP single-token Decode:** AMD improved Decode throughput by `5.64%` over Official.
- **MTP enabled for both implementations:** Decode was effectively tied, while AMD improved Prompt throughput by `16.70%`, reduced model-compute TTFT by `14.31%`, and improved two-client QPS by `5.09%`.

The same MTP-enabled paired run reduced mean request latency by `4.89%`. MTP changes the workload into proposal generation and multi-token target validation for both implementations, so its scheduling gain is not presented as an AMD-kernel gain.

## Experimental Discipline

Official and AMD comparisons use the same:

- GGUF and multimodal projector
- inference profile and context allocation
- KV cache types and Flash Attention state
- prompt and output-token limit
- temperature, seed, and sampling parameters
- cache policy and warm-up procedure
- client concurrency for QPS runs

Implementation identity is read from the active build revision and binary metadata. A benchmark cannot label a run as AMD or Official by user input alone.

## Overall Comparison with Official

The representative same-condition non-MTP service comparison recorded:

| Implementation | Decode throughput | Relative result |
| --- | ---: | ---: |
| Official | 84.0867 tok/s | baseline |
| AMD | 88.8320 tok/s | +5.64% |

This result applies to the archived Qwen3.6 APEX GGUF, RDNA3/gfx1100 GPU, ROCm stack, and tested shapes. It is not a general performance guarantee.

## Optimization 1: Reuse Q8_1 Activation Quantization

### Official Behavior

Quantized MatVec kernels multiply quantized weights by a temporary Q8_1 representation of the F32 activation. In the baseline path, compatible MatVec dispatches can quantize the same activation repeatedly, launching additional quantization kernels and rereading the same input.

### AMD Behavior

The AMD implementation caches the temporary quantization result inside the valid execution lifetime and reuses it only when tensor identity, shape, type, device, and ownership match. The cache is invalidated when the activation or execution boundary changes.

### Why It Helps RDNA3 Decode

Single-token decode is dominated by repeated weight-streaming MatVec work. Removing redundant activation quantization reduces small-kernel launches and memory traffic surrounding the dominant MatVec kernels without changing the mathematical result.

## Optimization 2: Fuse Residual Add, RMSNorm, and Scale

### Official Behavior

The graph normally executes separate operations:

```text
residual = input + branch
normalized = rms_norm(residual)
output = normalized * weight
```

Each operation can launch a kernel and materialize intermediate values in global memory.

### AMD Behavior

The AMD graph matcher recognizes only the exact safe pattern with compatible contiguous tensors, supported type/shape, and single-consumer ownership. A native HIP kernel:

1. loads input and branch values;
2. computes the residual;
3. reduces the sum of squares within the workgroup;
4. applies inverse RMS and the learned weight;
5. writes the final output while preserving the residual value required by the graph.

The implementation uses RDNA3-aware vectorized access and wave reduction where valid. Unsupported layouts or graph ownership fall back to the original operations.

### Benefit and Boundary

Fusion reduces kernel launches and intermediate global-memory round trips. It does not change the model architecture, normalization epsilon, or residual semantics. The optimization is enabled only when the graph matcher proves equivalence.

## Optimization 3: Native RDNA3 Q6_K × Q8_1 MMVQ

### Baseline Bottleneck

Decode is autoregressive: one newly accepted token repeatedly invokes quantized matrix-vector multiplication over large weight matrices. For Q6_K weights, the operation is primarily constrained by weight bandwidth, dequantization, dot-product instruction efficiency, and launch scheduling.

### AMD Native Path

The AMD implementation adds a dedicated HIP kernel for supported RDNA3 shapes rather than relying only on the shared CUDA-derived template path. It preserves Q6_K block semantics and Q8_1 scale/zero-point correction while adapting execution to AMD wave behavior.

Key changes include:

- Wave32-oriented lane mapping for the selected shape family
- vectorized and coalesced weight/activation access
- register-resident partial accumulation
- two accumulation chains to expose instruction-level parallelism
- explicit Q8_1 scale and correction handling
- guarded block prefetch where it reduces dependency stalls

The dispatcher uses weight type, activation type, architecture, and shape constraints. It falls back to the baseline kernel for unsupported variants.

### What the Optimization Does Not Do

It does not convert single-token GEMV into GEMM by definition, and it cannot eliminate reading the model weights. Its goal is to make the unavoidable Q6_K weight stream and dot product more efficient on RDNA3.

## Optimization 4: Dynamic Wave32/Wave64 MMVQ Evaluation

Different shapes can favor Wave32 or Wave64 because lane utilization, register pressure, reduction structure, and occupancy differ. FastAgentFactory records the selected wave variant and evaluates it under identical service conditions.

The final production path keeps only variants that demonstrate a repeatable service-level benefit. Experimental scheduling changes that do not improve throughput are removed rather than accumulated as permanent branches.

## RDNA3 MMQ Output-column Tiling

Multi-column target validation and Prefill can use matrix-matrix quantized kernels rather than the single-vector path. The AMD experiment evaluates output-column tiling, register reuse, and workgroup geometry for RDNA3. This path is treated separately from MMVQ because its arithmetic intensity, LDS use, and occupancy constraints differ.

No MMQ change is presented as successful unless the actual kernel dispatch is observed and normal service or benchmark throughput improves under repeated paired runs.

## MTP Speculative Decoding

The selected Qwen3.6 GGUF retains NextN/MTP layers. When enabled, llama-server starts with `--spec-type draft-mtp`. The MTP head proposes up to three candidate tokens and the target model validates them together. No second draft model is required.

The runtime considers MTP active only when llama-server slots report `speculative=true`. Benchmark results read the actual candidate and accepted-token counts from llama.cpp timings; configuration alone is not treated as proof of activation.

MTP improves throughput because one target forward pass can accept multiple tokens, amortizing model-weight reads, MMVQ, MoE routing, elementwise kernels, and launch overhead. It does not make an individual MMVQ read fewer weights and adds work in the MTP proposal head.

Earlier MTP on/off measurements remain useful for understanding speculative scheduling, but they are not used as an AMD-versus-Official kernel claim. AMD attribution comes only from paired Official/AMD runs with the same MTP state. A single-token MMVQ advantage does not automatically carry into the multi-token validation path; the MTP proposal head and target multi-token path must be attributed independently.

### Latest Ten-round Paired Experiment with MTP Enabled

The latest experiment group, completed on July 22, 2026, used the same long prompt, `max_output_tokens=256`, `temperature=0`, `seed=42`, a cold prompt cache, one warm-up, and three measured iterations. Concurrency used two client requests. Each of ten rounds ran Official and AMD performance, concurrent QPS, and operator analysis, completing all `60 / 60` sub-experiments. MTP was enabled for both implementations, so this measures the complete MTP-enabled service path rather than an isolated single-token MMVQ path.

| Metric, ten-round mean | Official | AMD | AMD relative change |
| --- | ---: | ---: | ---: |
| Decode TPS | 123.897 tok/s | 124.111 tok/s | **+0.17%** |
| Prompt TPS | 1460.670 tok/s | 1704.649 tok/s | **+16.70%** |
| Model-compute TTFT | 540.873 ms | 463.456 ms | **-14.31%** |
| MTP acceptance rate | 66.54% | 64.62% | -1.92 percentage points |
| Two-client QPS | 0.3788 req/s | 0.3981 req/s | **+5.09%** |
| Aggregate output TPS | 96.97 tok/s | 101.91 tok/s | **+5.09%** |
| Mean request latency | 4626.39 ms | 4399.97 ms | **-4.89%** |
| Error rate | 0% | 0% | Equal |

The accurate conclusion is: **with MTP enabled, AMD Decode is effectively tied with Official but retains a small `0.17%` gain; this is not a significant Decode improvement.** The clearer AMD gains are in Prompt/Prefill and two-client aggregate throughput. MTP changes per-token MMVQ execution into proposal generation plus multi-token target validation, and AMD's acceptance rate was 1.92 percentage points lower in this group. This dilutes the previously measured `5.64%` single-token Decode gain without MTP. The results are not contradictory: `5.64%` describes autoregressive Decode with MTP disabled, while `0.17%` describes the latest complete MTP-enabled service path.

The correctness check hashed the complete `reasoning_content + content` output. AMD MTP on/off and Official MTP on matched for this run, while Official without MTP diverged under greedy execution. The result is retained as a floating-point/batching-path boundary; it is not claimed that all four paths are bitwise identical.

## Concurrent QPS

The concurrency benchmark uses closed-loop workers. A worker sends its next request only after the previous request completes. With one llama-server slot, client concurrency above one measures queue pressure rather than multiple model slots executing simultaneously.

| Implementation with MTP | Client concurrency | QPS | Aggregate output TPS | Mean request latency |
| --- | ---: | ---: | ---: | ---: |
| Official | 1 | 0.5751 | 73.61 tok/s | 1.739 s |
| Official | 2 | 0.6040 | 77.31 tok/s | 2.907 s |
| Official | 4 | 0.6055 | 77.51 tok/s | 5.394 s |

QPS is successful requests divided by the measured time window. Aggregate output TPS is all generated tokens divided by the same window and is not the same metric as single-request Decode TPS.

## Dispatch and Attribution

Stable kernel ids are defined in a kernel catalog with labels, descriptions, architecture support, quantization variants, and shape constraints. Runtime counters distinguish:

- graph eligibility;
- dispatcher selection;
- actual kernel launch;
- fallback and its reason.

Operator analysis records GGML graph operations, backend assignment, HIP kernel families, host shapes, quantization types, and launch configuration. A host record is paired with GPU timing only when event counts align; mismatches are reported rather than guessed.

## Limitations

- The native paths have been evaluated on RDNA3/gfx1100; other architectures use baseline paths unless explicitly supported.
- Benefits depend on model quantization, layer shapes, context, slots, KV cache, and ROCm version.
- MTP benefit depends strongly on candidate acceptance rate.
- Operator profiling disables HIP Graph replay for attribution and must not be compared directly with normal service timing.
- Only successful, reproducible implementation changes belong in the final AMD difference; failed experiments are removed instead of being presented as optimization work.
