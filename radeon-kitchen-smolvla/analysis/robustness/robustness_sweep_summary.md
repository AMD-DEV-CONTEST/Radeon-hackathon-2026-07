# Sim-to-Real Robustness Intensity Sweep

Every point reuses one placement manifest. Severity is normalized within each stress family: 0 is nominal and 1 is the maximum listed perturbation.

| Family | Severity | Parameter | Episodes | Success | Rate | Retention |
|---|---:|---|---:|---:|---:|---:|
| nominal | 0.00 | `nominal` | 20 | 6 | 30.0% | 100.0% |
| Brightness +/- | 0.33 | `--brightness-range 0.95 1.05` | 20 | 8 | 40.0% | 133.3% |
| Brightness +/- | 0.67 | `--brightness-range 0.85 1.15` | 20 | 12 | 60.0% | 200.0% |
| Brightness +/- | 1.00 | `--brightness-range 0.75 1.25` | 20 | 9 | 45.0% | 150.0% |
| RGB noise | 0.33 | `--image-noise-std 2` | 20 | 2 | 10.0% | 33.3% |
| RGB noise | 0.67 | `--image-noise-std 4` | 20 | 9 | 45.0% | 150.0% |
| RGB noise | 1.00 | `--image-noise-std 8` | 20 | 3 | 15.0% | 50.0% |
| Occlusion | 0.33 | `--occlusion-prob 1.0 --occlusion-fraction 0.10` | 20 | 4 | 20.0% | 66.7% |
| Occlusion | 0.67 | `--occlusion-prob 1.0 --occlusion-fraction 0.25` | 20 | 1 | 5.0% | 16.7% |
| Occlusion | 1.00 | `--occlusion-prob 1.0 --occlusion-fraction 0.40` | 20 | 0 | 0.0% | 0.0% |
| Action delay | 0.33 | `--action-delay-steps 1` | 20 | 11 | 55.0% | 183.3% |
| Action delay | 0.67 | `--action-delay-steps 2` | 20 | 11 | 55.0% | 183.3% |
| Action delay | 1.00 | `--action-delay-steps 4` | 20 | 9 | 45.0% | 150.0% |
| Friction low | 0.33 | `--cube-friction 1.4` | 20 | 9 | 45.0% | 150.0% |
| Friction low | 0.67 | `--cube-friction 1.2` | 20 | 10 | 50.0% | 166.7% |
| Friction low | 1.00 | `--cube-friction 1.0` | 20 | 13 | 65.0% | 216.7% |
| Friction high | 0.33 | `--cube-friction 1.6` | 20 | 12 | 60.0% | 200.0% |
| Friction high | 0.67 | `--cube-friction 1.8` | 20 | 10 | 50.0% | 166.7% |
| Friction high | 1.00 | `--cube-friction 2.0` | 20 | 6 | 30.0% | 100.0% |

## Reading the Curve

The expected transfer pattern is lower success at higher stress, but each point is an episode-level binomial estimate. A non-monotonic local step is reported as sampling variance rather than smoothed away.

The friction family is shown as separate low- and high-friction directions because the same absolute deviation can affect contact in different ways.

These are Genesis stress tests, not real-robot success guarantees.
