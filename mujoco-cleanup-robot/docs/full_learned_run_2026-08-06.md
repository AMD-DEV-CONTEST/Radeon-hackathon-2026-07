# Fixed-room learned full run — 2026-08-06

## Result

The final `v9` run completed one collision-free room lap and then detected,
approached, grasped, carried, and deposited the can, bottle, cup, and banana in
one continuous simulation. Runtime task actions came from PyTorch route and arm
policies plus the trained YOLO11 detector. No teacher, demonstration action
replay, IK, object truth, `qpos` write, or `qvel` write was used for control.

This is a fixed-scene overfit result. It is not evidence of random-room or
real-robot generalization.

| Gate | Measured result |
|---|---|
| Full learned mission | 2/2 consecutive successes (`v8`, `v9`) |
| Room lap policy | 3/3, 100% route coverage, zero blocking collisions |
| Fixed arm policies | 3/3 per object; 12/12 stable physical deposits |
| Detector held-out | mAP50 0.995, recall 0.999 |
| Final video ledger | 13,866 control steps = 13,866 video frames |
| Integrity monitor | clean, 352,006 MuJoCo steps, zero violations |

## Final artifacts

- Uninterrupted submission video:
  `final_submission/videos/v9_full_whole_room.mp4`
- Compact result:
  `final_submission/metrics/summary.json`
- Full command ledger:
  `final_submission/metrics/result.json`
- ROCm samples:
  `final_submission/metrics/rocm_telemetry.jsonl`
- ROCm summary:
  `final_submission/metrics/rocm_telemetry_summary.json`
- Portable bundle manifest:
  `SUBMISSION_MANIFEST.json`

The uninterrupted submission video is 320×240, 20 fps, 13,866 frames, and
has SHA256
`6f89ffc090f5e79d8dbc6d12d3d1ae852e08178c6d8299d6c0f3ce21710b2a98`.

## Learned models

- Lap route MLP:
  `final_submission/models/lap_route/policy.pt`
- Object-specific route MLPs:
  `final_submission/models/object_routes/{can,bottle,cup,banana}.pt`
- Fixed arm Fourier MLPs:
  `final_submission/models/arm/{can,bottle,cup,banana}.pt`
- TidyBot-domain YOLO11 detector:
  `final_submission/models/detector/best.pt`

The object-specific route policies were required because a single MLP's global
route progress feature underweighted rare docking segments. The cup dock was
also changed to a west-facing, target-relative equivalent pose so the rigid
trailer did not sweep the island sofa. Both changes preserve the learned
runtime contract.

## Inference timing

Measured with synchronized ROCm inference:

- Route MLP: p50 0.239 ms, p95 0.259 ms over 7,296 calls.
- Arm MLP: p50 0.669 ms, p95 0.720 ms over 6,281 calls.
- YOLO11: 1,210.8 ms cold start; warm p50 11.03 ms and p95 11.16 ms.

## ROCm telemetry

The final run recorded 167 valid one-second samples with no parse errors:

- GPU use: mean 22.89%, p50 28%, p95 40%, maximum 44%.
- VRAM: peak 867,450,880 bytes of 51,522,830,336 bytes.
- Board power: mean 68.31 W, p95 78 W, maximum 80 W.
- Temperature: p95/max 44°C.
- SCLK: p95 2,089 MHz; MCLK: p95 1,124 MHz.

Detector training separately averaged 77.02% GPU use with 100% p95 utilization,
11.17 GB peak VRAM, 300 W peak power, and 59°C maximum temperature.

## Reproduction

First follow the environment and pinned Menagerie setup in the repository
[`README.md`](../../README.md#快速复现), then verify the portable bundle:

```bash
python scripts/verify_submission_bundle.py
```

Run the final mission with the bundled checkpoints:

```bash
PYTHONPATH=src MUJOCO_GL=egl python scripts/run_tidybot_full_learned.py \
  --route-checkpoint final_submission/models/lap_route/policy.pt \
  --object-route-directory final_submission/models/object_routes \
  --arm-directory final_submission/models/arm \
  --detector-weights final_submission/models/detector/best.pt \
  --output outputs/judge-reproduction-v9 \
  --device 0
```

The bundle verifier checks the released model and video hashes, the recorded
mission and integrity results, and every file in `SUBMISSION_MANIFEST.json`.
