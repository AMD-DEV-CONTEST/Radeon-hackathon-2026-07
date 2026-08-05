# ChronoSafe-Drive Paper-Grade Experiment Protocol

Protocol version: 1.1  
Frozen date: 2026-07-29  
Trainval amendment: 2026-07-30, before trainval feature construction or model fitting  
Primary platform: AMD Radeon (`gfx1100`) with ROCm/HIP 7.2

This document fixes the research questions, data partitions, metrics and model
selection rule before any large-dataset challenger is trained. The verified
`hybrid_timing_gru_v2` checkpoint is retained as the locked competition
baseline and is not tuned on the experiments below.

## Research questions

- **RQ1 — Compositional diagnosis:** Does factorizing camera, LiDAR and timing
  health improve diagnosis of compound degradation compared with a flat
  seven-class classifier?
- **RQ2 — Sim-to-real generalization:** Does joint MetaDrive + nuScenes
  training improve performance on complete held-out real scenes without
  reducing unseen-domain simulator performance?
- **RQ3 — Timing awareness:** Do causal packet-age and temporal-consistency
  features reduce false delay alarms under normal motion and visual blur?
- **RQ4 — Risk calibration:** Does robust conformal calibration achieve at
  least 90% empirical upper-risk coverage on unseen domains without forcing
  premature minimal-risk maneuvers?
- **RQ5 — Closed-loop safety:** Under compound degradation, does the calibrated
  controller reach a minimal-risk condition while avoiding premature stops
  during clean and isolated-degradation intervals?

## Fixed data partitions

### MetaDrive development domains

- Training: `3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97,101,103,107,109`
- Calibration: `113,127`
- Test: `131,137`

### MetaDrive external closed-loop domains

The following seeds are not used for model fitting, normalization, calibration
or threshold selection:

`149,151,157,163,167,173,179,181,191,193,197,199,211,223,227,229,233,239,241,251`

Seed 149 is the first locked demonstration run. Aggregate claims use all 20
external seeds and report confidence intervals rather than selecting the best
run.

### nuScenes mini cross-validation

- Unit of partition: complete scene, including every augmentation and temporal
  window derived from that scene.
- Five folds, two test scenes per fold.
- For each fold, two of the remaining scenes are calibration domains and six
  are training domains.
- Training random seeds: `2026, 2027, 2028`.
- Report mean, standard deviation and 95% confidence interval over the 15
  fold/seed runs.

### Larger nuScenes trainval challenger

- Raw archives are processed shard by shard because persistent storage is
  limited to 100 GB.
- Scene tokens are deduplicated; mini scenes must not occur in both development
  and external evaluation partitions.
- Split is generated once with seed `2026` at nuScenes-log level, targeting
  70% train, 15% calibration and 15% test scenes. Grouping by `log_token`
  prevents adjacent snippets from one collection drive crossing partitions.
- The generated manifest is committed before model training and never edited
  in response to test results.

## Controlled degradation factors

1. clean;
2. progressive camera blur;
3. camera freeze;
4. LiDAR dropout;
5. dynamic packet delay;
6. camera freeze plus LiDAR dropout;
7. camera blur plus dynamic delay.

Severity-stratified analysis must report weak, medium and strong corruption
bins. The held-out test evaluation uses the full severity range.

## Models and ablations

| ID | Model | Purpose |
|---|---|---|
| B0 | Fixed-rule health thresholds | Non-learning baseline |
| B1 | Single-frame MLP | Tests the value of temporal modeling |
| B2 | Flat seven-class GRU | Tests compositional factorization |
| B3 | Compositional GRU, simulator only | Original temporal baseline |
| B4 | Compositional GRU, sim + real, 10 features | Tests real-data mixing |
| B5 | Timing-aware compositional GRU without scenario loss | Feature ablation |
| B6 | Timing-aware compositional GRU without real data | Domain ablation |
| B7 | Full timing-aware compositional GRU | Proposed method |

All learned comparisons use the same scene/seed partitions, sequence length and
evaluation code. Hyperparameters are selected only from training and
calibration domains.

## Primary and secondary metrics

### Diagnosis

- scenario accuracy and macro-F1;
- camera, LiDAR and delay balanced accuracy and macro-F1;
- seven-class confusion matrix;
- per-severity recall;
- false delay alarm rate on clean and blur-only sequences.

### Risk calibration

- risk MAE and RMSE;
- empirical upper-risk coverage (target at least 0.90);
- conformal radius / mean upper-bound slack;
- coverage by domain, scenario and severity;
- risk reliability curve.

### Closed-loop safety

- minimal-risk maneuver success rate;
- final speed and time-to-stop;
- trigger step and trigger delay after compound-fault onset;
- false MRM rate before compound-fault onset;
- fraction of time in `NORMAL`, `DEGRADED`, `MINIMAL_RISK`;
- collision and lane-departure counts where exposed by the simulator;
- scenario accuracy, risk MAE and coverage during closed-loop operation.

### AMD/ROCm evidence

- GPU name, ROCm/HIP version and PyTorch version;
- training time, samples/s and peak allocated memory;
- inference latency p50/p95/p99 and throughput;
- batch-size scaling and optional mixed-precision comparison.

## Statistical reporting

- Never select or omit a seed based on its outcome.
- Report mean and standard deviation across independent domains/runs.
- Use domain-level bootstrap 95% confidence intervals with 10,000 resamples.
- Use paired Wilcoxon signed-rank tests for model comparisons on common domains;
  apply Holm correction when testing multiple ablations.
- Report effect size and absolute improvement, not only p-values.

## Model-selection rule

A challenger may replace `hybrid_timing_gru_v2` only if it satisfies all of the
following on the frozen protocol:

1. higher mean nuScenes scene-level macro-F1;
2. no more than one percentage-point reduction in MetaDrive scenario accuracy;
3. empirical risk coverage of at least 0.90;
4. at least 95% MRM success across the 20 external closed-loop seeds;
5. no statistically significant increase in premature MRM rate.

Otherwise the challenger is reported as an ablation or negative result and the
locked v2 checkpoint remains the submission model.

## Reproducibility and data governance

- Raw nuScenes files are never redistributed in the repository.
- Download URLs, official terms, hashes where available and generated scene
  manifests are documented.
- Every command writes a log under `evidence/` and a machine-readable summary.
- Model checkpoints, split manifests and final figures live under the persistent
  project directory.
- The final report distinguishes controlled synthetic degradation on real
  sensor streams from naturally occurring sensor faults.
