# Track 3, VisioBot Lab, RadeonVLA-Reflex

> **An interruptible, recoverable, and evidence-driven VLA execution system for language-guided robotic manipulation on AMD Radeon.**

RadeonVLA-Reflex advances language-conditioned robot control from a one-shot policy call into an
auditable execution system. A fine-tuned SmolVLA policy proposes continuous actions; a deterministic
Reflex boundary validates every action chunk, invalidates stale commands, detects execution failure,
and performs bounded strict-physics recovery before control reaches Genesis. The complete lifecycle—
simulation, data collection, training, evaluation, and public evidence—runs on one AMD Radeon GPU
through ROCm.

## Project links

- **Project website:** <https://zzw-rgb.github.io/Radeon-hackathon-2026-07/>
- **Project source code:** <https://github.com/zzw-rgb/Radeon-hackathon-2026-07/tree/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex>
- **Interactive evidence console:** <https://zzw-rgb.github.io/Radeon-hackathon-2026-07/console.html>
- **Official Bilibili film:** <https://www.bilibili.com/video/BV1B4M26SEZg/>
- **Five-page technical report:** <https://github.com/zzw-rgb/Radeon-hackathon-2026-07/blob/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex/reports/RadeonVLA-Reflex-Technical-Report.pdf>
- **Hugging Face releases:** <https://huggingface.co/a3124371940>

## Team

**VisioBot Lab · Nanjing University of Science and Technology**

| Member | Role | Technical responsibility |
|---|---|---|
| **Zhenwei Zhou** | **Captain / Technical Lead** | Overall architecture and core implementation; Genesis, expert policy, Reflex runtime, collection orchestration, SmolVLA training/evaluation, AMD deployment, website, and release engineering |
| Ange Liu | Language & Frontend QA | Task-language schema review, collected-instruction consistency checks, website internationalization QA, and bilingual technical documentation |
| Haoran Wang | Data & Reproducibility QA | Dataset-certificate spot-checks, evaluation aggregation, reproduction-command verification, and artifact checksum packaging |

## Evaluator gateway

| Experience | Public link |
|---|---|
| **Live bilingual project showcase** | [RadeonVLA-Reflex website](https://zzw-rgb.github.io/Radeon-hackathon-2026-07/) |
| **Interactive 20-task evidence console** | [Launch the evidence console](https://zzw-rgb.github.io/Radeon-hackathon-2026-07/console.html) |
| **Official 200-second project film** | [RadeonVLA-Reflex on Bilibili](https://www.bilibili.com/video/BV1B4M26SEZg/) |
| Direct 1080p film | [Play or download MP4](https://zzw-rgb.github.io/Radeon-hackathon-2026-07/videos/radeonvla-reflex-3min.mp4) |
| Five-page technical report | [Open the release PDF](https://github.com/zzw-rgb/Radeon-hackathon-2026-07/blob/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex/reports/RadeonVLA-Reflex-Technical-Report.pdf) |
| Reproducible source release | [GitHub source directory](https://github.com/zzw-rgb/Radeon-hackathon-2026-07/tree/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex) |
| English / Chinese guides | [English README](https://github.com/zzw-rgb/Radeon-hackathon-2026-07/blob/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex/README.md) · [中文 README](https://github.com/zzw-rgb/Radeon-hackathon-2026-07/blob/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex/README.zh-CN.md) |
| Competition page | [AMD AI Developer Contest — Track 3](https://modelscope.cn/events/299/比赛介绍) |

## Public data, models, and evidence

Every artifact below is public, independently downloadable, and bound to an immutable Hugging Face
revision. The README also provides one-command pinned downloads and verification.

| Artifact | Public repository | Immutable revision |
|---|---|---|
| Physical-1K dataset | [1,000 strict-physics episodes](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_1k) | `b0f72c60e9100739fd82bd498c8f3d9bed7b75af` |
| Physical-2K dataset | [2,000 strict-physics episodes](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_2k) | `2779b7c5566df9072bb9a7c43335d6203ea97887` |
| SmolVLA 20K | [Primary showcase checkpoint](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k) | `abcca9f2b313e378b554449016b520b8117016fe` |
| SmolVLA 50K | [Intermediate checkpoint](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k_50k) | `59f6f0ad720054505667a652fe07e03d65e82915` |
| SmolVLA 200K | [Full continuation checkpoint](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_2k_200k) | `1ea32da3d59ce0905d0f1331bc3c6643e42beb7e` |
| Evaluation library | [Videos, results, provenance, and checksums](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_evaluation_videos) | `6de24191322c76c53405d6686b9ae74989073414` |

## Final measured results

The primary benchmark freezes one 200K checkpoint, the exact collected language, all 20 registered
fruit × destination tasks, and five disjoint seeds per task. Learned-policy retries are disabled.

| Metric | Result |
|---|---:|
| Learned SmolVLA first attempt | 36/100 |
| Strict-physics precision recoveries | 55/63 |
| **Final RadeonVLA-Reflex system success** | **91/100** |
| Wilson 95% interval | 83.8–95.2% |
| Inference latency P50 / P95 | 4.54 / 37.27 ms |
| Retained failures | 9/100 |

All 100 episodes—including every failure—remain in
[`artifacts/evaluation.json`](https://github.com/zzw-rgb/Radeon-hackathon-2026-07/blob/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex/artifacts/evaluation.json).
The learned first attempt and deterministic recovery contribution are deliberately reported
separately. Precision recovery disables rigid pose writes, object teleport, kinematic grasp glue,
and placement nudges.

An independent command-change probe switches `banana→white-left` to `banana→blue-right` at control
step 40. It records safe interrupt 1/1, zero additional response steps, zero unprotected
old-command actions, and final new-target success 1/1 in
[`artifacts/interrupt_evaluation.json`](https://github.com/zzw-rgb/Radeon-hackathon-2026-07/blob/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex/artifacts/interrupt_evaluation.json).

## AMD Radeon / ROCm execution path

- AMD Radeon Graphics (`gfx1100`), one visible GPU
- ROCm runtime `7.2.53211-e1a6bc5663`
- PyTorch `2.9.1+rocm7.2.1.gitff65f5bc`
- Genesis 1.1.2 and LeRobot 0.6.0
- Physical-2K continuation: 100,000 steps in 3h45m32s at approximately 30 samples/s
- Measured peak training memory: 2.22 GB

## Reproduce the public release

```bash
cd track3_VisioBotLab_RadeonVLA-Reflex
python -m pip install -e .
python -m radeonvla.download_artifacts --artifact physical-1k model-20k evaluation-videos
python -m radeonvla.submission_audit --final
```

The [English README](https://github.com/zzw-rgb/Radeon-hackathon-2026-07/blob/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex/README.md)
continues from this gate through strict dataset validation, real policy loading, AMD training,
single-task evaluation, and the formal 100-rollout command. No private artifact or source patch is
required.

## Claims boundary

This submission evaluates Genesis simulation only and makes no real-robot or sim-to-real claim.
Advanced L2–L4 task definitions are implemented, while the published 91/100 primary result covers
the registered L1 20-task suite. Evidence is intentionally structured so evaluators can distinguish
learned behavior, deterministic safety logic, recovery contribution, and retained failures.
