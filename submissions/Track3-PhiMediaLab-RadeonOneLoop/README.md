# Track 3, Phi Media Lab, Radeon OneLoop

## Project

**Radeon OneLoop: Single-Radeon Phase-Aware HIL Bimanual Handover**

**Team:** Phi Media Lab

**Team member:** Baoshu Feng

Radeon OneLoop is a complete embodied-learning pipeline for a real dual-SO-101
handover. One arm grasps and presents an object, the second receives it, and
the system places it in a target zone. We study a phase-aware ACT objective
that gives human correction frames more loss mass while suppressing failed
autonomous prefixes, and compare it fairly with a uniformly trained ACT
baseline.

## What runs on AMD Radeon

The complete formal accelerator path uses one AMD Radeon `gfx1100` GPU:

- Genesis 1.3.1 environment build, stepping, and camera rendering through
  `gs.amdgpu`;
- baseline and phase-aware ACT training from random initialization through
  PyTorch 2.9.1 / ROCm 7.2.1; and
- real-observation ACT chunk inference through the same ROCm stack.

The CPU handles decoding, cameras, robot I/O, timeouts, action limits,
watchdog, and emergency stop. No CUDA device, NPU, second GPU, remote inference
API, or historical MI300X checkpoint participates in the formal lineage.

## Highlights

- Immutable 124-episode, 178,465-frame real dataset contract with 15,906
  reviewed intervention/correction frames.
- Fair 10,000-step baseline-versus-phase-aware ACT experiment with a
  predeclared final-step checkpoint rule.
- Correction-frame normalized chunk L1 improved 2.05% (0.11957 → 0.11712),
  while the equal-role aggregate worsened 14.19%; the tradeoff is reported
  explicitly and is not relabeled as task success.
- Full 100-action chunk median latency is 18.11 ms / 18.55 ms, with 1.233 ms
  queued-action median for both checkpoints.
- Dual-SO-101 Genesis environment with two 480×640 cameras and measured
  single-Radeon execution.
- Fail-closed evidence launcher binding every result to GPU UID, Git commit,
  config hash, dataset hash, seed, exact command, GPU samples, and raw logs.
- CPU-edge sequence, timeout, joint-limit, delta-limit, watchdog, and latched
  E-stop contracts.
- Explicit negative-result reporting: training diagnostics are not presented
  as task success, and an uncalibrated Gaussian branch was excluded.
- Upstream AMD support report:
  https://github.com/Genesis-Embodied-AI/genesis-world/issues/3163

## Deliverables

- Source and reproduction: https://github.com/phi-media-lab/radeon-oneloop
- Technical report in this submission:
  [radeon-oneloop-technical-report.pdf](radeon-oneloop-technical-report.pdf)
- Technical report in the dedicated repository:
  https://github.com/phi-media-lab/radeon-oneloop/blob/main/output/pdf/radeon-oneloop-technical-report.pdf
- Formal evidence:
  https://github.com/phi-media-lab/radeon-oneloop/tree/main/artifacts/formal
- 3:45 demonstration video:
  https://github.com/phi-media-lab/radeon-oneloop/releases/download/v1.0.0/radeon-oneloop-demo.mp4
- Versioned release:
  https://github.com/phi-media-lab/radeon-oneloop/releases/tag/v1.0.0

## Reproduction entry point

```bash
git clone https://github.com/phi-media-lab/radeon-oneloop.git
cd radeon-oneloop
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
./ops/validate_scaffold.sh
```

The root README contains the hash-pinned Radeon environment, authorized data
build, Genesis, paired training, latency, and diagnostic commands. Raw robot
video is access-controlled and is not redistributed; its schema and immutable
source/derived hashes are public.
