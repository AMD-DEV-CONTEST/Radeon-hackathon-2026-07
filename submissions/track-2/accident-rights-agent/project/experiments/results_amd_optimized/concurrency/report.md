# AMD Radeon 并发性能实验

所有数值来自同一 Case Capsule、同一模型和本次 Radeon 运行日志；每档使用相同请求数，Prefix Cache 在统一预热后开启。

- Model: `Qwen/Qwen3-VL-8B-Instruct`
- Source commit: `d11d9da`
- Requests per level: 4
- Max output tokens: 700

| Concurrency | TTFT p50/p95 | TPOT p50/p95 | Latency p50/p95 | Output tok/s | Speedup | Efficiency | Verifier | GPU mean/peak | VRAM peak |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.081/0.081s | 0.0401/0.0401s | 11.816/11.820s | 24.86 | 1.00x | 100.0% | 100.0% | 99.2/100% | 43820 MB |
| 2 | 0.163/0.245s | 0.0415/0.0417s | 12.311/12.461s | 47.75 | 1.92x | 96.0% | 100.0% | 98.8/100% | 43820 MB |
| 4 | 0.138/0.138s | 0.0469/0.0470s | 13.878/13.879s | 84.54 | 3.40x | 85.0% | 100.0% | 100.0/100% | 43820 MB |
