# Radeon MJX LEAP Hand

**Track:** Track 3 — Physical AI Challenge  
**Team:** DMrobot  
**Application:** Radeon MJX LEAP Hand

Radeon MJX LEAP Hand is a reproducible JAX/ROCm workflow for training and evaluating a simulated 16-DoF LEAP Hand on an AMD Radeon GPU. The task is `LeapCubeRotateZAxis`: retain a cube and rotate it about the reward-aligned positive Z axis.

The project uses the official Google DeepMind MuJoCo Playground source directly at pinned commit `220abb9d6a41eaa258047dacf9ca70a92e008b78`. The submission does not copy or claim the upstream project. DMrobot contributes the validated Radeon integration procedure, GPU/MJX verification utility, checkpoint compatibility path, task-aware evaluator, manifests, and documentation.

## Official deliverables

| Requirement | Material |
|---|---|
| Technical report | [English technical report](https://github.com/liyan03/radeon-mjx-leap-hand/blob/2a5dcdc0ece9ef8f429dba61aeb2e90a6912251b/TECHNICAL_REPORT.md) |
| Dedicated source repository | [DMrobot source at frozen commit `2a5dcdc`](https://github.com/liyan03/radeon-mjx-leap-hand/tree/2a5dcdc0ece9ef8f429dba61aeb2e90a6912251b) |
| Reproducibility README | [Environment, training, evaluation, and troubleshooting](https://github.com/liyan03/radeon-mjx-leap-hand/blob/2a5dcdc0ece9ef8f429dba61aeb2e90a6912251b/README.md) |
| Quantitative evaluator | [`eval_leap_policy.py`](https://github.com/liyan03/radeon-mjx-leap-hand/blob/2a5dcdc0ece9ef8f429dba61aeb2e90a6912251b/eval_leap_policy.py) |
| Run and evaluation manifests | [Machine-readable results](https://github.com/liyan03/radeon-mjx-leap-hand/tree/2a5dcdc0ece9ef8f429dba61aeb2e90a6912251b/results) |
| Demonstration video | **Pending before final submission.** The real Radeon-server recording must be added; synthetic footage will not be substituted. |
| Final Orbax checkpoint | **Pending external artifact publication.** Exact packaging instructions are provided in the source repository. |
| Docker image | Not claimed. Docker is preferable rather than mandatory; the validated deliverable is the native Radeon Cloud setup. |

## Architecture

```text
AMD Radeon gfx1100 (48 GiB)
  → ROCm 7.2.1
  → JAX 0.8.2 ROCm backend
  → MuJoCo MJX vectorized simulation
  → MuJoCo Playground LEAP Hand
  → Brax PPO
  → Orbax checkpoint
  → batched raw-environment evaluation
```

No external dataset is used. PPO experience is generated online by vectorized MJX simulation.

## Radeon execution evidence

| Item | Validated value |
|---|---:|
| GPU | AMD Radeon Graphics, `gfx1100`, 48 GiB |
| ROCm | `7.2.1` |
| Python | `3.12.3` |
| JAX | `0.8.2`, backend `gpu`, `RocmDevice(id=0)` |
| MuJoCo Playground | `220abb9d6a41eaa258047dacf9ca70a92e008b78` |
| Brax | `0.14.2` |
| Observed GFX utilization | `100%` |
| Observed GFX clock | `2232 MHz` |
| Observed VRAM use | approximately `2.1 / 49.1 GiB` |

Low framebuffer occupancy is not evidence of CPU fallback. JAX reported the Radeon ROCm device, and AMD-SMI showed an active compute engine.

## Training and result

The PPO run used 512 parallel environments and completed checkpoint step `100,270,080`.

One deterministic 256-episode evaluation of the final checkpoint under the nominal simulator configuration produced:

| Metric | Result |
|---|---:|
| Return, mean ± population SD | `30.8215 ± 6.8834` |
| Return P05 / median / P95 | `22.6888 / 32.6272 / 36.1719` |
| Full-horizon survival | `99.22%` (`254/256`) |
| Cube-drop rate | `0.78%` (`2/256`) |
| Mean signed Z angular velocity | `1.2403 rad/s` |
| Mean reward-aligned signed equivalent turns | `4.9116` |
| JIT / rollout time | `27.96 s / 15.19 s` |

`LeapCubeRotateZAxis` has no official binary success metric. Full-horizon survival is therefore reported as survival, not as task success. The result is limited to one nominal evaluation and does not establish baseline improvement, multi-seed reproducibility, domain-randomized robustness, or sim-to-real transfer.

## Technical contributions

- A pinned and validated Radeon ROCm → JAX → MJX → PPO workflow for LEAP Hand.
- A raw-environment evaluator that avoids AutoReset contamination of terminal accounting.
- Task-aware rotation, retention, percentile, and numerical-validity metrics.
- A non-invasive Brax 0.14.2 checkpoint loader for nullable initializer metadata.
- Explicit separation of Radeon compute from EGL/OSMesa visualization on headless servers.

## Team contribution

DMrobot performed the Radeon environment integration, MJX validation, PPO training, checkpoint management, evaluator implementation, result interpretation, reproducibility documentation, and submission packaging.

## Draft status

This branch is intentionally marked as a draft until the required real demonstration video and a stable checkpoint artifact link are added. The source, report, evaluator, manifests, and reproducibility guide are already public and frozen at the commit linked above.
