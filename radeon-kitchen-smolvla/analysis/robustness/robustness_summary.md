# Sim-to-Real Robustness Envelope

All conditions reuse the same placement manifest. `robustness retention` is stressed success divided by nominal success.

| Condition | Episodes | Success | Rate | 95% Wilson CI | Retention |
|---|---:|---:|---:|---:|---:|
| nominal | 20 | 10 | 50.0% | 29.9%-70.1% | 100.0% |
| brightness_085_115 | 20 | 11 | 55.0% | 34.2%-74.2% | 110.0% |
| rgb_noise_std4 | 20 | 9 | 45.0% | 25.8%-65.8% | 90.0% |
| camera_dropout_50 | 20 | 4 | 20.0% | 8.1%-41.6% | 40.0% |
| occlusion_fraction25 | 20 | 4 | 20.0% | 8.1%-41.6% | 40.0% |
| action_delay_2 | 20 | 8 | 40.0% | 21.9%-61.3% | 80.0% |
| friction_low_1p2 | 20 | 8 | 40.0% | 21.9%-61.3% | 80.0% |
| friction_high_1p8 | 20 | 11 | 55.0% | 34.2%-74.2% | 110.0% |

## Interpretation

- Nominal is the paired control; it should remain the first row in the video and report.
- A falling curve is expected under stronger visual, timing, and contact perturbations; the engineering goal is to measure the envelope rather than hide failures.
- Camera dropout and occlusion test observation loss. Action delay and friction test control and contact gaps.
- These are simulation stress tests, not evidence of real-robot success. Real transfer still requires camera calibration and guarded hardware trials.
