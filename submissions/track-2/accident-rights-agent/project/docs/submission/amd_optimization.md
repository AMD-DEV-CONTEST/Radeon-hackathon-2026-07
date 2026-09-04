# AMD Radeon Optimization Report

Measured on Radeon Cloud: 2026-08-01
Evidence directory: `benchmarks/results/`
Fair-comparison source commit: `0ce3564`

## 1. Environment

- GPU: Navi31 `gfx1100`, 96 CUs, 48 GB GDDR6;
- ROCm 7.2.1, amdgpu 6.16.13;
- Python 3.10.12, PyTorch ROCm `2.9.1+gitff65f5b`;
- vLLM `0.16.1.dev0+g89a77b108.d20260318`;
- model: Qwen3-VL-8B-Instruct;
- endpoint: `http://127.0.0.1:8000/v1`;
- model fingerprint:
  `cec420e03b2df4db1f120faed9a7a2c302c2d5ecb65ccab2085c2c5e561be6dc`.

## 2. Fair Baseline

Both groups use the same model, hardware, Golden Case, request order,
`temperature=0`, output limit, and evaluator.

**Baseline:** full case history; Prefix Cache disabled;
`max_model_len=16384`; `gpu_memory_utilization=0.90`; default vLLM batch
behavior; full tool-result fields.

**Optimized comparison:** Case Capsule and dynamic task context; Prefix Cache
enabled; `max_model_len=16384`; `gpu_memory_utilization=0.90`; batch tokens
16,384; required tool-result fields only.

The final configuration used for interactive and 30-minute validation is:

```text
gpu_memory_utilization = 0.95
max_num_batched_tokens = 8192
max_model_len = 16384
enable_prefix_caching = true
```

## 3. Baseline vs Optimized

| Metric | Baseline | Optimized | Change |
|---|---:|---:|---:|
| Input tokens | 11,808 | 5,795 | -50.9% |
| TTFT p50 | 9.003 s | 0.113 s | -98.8% |
| TTFT p95 | 9.007 s | 0.113 s | -98.7% |
| TPOT p50 | 0.040 s/token | 0.039 s/token | slight improvement |
| Latency p95 | 23.407 s | 15.228 s | -34.9% |
| Output throughput | 15.417 tok/s | 25.689 tok/s | +66.6% |
| Mean GPU utilization | 99.533% | 100.000% | - |
| Peak VRAM | 44,246 MB | 43,984 MB | -262 MB |
| Success / OOM | 100% / 0 | 100% / 0 | pass |
| Quality score | 93.571 | 96.364 | not below baseline |
| ProtectedField retention | 100% | 100% | pass |

### Verifier interpretation

The comparison load fixes output length for performance measurement and does
not request the complete business ID list required by the semantic evaluator.
Both comparison groups therefore report `verifier_pass_rate=0`. This is not
presented as a business-quality pass. The full semantic concurrency 1/2/4
workload uses the optimized input and achieves 100% Verifier pass rate and a
quality score of 100.

## 4. Prefix Cache

For the second question on a repeated case, TTFT fell from 9.002 seconds to
0.104 seconds, a 98.8% improvement. The vLLM log recorded a peak Prefix Cache
hit rate of 99.4%. This benefit depends on a stable shared system prefix, tool
definitions, and case-material prefix. Different cases or frequently changing
prefixes should not be expected to achieve the same hit rate.

## 5. Case Capsule and Token Compression

The Case Capsule includes only task-relevant facts, required Evidence/Law IDs,
protected fields, and workflow state. Raw evidence is never lossily compressed.
Before and after context selection, the workflow compares dates, deadlines,
amounts, liability ratios, vehicle identifiers, party roles, Fact/Evidence/Law
IDs, legal versions, and approval status. Any mismatch blocks the node.

The final AMD comparison reduces tokens by 50.9%. An earlier isolated memory
experiment reported 25.32%; the baseline input and optimization configuration
were different, so the two values are not combined.

## 6. `gpu_memory_utilization`

| Parameter | Success | TTFT p50 | Throughput | Peak VRAM | OOM |
|---:|---:|---:|---:|---:|---:|
| 0.80 | 100% | 0.103 s | 48.776 tok/s | 39,588 MB | 0 |
| 0.85 | 100% | 0.103 s | 48.866 tok/s | 42,036 MB | 0 |
| 0.90 reference | 100% | 0.136 s | 49.322 tok/s | 43,984 MB | 0 |
| 0.95 | 100% | 0.136 s | 48.921 tok/s | 46,932 MB | 0 |

0.95 is the highest value validated for 30 minutes without OOM on this
instance, but it leaves approximately 2.4 GB headroom. A production rollout
should begin at 0.85 and increase only after testing representative multi-image
loads.

## 7. Batch Tokens

| Batch tokens | Success | TTFT p50 | Throughput | Peak VRAM | OOM |
|---:|---:|---:|---:|---:|---:|
| 8,192 | 100% | 0.134 s | 49.320 tok/s | 43,868 MB | 0 |
| 16,384 reference | 100% | 0.136 s | 49.322 tok/s | 43,984 MB | 0 |
| 32,768 | 100% | 0.106 s | 48.631 tok/s | 41,539 MB | 0 |

The final interactive configuration uses 8,192 to preserve scheduling
headroom. This is not a claim that 8,192 maximizes throughput for every load.

## 8. Context Length

The 16K reference and 32K groups use the same case and evaluator. The 32K group
maintains success and quality, with approximately 25.407 tok/s throughput and
44,498 MB peak VRAM. Dynamic memory makes 16K sufficient for the business
input, so the final configuration avoids unnecessary KV Cache allocation.

## 9. Concurrency 1/2/4

Each level runs 20 formal requests with the full business semantic evaluator:

| Concurrency | Success | TTFT p50/p95 | TPOT p50/p95 | Mean/p95 latency | Throughput | Verifier | OOM |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20/20 | 0.111/0.112 s | 0.0388/0.0388 s | 15.152/15.160 s | 25.667 tok/s | 100% | 0 |
| 2 | 20/20 | 0.113/0.116 s | 0.0401/0.0401 s | 15.559/15.668 s | 49.323 tok/s | 100% | 0 |
| 4 | 20/20 | 0.120/0.121 s | 0.0445/0.0445 s | 17.386/17.401 s | 89.478 tok/s | 100% | 0 |

Concurrency 4 provides 3.49 times the throughput of concurrency 1 while mean
latency increases by approximately 14.7%.

## 10. 30-Minute Stability

- duration: 1,809.493 seconds;
- requests: 298/298, 100% success;
- OOM: 0 in the runner and vLLM log;
- unchanged vLLM PID;
- UI/API returned HTTP 200 before and after;
- SQLite checkpoint `quick_check=ok` before and after;
- mean/peak GPU utilization: 99.626% / 100%;
- peak VRAM: 46,744 MB;
- peak power: 224 W;
- peak edge/hotspot/VRAM temperature: 54/61/60 C.

The stability runner uses a fixed short output. Its Verifier value and quality
score demonstrate neither legal nor business quality; the workload proves
service, GPU, memory, UI/API, and SQLite stability only.

## 11. Security Results

Code scanning found no public model Base URL or cloud API-key pattern. The
measured request to `http://127.0.0.1:8000/v1/models` returned HTTP 200, and the
process/listener evidence confirms loopback binding. Demo privacy scanning found
no unredacted real name, telephone number, or identity-card number.

## 12. Limitations

1. Results use one Navi31 48 GB GPU, one 8B model, and synthetic Golden Cases.
2. Prefix Cache gains depend on repeated prompt prefixes.
3. The 0.95 memory setting has limited headroom.
4. Synthetic Demo materials do not establish real-world recognition accuracy.
5. Quality and Verifier scores are engineering gates, not legal correctness.
6. Raw JSON/CSV and vLLM logs take precedence if this summary differs from the
   underlying evidence.
