# Fair nuScenes Trainval comparison

Evaluation uses 95 scenes grouped into 8 independent logs; 
all logs containing nuScenes-mini scenes are excluded. Confidence intervals use 10,000 paired log-cluster bootstrap resamples.

| Metric | Locked v2 | v3-large mean ± SD | v3 95% CI | Effect |
|---|---:|---:|---:|---:|
| Scenario accuracy | 80.5762% | 99.3446% ± 0.1093% | [99.2295%, 99.4767%] | 18.7684 pp |
| Camera accuracy | 94.9438% | 99.7816% ± 0.0517% | [99.6767%, 99.8815%] | 4.8378 pp |
| LiDAR accuracy | 85.7097% | 99.9985% ± 0.0027% | [99.9952%, 100.0000%] | 14.2888 pp |
| Delay accuracy | 99.9226% | 99.5631% ± 0.1593% | [99.4311%, 99.6736%] | -0.3595 pp |
| Risk MAE | 0.060401 | 0.012068 ± 0.000409 | [0.011532, 0.012754] | 80.0208 % reduction |
| Risk coverage | 100.0000% | 99.6010% ± 0.3106% | [99.4269%, 99.7784%] | -0.3990 pp |
| Conformal radius | 0.251078 | 0.058434 ± 0.004580 | [0.047057, 0.069811] | 76.7266 % reduction |
