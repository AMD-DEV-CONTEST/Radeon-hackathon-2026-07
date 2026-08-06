# Decompile benchmark baseline

The application records orchestration-stage timing locally. These baseline figures are deterministic demo measurements, not a claim of model throughput on a particular GPU. Re-run the benchmark after selecting a ROCm runtime to produce hardware-specific values.

| Stage | Baseline |
| --- | ---: |
| Transcript processing | 1.8 s |
| Vision inference adapter | 4.2 s |
| BGE embedding adapter | 0.7 s |
| Planning | 3.6 s |
| Repository generation | 1.1 s |
| Total | 11.4 s |

## Measurement method

`GET /api/benchmarks` returns the values used by the UI. For a deployment benchmark, run a warm-up inference, collect five runs, report median latency and tokens/sec, then capture `rocm-smi` utilization and VRAM at one-second intervals. This keeps AMD GPU claims traceable and reproducible.
