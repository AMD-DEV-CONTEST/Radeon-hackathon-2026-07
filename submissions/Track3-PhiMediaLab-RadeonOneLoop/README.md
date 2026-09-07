# Track 3, Phi Media Lab, Radeon OneLoop

## Project

**Radeon OneLoop: a staged Real2Sim2Real loop for bimanual handover on AMD Radeon**

**Team:** Phi Media Lab

**Team member:** Baoshu Feng

Radeon OneLoop connects a proven real-robot learning loop to a new Real2Sim
path for the same dual-SO-101 cell and team-owned plush object. One arm grasps
and presents the object, the second receives it, and the system places it in a
target zone.

## Two auditable evidence chains

### 1. Real -> learn -> real

- 84 team demonstrations plus 40 reviewed policy/HIL episodes form an
  immutable 124-episode, 178,465-frame dataset with 15,906 correction frames.
- Baseline ACT and phase-aware ACT were both initialized from scratch and
  trained for 10,000 updates on exactly one Radeon `gfx1100` through ROCm.
- Phase-aware weighting gives correction frames weight 4.0 and failed policy
  prefixes weight 0.05. It reduced correction-frame normalized chunk L1 by
  2.05% (`0.11957 -> 0.11712`) while worsening the equal-role aggregate by
  14.19%; both sides of the tradeoff are reported.
- The inherited physical HIL/deployment system has a reviewed 37/45 (82.22%)
  handover result. A 51.14-second hardware clip shows one complete physical
  handover-to-place execution in that cell.
- Full 100-action chunk median latency is 18.11 ms / 18.55 ms, with 1.233 ms
  queued-action median for both checkpoints.

The 37/45 result predates the new formal checkpoints. It proves that the
physical data/HIL/deployment loop operated, but is not claimed as the success
rate of either new checkpoint. Likewise, one successful video is execution
evidence, not a success-rate estimate.

### 2. Real -> sim

- Reviewed real photographs of the team-owned object produce a TRELLIS.2
  textured asset with 221,670 vertices and 293,972 faces.
- The asset is canonicalized to the measured 95 mm object height and ingested
  into the matching Genesis workspace.
- Our Torch/ROCm MGPBD implementation owns a tetrahedral state; an exact
  custom-vertex bridge transfers that state into the Genesis AMD renderer.
- AMD run `T152831` passed the bridge gate on `bunny_small`: 2,992 volume
  vertices / 12,298 tetrahedra, 2,000 boundary vertices / 3,996 faces, one
  closed component, zero open or non-manifold edges, and zero rest-state
  mapping error.

This is a validated staged pipeline, not a claim of completed realtime
deformable-doll contact. TRELLIS.2 generation used its official hosted
endpoint; Radeon evidence starts at metric asset preparation and Genesis
execution. The MGPBD P0a2 solve preserves a safe 31-outer checkpoint but does
not pass full convergence at outer 32. The next experiment is a
boundary-conforming doll volume, gripper contact, and sim-to-real retraining.

## What runs on AMD Radeon

The formal accelerator path uses one AMD Radeon `gfx1100` GPU for Genesis,
baseline and phase-aware ACT training, and real-observation ACT inference.
PyTorch 2.9.1 uses ROCm 7.2.1 / HIP. The CPU handles decoding, cameras, robot
I/O, limits, watchdog, and emergency stop. The Real2Sim development path also
validates MGPBD tensor solves and the Genesis state bridge on an AMD APU
(`gfx1150`). Each claim is tied to its own host and receipt; results are not
silently pooled across machines.

## Why it matters

OneLoop turns corrections from a deployment failure mode into reusable
training signal, while the Real2Sim branch turns the same real object and cell
into a measurable digital-twin interface. Data schema, robot state, cameras,
safety protocol, object scale, and evidence receipts are shared across the
real and simulated paths.

## Deliverables

- Source and reproduction: https://github.com/phi-media-lab/radeon-oneloop
- Technical report in this submission:
  [radeon-oneloop-technical-report.pdf](radeon-oneloop-technical-report.pdf)
- Formal single-Radeon evidence:
  https://github.com/phi-media-lab/radeon-oneloop/tree/main/artifacts/formal
- MGPBD-to-Genesis bridge evidence:
  https://github.com/phi-media-lab/radeon-oneloop/tree/main/artifacts/development/amd_genesis_mgpbd_bunny_bridge_20260806T152831Z
- 3:45 formal workflow video:
  https://github.com/phi-media-lab/radeon-oneloop/releases/download/v1.0.0/radeon-oneloop-demo.mp4
- 51-second physical handover-to-place evidence:
  https://github.com/phi-media-lab/radeon-oneloop/releases/download/v1.0.0/amd-hackathon.mp4
- Versioned release and SHA-256 manifest:
  https://github.com/phi-media-lab/radeon-oneloop/releases/tag/v1.0.0

## Reproduction entry point

```bash
git clone https://github.com/phi-media-lab/radeon-oneloop.git
cd radeon-oneloop
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
./ops/validate_scaffold.sh
```

The repository contains the immutable dataset registry (not raw private
frames), hash-pinned Radeon environment, paired training configs, formal run
receipts, inference evaluators, Real2Sim preparation code, MGPBD gates, Genesis
bridge tests, and explicit negative-result reports.
