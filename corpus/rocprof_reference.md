# rocprof Field Reference and Usage Guide

`rocprof` is AMD's hardware performance counter profiler. It instruments GPU kernels
and reports detailed hardware metrics: occupancy, memory bandwidth, cache efficiency,
instruction throughput. Use it when `rocm-smi` and `torch.profiler` have narrowed
down the bottleneck to a specific kernel and you need hardware-level evidence.

---

## Basic Usage

```bash
# Collect default statistics for all kernels:
rocprof --stats python workload.py

# Collect specific hardware counters:
rocprof -i counters.txt python workload.py

# Output to CSV:
rocprof --stats -o results.csv python workload.py
```

---

## Key Output Fields from `--stats`

### Kernel Dispatch Table

| Field | Description |
|---|---|
| `KernelName` | Kernel function name |
| `Calls` | Number of times this kernel was called |
| `TotalDurationNs` | Total wallclock time across all calls |
| `AverageDurationNs` | Mean per-call time |
| `Occupancy` | Average wavefront occupancy (0.0–1.0) |

### Occupancy Field Interpretation

| Value | Meaning |
|---|---|
| 0.8–1.0 | Good — most CU slots are filled |
| 0.5–0.8 | Moderate — some occupancy limitation |
| < 0.5 | Low — register pressure, LDS overuse, or tiny blocks |

---

## Hardware Counter Reference

Counters are specified in a `counters.txt` file. Key counters:

### Memory Counters

| Counter | Description |
|---|---|
| `FETCH_SIZE` | Total bytes fetched from L2 (includes redundant fetches) |
| `WRITE_SIZE` | Total bytes written to L2 |
| `L2_CACHE_HIT` | L2 cache hit rate (higher = less VRAM traffic) |
| `L1_CACHE_HIT` | L1 cache hit rate |
| `VALU_STALL_CYCLES` | Cycles stalled waiting for memory data |

### Occupancy and Scheduling

| Counter | Description |
|---|---|
| `WAVES_IN_FLIGHT` | Average active wavefronts per CU |
| `VGPR_USED` | Vector general-purpose registers used per thread |
| `SGPR_USED` | Scalar registers used per thread |
| `LDS_USED` | LDS bytes used per block |

### Compute Counters

| Counter | Description |
|---|---|
| `VALU_OPS` | Vector ALU operations executed |
| `VMEM_OPS` | Vector memory operations (load/store) |
| `SALU_OPS` | Scalar ALU operations |

---

## Example: Diagnosing Memory Coalescing

```bash
cat counters.txt
pmc: FETCH_SIZE, L2_CACHE_HIT, VALU_STALL_CYCLES, WAVES_IN_FLIGHT

rocprof -i counters.txt -o coalescing_analysis.csv python workload.py
```

Signs of non-coalesced access in the output:
- `FETCH_SIZE` is much larger than the expected working set
- `L2_CACHE_HIT` is low (< 50%) — each fetch misses because addresses are non-sequential
- `VALU_STALL_CYCLES` is high — compute is waiting for memory

Signs of well-coalesced access:
- `FETCH_SIZE` ≈ (tensor_elements × element_size) — efficient
- `L2_CACHE_HIT` > 80%
- `VALU_STALL_CYCLES` < 20% of total cycles

---

## Example: Diagnosing Occupancy

```bash
cat counters.txt
pmc: VGPR_USED, LDS_USED, WAVES_IN_FLIGHT

rocprof -i counters.txt -o occupancy_analysis.csv python workload.py
```

| VGPR_USED per thread | Impact on occupancy (CDNA2) |
|---|---|
| ≤ 32 | Full occupancy (10 wavefronts per SIMD) |
| 33–48 | Reduced (8 wavefronts per SIMD) |
| 49–64 | Halved (6 wavefronts per SIMD) |
| > 128 | Very low occupancy |

---

## Example: Full Investigation Workflow

```bash
# Step 1: Identify which kernels take the most time
rocprof --stats -o step1.csv python workload.py

# Step 2: Focus on the top kernel — check memory efficiency
cat > mem_counters.txt << EOF
pmc: FETCH_SIZE, L2_CACHE_HIT, VALU_STALL_CYCLES
EOF
rocprof -i mem_counters.txt -o step2.csv python workload.py

# Step 3: Check occupancy limiters
cat > occ_counters.txt << EOF
pmc: VGPR_USED, LDS_USED, WAVES_IN_FLIGHT
EOF
rocprof -i occ_counters.txt -o step3.csv python workload.py
```

---

## rocprof vs torch.profiler

| | `rocprof` | `torch.profiler` |
|---|---|---|
| Level | Hardware counters | PyTorch op-level |
| Granularity | Per-kernel hardware metrics | Per-op time and memory |
| Ease of use | Requires counter config | Built into PyTorch |
| Best for | Deep hardware diagnosis | Finding which op to optimize |

**Recommended workflow**: Use `torch.profiler` to identify the slow ops,
then `rocprof` to understand the hardware-level cause.
