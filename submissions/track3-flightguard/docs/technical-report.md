# FlightGuard Track 3 Technical Report

**Team:** 做实验摸鱼呢

**Participant:** Haokai Ding (solo)

## Project overview

FlightGuard is a simulation-only, Radeon-native controller-qualification workflow for quadrotors. It generates reproducible off-nominal Genesis contexts, evaluates matched controller pairs through PyTorch ROCm on one AMD Radeon GPU, and packages the resulting metrics and videos for rapid review before hardware testing.

The primary result is a focused controller intervention. In 384 primary adversarial pairs, changing only the vertical gains raises mission success from 194/384 to 371/384. In 192 separate retention-heldout pairs, success rises from 121/192 to 192/192. There are zero nominal-only wins in either suite.

## Team contribution

Haokai Ding designed and implemented the system, ran the experiments, analyzed the results, created the demo, and prepared the submission.

## Motivation and application

Hardware flight tests are expensive and slow to repeat. A robotics team needs a fast way to expose failures, isolate one controller change, and decide whether that change deserves hardware time. FlightGuard makes that decision process reproducible on Radeon.

The workflow serves embodied-AI researchers and flight-control developers:

1. generate deterministic mass, thrust, wind, delay, and gate-course conditions;
2. run matched Genesis missions on one Radeon;
3. compare mission outcomes and controller traces;
4. check finiteness and action saturation;
5. review the result through raw metrics, figures, and paired video.

## Technical architecture

The Challenge Arena evaluates nominal PD against `robust_z` with identical paired initial state, gates, vehicle/environment parameters, and random streams. Only two parameters change:

- `kp_z`: 2.5 → 8.0
- `kd_z`: 2.0 → 3.6

The controller setting was fixed before the three formal seeds ran. A bit-exact no-op checks the unchanged path. A zero-action kill-magnitude control yields 0/8 successes and 10.506417 m maximum paired-active divergence. These controls establish that the evaluation is sensitive to the intended intervention.

A second qualification lane evaluates the shared `robust_z` controller over seeds 303, 304, and 305 in 384 heldout three-gate contexts. Three registered replicas produce 1,152 method episodes. A training-distribution collector covers 192 additional environments.

## Exact results

### Paired controller capability

| Suite | Pairs | Nominal PD | `robust_z` | Added successes | Nominal-only wins |
|---|---:|---:|---:|---:|---:|
| Primary adversarial | 384 | 194/384 (50.5208%) | 371/384 (96.6146%) | +177 (+46.0938 pp) | 0 |
| Retention heldout | 192 | 121/192 (63.0208%) | 192/192 (100%) | +71 (+36.9792 pp) | 0 |

Primary failures fall from 190 to 13, a 93.1579% reduction. Per-seed success deltas are +57, +58, and +62. Strikes fall from 178 to 13 and terminal failures from 190 to 13. All paired traces are finite; every formal source reports one visible `AMD Radeon Graphics`; maximum applied-action saturation is 0.0 for both arms.

The 7-second paired Genesis replay shows one submitted pair from seed 144856705. Nominal PD collides at step 167 with 0/3 gates; `robust_z` completes 3/3 gates at step 479. Aggregate claims come from all 384 primary and 192 retention pairs.

### Heldout three-gate missions

Across 384 paired course contexts and 1,152 method episodes:

- `constant_velocity`: 384/384 mission successes and 1,152 gate passes;
- `hold_last`: 384/384 mission successes and 1,152 gate passes;
- `learned`: 384/384 mission successes and 1,152 gate passes;
- zero strikes, mission failures, terminal failures, or unfinished episodes;
- all tracked mission fields finite;
- exactly one visible Radeon in every source run.

The replicas tie exactly. This result therefore supports the shared controller and evaluator rather than learned-method superiority.

The observed samples cover mass scale 0.80046–1.19933, thrust scale 0.80609–1.19861, wind-acceleration norm 0–0.59828 m/s², and action delay 0–6 steps.

### Training-distribution collector

The collector retains 63/64, 62/64, and 61/64 environments across seeds 303, 304, and 305: **186/192 = 96.875%**. Position, velocity, quaternion, angular velocity, issued action, and applied action are finite in every source run. Maximum per-environment applied-action saturation is 0.0.

## AMD Radeon and ROCm execution

Genesis executes the batched simulation through PyTorch HIP/ROCm. Every mission and collector source reports one visible `AMD Radeon Graphics`, and GPU jobs are serialized.

The fixed one-Radeon scaling workload measures 2,227,200 transitions:

| Environments | Mean transitions/s | Mean GPU use | CV |
|---:|---:|---:|---:|
| 32 | 4,632.582556654058 | 77.3544% | 0.003122105834443068 |
| 128 | 18,354.411592309174 | 76.2593% | 0.0009916172953886402 |
| 256 | 36,383.01129648785 | 77.0864% | 0.002506217057283922 |
| 512 | 74,246.46385791198 | 78.4684% | 0.0033317633931520337 |

The 32→512 speedup is 16.027013647337444× with 1.0016883529585903 parallel efficiency. GPU use reaches 86%; maximum observed VRAM is 962,785,280 bytes. This is intra-device scaling for a fixed simulation workload.

## Innovation

FlightGuard combines a matched adversarial controller test, intervention self-checks, batched Radeon execution, and a short visual review path. The important unit is the complete decision loop: expose a failure, change one controller hypothesis, repeat it across three seeds, retain every nominal success, and present both capability and compute evidence together.

## Reproducibility

Run `python3 scripts/judge_smoke.py` from `submissions/track3-flightguard` for the fast CPU-only check. It validates the submitted Challenge Arena inputs, nominal mission and collector totals, paired diagnostics, figures, videos, and Radeon measurements.

For the full Genesis campaign, use [`scripts/reconstruct_challenge_arena_amd.py`](../scripts/reconstruct_challenge_arena_amd.py) as the serial one-Radeon entry point. Submitted inputs and raw outputs remain under `submission/evidence/`.

## Upstream contribution

[Genesis PR #3159](https://github.com/Genesis-Embodied-AI/genesis-world/pull/3159) updates the AMD Docker path from PyTorch 2.6 to AMD's PyTorch 2.8 image and adds a static regression test. It remains an open software contribution and is not counted as controller capability.

## Claim boundary

FlightGuard demonstrates controller qualification in Genesis over sampled contexts on one Radeon. It does not establish physical-flight safety, certification, sim-to-real transfer, a continuous flight envelope, population generalization, learned-method superiority, or SOTA superiority.
