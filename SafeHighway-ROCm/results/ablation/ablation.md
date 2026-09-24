# Reward-profile ablation

All policies are scored on the canonical baseline reward (`normalize_reward=True`, `collision_reward=-1`) so that runs trained under different shaping schemes remain comparable. Values are mean ± std across seeds.

## Main results

| Profile | Seeds | Collision rate | Survival rate | Mean speed | Step reward | Mean min TTC (s) | TTC violation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `random` | 9 | 90.0 ± 0.0% | 10.0 ± 0.0% | 25.09 ± 0.00 | 0.807 ± 0.000 | 0.58 ± 0.00 | 13.6 ± 0.0% |
| `baseline` | 3 | 81.1 ± 12.9% | 18.9 ± 12.9% | 26.40 ± 1.40 | 0.860 ± 0.030 | 0.92 ± 0.83 | 12.8 ± 4.1% |
| `penalty` | 3 | 100.0 ± 0.0% | 0.0 ± 0.0% | 29.38 ± 0.24 | 0.928 ± 0.004 | 0.01 ± 0.02 | 23.4 ± 4.6% |
| `ttc` | 3 | 38.9 ± 7.9% | 61.1 ± 7.9% | 25.52 ± 0.25 | 0.844 ± 0.006 | 1.63 ± 0.29 | 4.5 ± 1.2% |

## Action distribution

The baseline policy degenerates into a speed maximiser: it almost never brakes. Shaping is expected to restore the `SLOWER` action.

| Profile | LANE_LEFT | IDLE | LANE_RIGHT | FASTER | SLOWER |
| --- | ---: | ---: | ---: | ---: | ---: |
| `random` | 21.6% | 20.1% | 19.8% | 19.0% | 19.6% |
| `baseline` | 27.2% | 37.9% | 20.1% | 14.7% | 0.0% |
| `penalty` | 0.0% | 28.3% | 2.5% | 69.2% | 0.0% |
| `ttc` | 18.1% | 6.4% | 27.9% | 15.9% | 31.7% |
