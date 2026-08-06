# Acceptance Evidence Export

This directory is a deterministic export of existing historical artifacts, **not a new training or acceptance run**.

## Training

- Source: `archive/train_v8.log` (SHA-256 recorded in `summary.json`)
- Parsed iterations: 0–499 (500 rows)
- Final: 24,576,000 steps, reward 93.07, mean distance 1.1319 m, mean episode `goals_total` metric 1358.375
- Throughput: final 4,315, mean 4,299.588, peak 4,618 steps/s
- Log-reported duration: 5,723 seconds
- Curve: `training/training_curve.csv`

The five requested reward components are **missing**, because the log emits only aggregate reward: approach_ball, ball_control, ball_progress, ball_contact, goal_scored. Configuration terms or weights are not measurements and were not substituted.
The custom `Mean episode goals_total` value is preserved with its original mean-episode semantics; it is not an independently counted number of scored goals.

## GPU telemetry

- Source: `track3-data/benchmark/gpu_samples.csv` (612 samples)
- Observed peak utilization: 100.0%
- Observed peak VRAM: 23737.827 MB of 51522.830 MB reported
- Labeled iteration range: 60–499

The collector starts after training began and includes idle samples after iteration 499. These values are historical training-labeled telemetry, not full-window telemetry and **not a GPU stress-test result**.

## Models and provenance limits

`training/model_hashes.csv` contains SHA-256 values recomputed from local bytes. Manifest hashes are retained only for comparison. The manifest describes remote paths and historical metadata; this export does not independently verify those remote claims, checkpoint quality, evaluation performance, or checkpoint-to-ONNX lineage.
