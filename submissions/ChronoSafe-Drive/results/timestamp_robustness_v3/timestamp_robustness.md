# Timestamp metadata robustness

| Condition | Accuracy mean ± SD | Δ accuracy | Risk MAE | Coverage | ≥90% coverage |
|---|---:|---:|---:|---:|:---:|
| intact | 99.8271% ± 0.0241% | +0.0000 pp | 0.007166 | 99.3431% | yes |
| missing burst 10pct | 98.9957% ± 0.9997% | -0.8314 pp | 0.014878 | 92.8533% | yes |
| missing burst 30pct | 92.4710% ± 1.5739% | -7.3561 pp | 0.028170 | 81.7230% | no |
| missing burst 50pct | 84.7828% ± 1.2249% | -15.0443 pp | 0.041540 | 71.0554% | no |
| camera clock drift 1frame | 99.8134% ± 0.0315% | -0.0137 pp | 0.007924 | 99.5768% | yes |
| camera clock drift 3frames | 99.6769% ± 0.0959% | -0.1502 pp | 0.011204 | 99.6207% | yes |
| camera clock drift 5frames | 99.2688% ± 0.1265% | -0.5583 pp | 0.014957 | 99.5616% | yes |
| timestamp jitter 1frame | 96.1346% ± 1.5653% | -3.6925 pp | 0.020021 | 95.0318% | yes |
| timestamp jitter 2frames | 85.3047% ± 3.2816% | -14.5224 pp | 0.035745 | 87.9746% | no |
| timestamp channels swapped | 72.0202% ± 0.9456% | -27.8069 pp | 0.035283 | 82.4421% | no |
| timestamps spoofed clean | 67.9637% ± 0.6694% | -31.8634 pp | 0.064820 | 55.5394% | no |
