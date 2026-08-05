# Performance Evidence and Optimization

The verified direct loopback run measured 1,511.072 ms latency and 32.427 completion tokens per second for 45 prompt tokens and 49 completion tokens. The complete Chinese Agent task measured 18.384639 seconds, including retrieval, planning, tool work, model generation, audit persistence, and response assembly.

Implemented optimizations are an 8,192-token context cap, 0.85 GPU-memory utilization, loopback transport, temperature zero, top-k local retrieval, excluded environment directories, bounded inventory samples, and a 25-item model-context limit. These settings target predictable memory and smaller prompts.

Only captured values are claims. No unmeasured baseline, speedup, P50, P95, VRAM peak, concurrency, or hardware soak value is invented. The immutable source record is `submission/evidence/rocm-verified/radeon-benchmark-run.json`.
