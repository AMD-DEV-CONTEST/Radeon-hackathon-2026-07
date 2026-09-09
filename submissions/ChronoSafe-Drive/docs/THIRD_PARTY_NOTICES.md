# Third-Party Software and Data Notices

ChronoSafe-Drive contains original project code and uses the following
third-party software and data. Users must verify the current upstream licenses
before redistribution or deployment.

## AMD ROCm and PyTorch

- Project: AMD ROCm software stack and ROCm-enabled PyTorch
- Upstream: <https://github.com/ROCm/ROCm> and <https://github.com/pytorch/pytorch>
- Use in this project: GPU training, inference, AMP, device-event timing, and
  memory measurement
- Project modifications: no vendored or modified ROCm/PyTorch source

## MetaDrive

- Project: MetaDrive 0.4.3
- Upstream: <https://github.com/metadriverse/metadrive>
- Use in this project: physics-based driving simulation, vehicle dynamics, RGB
  observations, LiDAR observations, and closed-loop actuation
- Project modifications: no installed package files are modified. An optional
  process-local raw-headless fallback exists for diagnosis only and is excluded
  from formal results. Official results run under Xvfb without that fallback.
- Original ChronoSafe-Drive work: fault scheduling, timing-aware feature
  extraction, model integration, calibrated state machine, multi-seed protocol,
  renderer-domain validation, and evidence generation

## nuScenes

- Dataset: nuScenes v1.0-trainval
- Official source: <https://www.nuscenes.org/>
- Use in this project: public logged `CAM_FRONT`, `LIDAR_TOP`, timestamp, and ego
  pose streams
- Redistribution: raw images, point clouds, and metadata archives are not
  redistributed by ChronoSafe-Drive
- Original ChronoSafe-Drive work: direct metadata parsing, causal alignment,
  LiDAR range binning, controlled degradation, timing features, track creation,
  log-grouped leakage-resistant split, and evaluation

## NumPy, OpenCV, and Matplotlib

- NumPy: feature construction, deterministic corruption, metrics, and bootstrap
  sampling
- OpenCV: controlled image blur and preview generation
- Matplotlib: reviewer-facing plots
- Project modifications: no vendored or modified upstream source

## Original project components

The following components were implemented specifically for ChronoSafe-Drive:

- persistent single and compound camera/LiDAR/timing fault injection;
- 10-dimensional sensor-health and 15-dimensional timing-aware causal features;
- timestamp missing, drift, jitter, swap, and spoofing augmentation;
- factorized camera/LiDAR/timing GRU with a continuous risk head;
- worst-domain stress conformal risk calibration;
- hysteretic `NORMAL` / `DEGRADED` / `MINIMAL_RISK` controller;
- calibration-only MRM threshold selection;
- log-grouped nuScenes split and leakage checks;
- 20-seed closed-loop aggregation and bootstrap intervals;
- AMD ROCm real-sequence FP32/AMP benchmark and equivalence verification; and
- reproducibility, visualization, and machine-readable evidence scripts.

This notice is informational and does not replace the license text or terms of
any upstream project or dataset.
