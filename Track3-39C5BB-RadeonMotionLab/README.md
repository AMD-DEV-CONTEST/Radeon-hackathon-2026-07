# Track 3 — Team #39C5BB — Radeon Motion Lab

**Radeon Motion Lab** is an evidence-first robustness benchmark for a vision-guided
Franka Panda fruit pick-and-place task, running in the Genesis physics engine on an
AMD Radeon GPU through ROCm.

The upstream Track 3 starter controller reads the target object pose directly from the
simulator. Our primary policy removes that oracle input: it estimates the grasp pose
from RGB-D images, public camera calibration, known table geometry, the requested fruit
class, and robot state. We then freeze eleven causal perturbation conditions, vary one
axis at a time, keep the failures, and record perception error separately from task
completion.

## Submission materials

| Requirement | Location |
| --- | --- |
| Project profile / technical report (PDF) | [`RadeonMotionLab-Technical-Report.pdf`](RadeonMotionLab-Technical-Report.pdf) |
| Demo video (4:53, 1080p/30fps) | [`RadeonMotionLab_Demo_1080p.mp4`](RadeonMotionLab_Demo_1080p.mp4) |
| Complete source code | https://github.com/kyui-azusa/radeon-motion-lab |
| Reproducibility README | https://github.com/kyui-azusa/radeon-motion-lab/blob/main/docs/REPRODUCIBILITY.md |
| Dockerfile | https://github.com/kyui-azusa/radeon-motion-lab/blob/main/Dockerfile |
| Archived run records & checksums | https://github.com/kyui-azusa/radeon-motion-lab/tree/main/runs |

## Verified AMD Radeon / ROCm execution

- Genesis 1.3.1 selected the `gs.amdgpu` backend
- PyTorch 2.9.1 on ROCm 7.2.1, target `gfx1100`, 47.98 GB device memory as reported by Genesis
- Simulation, rendering, and the robot execution loop all run on the AMD GPU backend
- Logs, preflight output, source revision, stage frames, MP4 files, and JSON records are
  archived in the public source repository with a SHA-256 manifest

## Results

The frozen baseline covers three YCB fruits, eleven conditions, and five seeds per
condition — 165 cells. The ten runtime conditions complete 144/150 episodes; the
separately rebuilt appearance matrix completes 15/15.

Nine conditions complete 15/15. Pose shift and low friction each complete 12/15
(Wilson 95% interval 0.548–0.930). All six failures are lemon execution failures
despite evaluator-only XY localization errors below 0.70 mm — the policy still saw the
fruit correctly, and the contact-and-execution path is where it broke.

A matched physical guard ablation *decreases* the physical subset from 27/30 to 20/30,
so it is reported as a negative result and is not promoted. A sensor-only controller
follow-up reaches 4/5 on its prerequisite lemon pose gate and is likewise not promoted.

## Known limitations

Five seeds per condition in one simulated scene: the intervals describe these episodes,
not a population-level deployment guarantee. No learned detector, end-to-end learned
policy, real-robot result, or sim-to-real transfer claim is made. A deterministic CPU
reference path exists for schema validation only and is never counted as AMD GPU
evidence.

## Team

- **Ziyu Zhou** ([@kyui-azusa](https://github.com/kyui-azusa)) — project lead: system
  design, sensor-only RGB-D policy, perturbation protocol, AMD Radeon/ROCm execution,
  evidence pipeline, technical report
- **Yunjia Zhang** ([@BeRiriJ](https://github.com/BeRiriJ)) — evaluation review,
  reproducibility testing, reproducibility materials
- **Liqing Sang** ([@ninly990](https://github.com/ninly990)) — evidence archiving,
  checksum verification, demonstration video
