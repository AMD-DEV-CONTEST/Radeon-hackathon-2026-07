# AMD Radeon 并发性能实验

所有数值来自同一 Case Capsule、同一模型和本次 Radeon 运行日志；每档使用相同请求数，Prefix Cache 在统一预热后开启。

- Model: `Qwen/Qwen3-VL-8B-Instruct`
- Source commit: `0ce3564`
- Requests per level: 20
- Max output tokens: 500

| Concurrency | Completed | Success | TTFT p50/p95 | TPOT p50/p95 | Latency p50/p95 | Output tok/s | Speedup | Efficiency | OOM | Verifier | GPU mean/peak | VRAM peak |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20/20 | 100.0% | 0.111/0.112s | 0.0388/0.0388s | 15.152/15.160s | 25.67 | 1.00x | 100.0% | 0 | 100.0% | 99.8/100% | 46744 MB |
| 2 | 20/20 | 100.0% | 0.113/0.116s | 0.0401/0.0401s | 15.665/15.668s | 49.32 | 1.92x | 96.1% | 0 | 100.0% | 100.0/100% | 46744 MB |
| 4 | 20/20 | 100.0% | 0.120/0.121s | 0.0445/0.0445s | 17.385/17.401s | 89.48 | 3.49x | 87.2% | 0 | 100.0% | 100.0/100% | 46744 MB |
