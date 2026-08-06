# Track 3, Avinash, Quantized Embodied Control

**Repository:** https://github.com/AV55CS/quantized-embodied-control
**📹 [Demo video](https://youtu.be/rxelrEAo7Io)**

How far can you compress a robot's brain before it drops the banana?

An ACT visuomotor policy controls a Franka Panda arm picking fruit in Genesis,
running on AMD Radeon under ROCm 7.2.1. We quantize the policy from 32 bits to 4
and locate the precision cliff.

| Strategy | Bits | Compression | Task success |
|---|---:|---:|---:|
| FP32 | 32 | 1.0× | 95% |
| Uniform 6-bit | 6.000 | 5.3× | 90% |
| Adaptive 6-bit | 6.001 | 5.3× | 90% |
| Uniform 5-bit | 5.000 | 6.4× | 80% |
| Uniform 4-bit | 4.000 | 8.0× | 35% |
| Adaptive 4-bit | 3.888 | 8.2× | 0% |

Deliverables: technical report, reproducibility instructions, quantization harness,
per-episode results, rollout videos — all in the linked repository.
