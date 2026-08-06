# TidyBot Final Submission — V9

## Main result

The learned fixed-room hierarchy completes one whole-room lap, then detects,
docks to, picks, carries, and deposits the can, bottle, cup, and banana.

- Two consecutive complete successes: V8 and V9
- No teacher, demonstration replay, IK, object-truth control, or state writes
- 13,866 control steps and 13,866 fixed-camera video frames
- IntegrityMonitor: clean, zero violations
- Final package validation: passed

This is a fixed-scene overfit result, not a random-room or real-robot
generalization claim.

## Videos

### Primary videos

- `videos/v9_full_whole_room.mp4`
  - Uninterrupted V9 submission video
  - Fixed whole-room corner camera
  - 320×240, 20 fps, 13,866 frames, 11:33.3
- `videos/v9_method_whole_room_4x.mp4`
  - Additional whole-room-only method presentation
  - 4× speed with method/stage labels and progress bar

### Frame-accurate clips from V9

- `videos/clips/01_learned_room_route.mp4`
  - Complete learned room lap
- `videos/clips/02_can_detect_stop_pick.mp4`
- `videos/clips/03_bottle_detect_stop_pick.mp4`
- `videos/clips/04_cup_detect_stop_pick.mp4`
- `videos/clips/05_banana_detect_stop_pick.mp4`

Each object clip starts before visual confirmation, includes the learned final
dock and stop, and retains the complete manipulation through stable deposit.

## Models

- `models/lap_route/`: learned whole-room route MLP
- `models/object_routes/`: four object-specific docking route MLPs
- `models/arm/`: four phase/progress-conditioned manipulation MLPs
- `models/detector/best.pt`: TidyBot-domain YOLO11 detector

## Metrics and provenance

- `metrics/summary.json`: compact mission and inference summary
- `metrics/result.json`: full event and command ledger
- `metrics/rocm_telemetry.jsonl`: raw one-second ROCm samples
- `metrics/rocm_telemetry_summary.json`: GPU utilization, VRAM, power,
  temperature, and clocks
- `metrics/video_validation.json`: frame counts, durations, sizes, and hashes
- `tidybot_full_learned_v1.json`: model lock and hashes

Final V9 ROCm:

- GPU utilization: mean 22.89%, p95 40%, max 44%
- Peak VRAM: 867,450,880 bytes
- Power: mean 68.31 W, max 80 W
- Maximum temperature: 44°C

Detector held-out metrics:

- mAP50: 0.995
- Recall: 0.999

## Reproduction

The source code and all nine runtime checkpoints are included in the parent
project directory. Follow the portable, ROCm-specific
[`快速复现`](../../README.md#快速复现) instructions to verify
the bundle and rerun the complete mission.

