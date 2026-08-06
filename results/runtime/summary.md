# Full SmolVLA `sample_actions()` runtime backends

| Backend | Mean ms | P50 ms | P95 ms | Samples/s | Speedup | Latency reduction | First call ms | Peak MiB | Memory Δ MiB | Validation | Fixed max error | Fixed RMSE | Changed max error |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| eager | 153.81 | 151.94 | 154.93 | 6.50 | 1.000× | 0.00% | 1224.62 | 1022.28 | 0.00 | reference | — | — | — |
| compile | 63.86 | 63.30 | 66.14 | 15.66 | 2.409× | 58.48% | 23357.21 | 1203.27 | 180.99 | numerical_mismatch (passed=False) | 0.067798 | 0.002732 | 0.023839 |
| hip-graph | 102.76 | 102.70 | 103.47 | 9.73 | 1.497× | 33.19% | 1558.50 | 1133.78 | 111.49 | ok (passed=True) | 0.000000 | 0.000000 | 0.000000 |
