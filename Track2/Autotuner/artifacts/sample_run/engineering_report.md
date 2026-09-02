# Autotuner Engineering Report

Evidence status: Simulation only. This artifact validates the software flow and does not report measured Radeon performance.

## Executive result

Autotuner evaluated 10 serving configurations on Simulated AMD Radeon GPU. The best accepted configuration reached 41.41 output tokens per second. The baseline reached 21.32 output tokens per second. The measured improvement was 94.3 percent.

## Method

The agent measured every candidate against the same prompt set, generation length, concurrency, quality floor, error limit, and latency limit. It used the model running on the active Radeon deployment to choose the next controlled experiment when local agent mode was available.

## Winning configuration

```json
{
  "engine": "vllm",
  "environment": {
    "VLLM_ATTENTION_BACKEND": "ROCM_AITER_UNIFIED_ATTN"
  },
  "arguments": {
    "model": "Qwen/Qwen3-8B",
    "max_model_len": 4096,
    "max_num_seqs": 16,
    "gpu_memory_utilization": 0.92,
    "kv_cache_dtype": "fp8",
    "quantization": "none"
  }
}
```

## Changes from baseline

1. attention_backend: auto to ROCM_AITER_UNIFIED_ATTN
2. kv_cache_dtype: auto to fp8
3. max_num_seqs: 4 to 16
4. gpu_memory_utilization: 0.82 to 0.92

## Trial evidence

<table>
<thead><tr><th>Trial</th><th>Candidate</th><th>Tokens per second</th><th>P95 ms</th><th>Error rate</th><th>Quality</th><th>Decision</th></tr></thead>
<tbody>
<tr><td>1</td><td>c942c2955d44</td><td>21.32</td><td>1466.0</td><td>0.000</td><td>1.000</td><td>Accepted</td></tr>
<tr><td>2</td><td>ba066e28a226</td><td>25.98</td><td>1202.6</td><td>0.000</td><td>1.000</td><td>Accepted</td></tr>
<tr><td>3</td><td>4fde2c1fb72e</td><td>28.97</td><td>1078.5</td><td>0.000</td><td>0.990</td><td>Accepted</td></tr>
<tr><td>4</td><td>9457494c7047</td><td>23.59</td><td>1324.5</td><td>0.080</td><td>0.990</td><td>Rejected</td></tr>
<tr><td>5</td><td>268909f43cda</td><td>38.40</td><td>813.8</td><td>0.000</td><td>0.990</td><td>Accepted</td></tr>
<tr><td>6</td><td>3d76894d750a</td><td>34.47</td><td>906.5</td><td>0.000</td><td>1.000</td><td>Accepted</td></tr>
<tr><td>7</td><td>dea182036338</td><td>32.35</td><td>966.1</td><td>0.080</td><td>0.990</td><td>Rejected</td></tr>
<tr><td>8</td><td>f562a70244c0</td><td>28.62</td><td>1091.8</td><td>0.000</td><td>1.000</td><td>Accepted</td></tr>
<tr><td>9</td><td>c805f2282a1f</td><td>41.41</td><td>754.7</td><td>0.000</td><td>0.990</td><td>Accepted</td></tr>
<tr><td>10</td><td>29a9522e0cc8</td><td>37.27</td><td>838.5</td><td>0.000</td><td>1.000</td><td>Accepted</td></tr>
</tbody>
</table>

## Reproducibility

The complete machine record is stored in `run.json`. The reusable serving configuration is stored in `best_preset.json`. Raw server logs, telemetry, and profiler output are stored inside each trial directory when available.

## Interpretation

This report describes measurements from one declared workload. Results should be confirmed on the target model, Radeon GPU, ROCm release, and request distribution before production use.
