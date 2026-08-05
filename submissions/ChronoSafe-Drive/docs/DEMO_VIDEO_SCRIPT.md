# ChronoSafe-Drive Demo Video Script

Target duration: 3 minutes 40 seconds  
Language: English narration and English on-screen text only  
Format: 1920 x 1080, 30 fps, H.264 MP4

## Production roles

- **Wang Guanyu — Demo Video Producer:** demo planning, screen recording,
  editing, English subtitles, and final video production.
- **Wang Zhenyu — Technical Lead:** supplies validated footage, benchmark
  evidence, numerical claims, and final technical approval.
- **Han Liuxuan — Research Materials Coordinator:** organizes competition,
  technical, and reference materials used during production.

## Production rules

- Show the AMD Radeon and ROCm environment visibly at least once.
- Use only official Xvfb footage from the validated camera path.
- Do not use the invalid raw-headless renderer-bypass run.
- Keep plots on screen long enough to read the axes and sample size.
- State that nuScenes faults are controlled corruptions on real sensor streams.
- State that the project is a research prototype, not a certified controller.

## Shot-by-shot script

### 0:00-0:15 - Title and problem

**Visual**

- Project title over a clean MetaDrive driving clip.
- Split screen transitions to blur, camera freeze, and LiDAR dropout.

**On-screen text**

```text
ChronoSafe-Drive
Self-Diagnosis, Calibrated Risk, and Minimal-Risk Control
AMD Radeon + ROCm Physical AI
```

**Narration**

> Autonomous vehicles must remain safe when perception does not fail all at
> once. Cameras can blur or freeze, LiDAR can lose returns, and timestamps can
> become stale or misleading. ChronoSafe-Drive turns these failures into a
> complete perception-to-control safety loop.

### 0:15-0:40 - Architecture

**Visual**

- Animate the system architecture from sensors to controller.
- Highlight the eight-frame window and four output heads.

**On-screen text**

```text
Camera + LiDAR + packet timing
15 causal features x 8 frames
Factorized GRU: camera / LiDAR / timing / risk
Stress conformal upper-risk calibration
NORMAL -> DEGRADED -> MINIMAL_RISK
```

**Narration**

> We fuse causal camera, LiDAR, motion, and packet-timing evidence over eight
> frames. A factorized GRU independently diagnoses camera, LiDAR, and timing
> health while predicting continuous risk. Stress conformal calibration turns
> that prediction into a conservative upper bound used by an interpretable
> three-state controller.

### 0:40-1:05 - Real data and timestamp innovation

**Visual**

- Show nuScenes camera and LiDAR examples.
- Overlay timestamp traces for intact, missing, jittered, swapped, and spoofed
  conditions.
- Display the leakage-resistant split diagram.

**On-screen text**

```text
nuScenes v1.0-trainval
850 scenes | 34,149 camera-LiDAR pairs | 239,043 samples
Split by complete log_token: 592 / 128 / 130 scenes
```

**Narration**

> Training combines physics-based MetaDrive data with public nuScenes sensor
> streams. Our main innovation treats timing metadata itself as fallible. We
> train against missing, drifting, jittered, swapped, and falsely clean
> timestamps. Complete collection logs are kept within one split to prevent
> adjacent-drive leakage.

### 1:05-1:30 - Actual AMD ROCm workflow

**Visual**

- Record the AMD cloud terminal from the local computer.
- Show the project path, GPU/HIP/PyTorch identity, and the frozen-claim verifier.
- Keep the successful final line visible for two seconds.

**Commands shown on screen**

```bash
cd /workspace/persistent/ChronoSafe-Drive
python -c "import torch; print('GPU:', torch.cuda.get_device_name(0)); print('HIP:', torch.version.hip); print('PyTorch:', torch.__version__)"
python scripts/verify_submission_claims.py
```

**Narration**

> This is the actual persistent project workspace on the AMD cloud instance.
> PyTorch identifies the AMD Radeon GPU through ROCm and HIP. The submitted
> verifier checks every public headline number directly against frozen JSON
> evidence and completes 118 checks without retraining or hidden inputs.

### 1:30-2:05 - Closed-loop evidence replay

**Visual**

- Play the synchronized dashboard replay for unseen seed 149, generated from
  the committed validated-Xvfb closed-loop CSV.
- Show diagnosis, upper risk, vehicle speed, and controller mode together.
- Pause briefly at compound-fault onset and MRM trigger.

**On-screen text**

```text
Evidence replay from validated MetaDrive Xvfb run
Frozen MRM threshold: 0.62
No test-seed tuning
```

**Narration**

> This dashboard replays the committed evidence from an unseen MetaDrive seed
> evaluated through the validated camera path under Xvfb, without bypassing
> camera effects.
> As compound degradation persists, the calibrated risk crosses the threshold
> selected only on two calibration seeds. The controller first reduces speed,
> then latches the minimal-risk maneuver and brakes to a near-stop.

### 2:05-2:30 - Closed-loop aggregate

**Visual**

- Show the 20-seed aggregate chart and a compact metric card.

**On-screen text**

```text
20 unseen closed-loop seeds
MRM success: 100%
Premature MRM: 0%
Diagnosis accuracy: 97.07%
Risk coverage: 99.83%
Final speed: 0.0138 km/h
```

**Narration**

> Across all 20 frozen external seeds, every run reaches the minimal-risk
> condition, with zero premature triggers. Mean diagnosis accuracy is 97.07
> percent, calibrated risk coverage is 99.83 percent, and final speed is about
> 0.014 kilometers per hour.

### 2:30-2:55 - Robustness result

**Visual**

- Animate a baseline-versus-robust grouped bar chart.
- Emphasize channel swap and spoofed-clean conditions.

**On-screen text**

```text
Severe timestamp failures
Missing 50%: 84.78% -> 97.77%
Jitter 2 frames: 85.30% -> 96.69%
Channels swapped: 72.02% -> 99.34%
Spoofed clean: 67.96% -> 95.08%
```

**Narration**

> Timestamp-robust training improves severe corruption accuracy by 11 to 27
> percentage points. Intact accuracy remains 99.34 percent, a transparent
> trade-off of less than half a percentage point for much stronger failure
> robustness.

### 2:55-3:25 - AMD Radeon and ROCm

**Visual**

- Show terminal hardware evidence: AMD Radeon, `gfx1100`, HIP 7.2, and PyTorch
  ROCm.
- Transition to the benchmark plot.

**On-screen text**

```text
AMD Radeon gfx1100 | ROCm/HIP 7.2
FP32 batch 1 p50: 0.559 ms
FP32 batch 1024: 1.37M sequences/s
AMP/FP32 diagnosis agreement: 100%
```

**Narration**

> Training and inference run on an AMD Radeon gfx1100 GPU with ROCm 7.2. The
> frozen model delivers sub-millisecond inference and 1.37 million temporal
> sequences per second at batch 1024. AMP preserves every diagnostic decision
> across 8,192 real samples, with risk error below seven ten-thousandths.

### 3:25-3:40 - Closing

**Visual**

- Return to the safely stopped vehicle.
- Show the GitHub repository and project title.

**On-screen text**

```text
ChronoSafe-Drive
Diagnose early. Calibrate risk. Stop safely.
Open, reproducible, and built on AMD ROCm.
```

**Narration**

> ChronoSafe-Drive shows how multimodal temporal diagnosis, calibrated risk,
> and closed-loop control can work together on AMD ROCm: diagnose early,
> calibrate uncertainty, and stop safely.

## Required visual assets

- one synchronized dashboard replay from a committed validated-Xvfb CSV;
- open `docs/demo_assets/closed_loop_replay.html` locally in a browser for the
  replay recording;
- one actual AMD cloud terminal recording showing GPU/HIP/PyTorch identity;
- architecture diagram;
- nuScenes sample panel with timing traces;
- timestamp robustness grouped bar chart;
- 20-seed closed-loop aggregate card;
- AMD/ROCm hardware terminal capture; and
- ROCm latency/throughput benchmark figure.

## Final quality gate

- Every caption, axis, legend, subtitle, and terminal annotation is English.
- No personally identifying information, cloud credentials, or private URLs
  appear in the recording.
- The video never claims road deployment or safety certification.
- Numerical claims exactly match committed JSON evidence.
- Audio peaks below clipping and remains intelligible at normal laptop volume.
