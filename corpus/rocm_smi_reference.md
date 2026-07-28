# rocm-smi Field Reference

`rocm-smi` is the AMD ROCm System Management Interface. It reports live GPU
hardware metrics and is the primary tool for understanding GPU state during
a performance investigation.

---

## Basic Usage

```bash
# Show all GPU info (default view):
rocm-smi

# JSON output (for programmatic parsing):
rocm-smi --json

# Continuous monitoring (refresh every N seconds):
rocm-smi -d 0 --showallinfo --loop N

# Show specific metrics:
rocm-smi --showuse        # GPU utilization %
rocm-smi --showmemuse     # VRAM usage
rocm-smi --showclocks     # Clock speeds
rocm-smi --showtemp       # Temperature
rocm-smi --showpower      # Power draw
```

---

## Key Fields and Their Meaning

### GPU Utilization (`GPU use (%)`)

Percentage of time the GPU compute units were active (not idle) during
the sampling interval.

| Value | Interpretation |
|---|---|
| 90–100% | Compute-bound or well-utilized |
| 50–90% | Moderate utilization — possible memory stalls |
| < 50% | Likely memory-bound, occupancy issue, or CPU bottleneck |

**Important**: High utilization ≠ high efficiency. A GPU can be 70% "busy"
while spending most of that time doing redundant memory transactions due to
non-coalesced access. Utilization tells you the GPU is awake; profiler traces
tell you what it's doing.

### VRAM Usage (`VRAM Total Used Memory (B)`)

Total GPU memory (HBM/GDDR) currently allocated.

| Situation | Action |
|---|---|
| Near 100% | Risk of OOM; reduce batch size or model size |
| 60–80% | Healthy range |
| < 30% | Room to increase batch size for better throughput |

### Memory Bandwidth Utilization

Not shown directly by `rocm-smi` — use `rocprof` for bandwidth.
A rough proxy: if GPU utilization is low and the workload should be compute-
heavy, the bottleneck is likely memory bandwidth.

### Clock Speeds (`sclk`, `mclk`)

| Field | Description |
|---|---|
| `sclk` | Shader clock (compute units) in MHz |
| `mclk` | Memory clock (VRAM) in MHz |

If clocks are throttled below the GPU's rated boost clock, check:
- Temperature throttling (`--showtemp`)
- Power limit throttling (`--showpower`)
- `ROCR_VISIBLE_DEVICES` correctly set

### Temperature (`Temperature (Sensor junction) (C)`)

The hotspot (junction) temperature is the most relevant for throttling decisions.

| Value | Status |
|---|---|
| < 80°C | Normal |
| 80–100°C | Hot — may throttle soon |
| > 100°C | Throttling actively — sustained at this level is a problem |

### Power Draw (`Average Graphics Package Power (W)`)

Compare against the GPU's TDP (thermal design power). If consistently at TDP
limit, the GPU may be power-throttling clock speeds.

---

## Reading rocm-smi JSON Output

```bash
rocm-smi --json > smi_output.json
```

The JSON structure uses `card0`, `card1`, etc. as top-level keys. Example:

```json
{
  "card0": {
    "GPU use (%)": "87",
    "VRAM Total Memory (B)": "25769803776",
    "VRAM Total Used Memory (B)": "16106127360",
    "Temperature (Sensor junction) (C)": "72",
    "Average Graphics Package Power (W)": "315.0",
    "sclk clock speed:": "2500Mhz",
    "mclk clock speed:": "2400Mhz"
  }
}
```

Note: values are strings, not numbers — always cast before arithmetic.

---

## Common Investigation Patterns

### Pattern 1: Is this compute-bound or memory-bound?

```bash
rocm-smi --showuse --showmemuse
```

- High GPU use (>90%) + low memory use → compute-bound
- Moderate GPU use (<60%) + high memory throughput → memory-bound

### Pattern 2: Is there thermal throttling?

```bash
rocm-smi --showtemp --showclocks
```

If temperature is high and clocks are below rated boost, it's thermal throttling.

### Pattern 3: VRAM pressure

```bash
rocm-smi --showmemuse
```

If VRAM is near capacity, reduce batch size before any kernel tuning.

---

## rocm-smi vs rocprof

| Tool | What it shows | When to use |
|---|---|---|
| `rocm-smi` | Live system-level GPU state | Quick health check, utilization, VRAM, temp |
| `rocprof` | Per-kernel hardware counters (occupancy, memory bandwidth, cache hits) | Deep diagnosis of a specific kernel |

For serious kernel analysis, always follow up `rocm-smi` with `rocprof --stats`.
