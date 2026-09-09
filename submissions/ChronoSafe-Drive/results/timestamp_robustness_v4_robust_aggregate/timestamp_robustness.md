# Timestamp metadata robustness

| Condition | Accuracy mean ± SD | Δ accuracy | Risk MAE | Coverage | ≥90% coverage |
|---|---:|---:|---:|---:|:---:|
| intact | 99.3446% ± 0.1093% | +0.0000 pp | 0.012068 | 100.0000% | yes |
| missing burst 10pct | 99.2961% ± 0.1273% | -0.0485 pp | 0.013646 | 100.0000% | yes |
| missing burst 30pct | 98.5604% ± 0.0883% | -0.7843 pp | 0.017570 | 99.6481% | yes |
| missing burst 50pct | 97.7715% ± 0.0730% | -1.5731 pp | 0.020734 | 99.4129% | yes |
| camera clock drift 1frame | 99.5449% ± 0.0473% | +0.2003 pp | 0.012096 | 100.0000% | yes |
| camera clock drift 3frames | 99.6541% ± 0.0343% | +0.3095 pp | 0.012702 | 100.0000% | yes |
| camera clock drift 5frames | 99.6784% ± 0.0569% | +0.3338 pp | 0.013795 | 100.0000% | yes |
| timestamp jitter 1frame | 99.4114% ± 0.1661% | +0.0668 pp | 0.015205 | 99.9985% | yes |
| timestamp jitter 2frames | 96.6868% ± 0.4945% | -2.6578 pp | 0.022303 | 99.9788% | yes |
| timestamp channels swapped | 99.3446% ± 0.1093% | +0.0000 pp | 0.012471 | 99.9985% | yes |
| timestamps spoofed clean | 95.0818% ± 0.0682% | -4.2628 pp | 0.027616 | 97.6350% | yes |
