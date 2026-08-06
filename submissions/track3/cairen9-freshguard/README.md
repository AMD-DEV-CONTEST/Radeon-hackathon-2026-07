# FreshGuard - Track 3 Physical AI Submission

FreshGuard is a language-conditioned, quality-aware robotic fruit sorting
system built with Genesis, LeRobot/SmolVLA, AMD Radeon GPUs, and ROCm. A
ripeness-conditioned hybrid controller keeps learned finger position control
for ripe fruit and applies a 6 N-per-finger, contact-triggered latched force
guard for unripe fruit.

## Deliverables

- Source code: https://github.com/cairen9/freshguard-physical-ai
- Technical report: [FreshGuard_Technical_Report.pdf](FreshGuard_Technical_Report.pdf)
- Reproducibility instructions: the source repository `README.md` and
  `FRESHGUARD_SUBMISSION.md`
- Raw demonstration clips: [GitHub-hosted ZIP](https://github.com/user-attachments/files/30781306/video.zip)
- Backup mirror: [Baidu Netdisk](https://pan.baidu.com/s/1wKbvYqZIJdXIoEYX-YC65w?pwd=s7zx), extraction code: `s7zx`

## Final Untouched Holdout

The final controller was frozen before a matched evaluation on 100 previously
unused seeds (`8000..8099`).

| Metric | Policy-only | FreshGuard hybrid | Change |
| --- | ---: | ---: | ---: |
| Task success | 84% | **99%** | **+15 pp** |
| Damage-free success | 64% | **72%** | **+8 pp** |
| Expected-bin rate | 84% | **99%** | **+15 pp** |
| Wrong-bin rate | 0% | **0%** | 0 pp |
| Mean peak contact | **17.17 N** | 18.18 N | +1.01 N |
| Mean episode wall time | 13.67 s | **12.17 s** | -1.50 s |
| Inference latency p95 | **5.32 ms** | 5.58 ms | +0.26 ms |

Damage-free success is a simulation risk proxy. The 18 N ripe and 26 N unripe
thresholds are not presented as calibrated biological bruise limits.

## AMD Radeon and ROCm

Genesis 1.2.3 ran with the `gs.amdgpu` backend on a `gfx1100` Radeon device
reporting 47.98 GB of device memory. Genesis simulation and SmolVLA inference
ran in the same ROCm environment.

| Parallel environments | Environment-steps/s | Speedup | Efficiency |
| ---: | ---: | ---: | ---: |
| 1 | 124.5 | 1.00x | 100.0% |
| 16 | 1,896.4 | 15.23x | 95.2% |
| 64 | 7,316.6 | 58.77x | 91.8% |
| 128 | 14,279.1 | 114.69x | 89.6% |
| 256 | **26,579.9** | **213.49x** | **83.4%** |

## Reproduction

The dedicated source repository contains environment setup, data recording,
training, matched evaluation, demo, and Radeon scaling commands. Large datasets
and checkpoints are intentionally excluded from ordinary Git history.

## Team

`cairen9` - Solo developer responsible for system design, controller
implementation, data collection, training, evaluation, Radeon benchmarking,
documentation, and demo production.

