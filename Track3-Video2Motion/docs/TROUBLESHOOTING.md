# Troubleshooting

Everything here was hit during development. The ordering is by how much time it
costs you, not by which component it belongs to.

---

## The three that fail silently

These produce **no error message**. If you skip them you will spend days
debugging the wrong thing.

### 1. MuJoCo Playground's auto-reset does not restore `info`

**Symptom** — training degrades monotonically; the *untrained* network is the
best one. Ablations that differ a lot (penalties off, entropy off, both off)
produce nearly identical curves.

**Cause** — `BraxAutoResetWrapper` says so in its own docstring:

> If `full_reset` is disabled (default): only data and obs are reset, **not the
> environment info**.

Our reference frame index lives in `info["motion_idx"]`. After the first
episode the physical state resets while the index keeps advancing, so the two
desynchronise permanently and every later sample is garbage.

**Fix**

```python
wrap_env_fn=functools.partial(wrapper.wrap_for_brax_training, full_reset=True)
```

> If ablations with very different settings give the same curve, stop tuning
> and look at what they *share* — the data pipeline, the wrapper, the state
> machine.

### 2. GVHMR reuses its cache keyed on the file name

**Symptom** — a video with a name you have used before silently returns the
previous result. The only tell is `Time elapsed: 0.03s` in the log.

**Fix** — delete the output directory before each run:

```bash
rm -rf $V2M_GVHMR/outputs/demo/<name>
```

`scripts/run_pipeline.sh` does this for you.

### 3. unitree_mujoco computes the PD law inside the DDS callback

**Symptom** — the policy is perfectly stable in native MuJoCo but falls at
~18–47 steps over DDS. Increasing `kd` does not help.

**Cause** — `LowCmdHandler` computes the torque and writes `mj_data.ctrl`, so
the torque is held constant between commands:

| Context | PD loop rate |
|---|---|
| Training (position actuator) | 500 Hz — MuJoCo recomputes every substep |
| Real robot (motor driver firmware) | 1–2 kHz |
| unitree_mujoco bridge | **50 Hz zero-order hold** |

Measured, same policy and model, only this changed:

| PD loop | Survival (max 500) |
|---|---|
| 50 Hz ZOH, kd = 2 / 5 / 10 | 18 / 24 / 18 |
| 200 Hz substep loop | **500** |

**Fix** — apply `src/third_party_patches/` (done by `scripts/setup_dds.sh`).
The callback only caches the command; the torque is recomputed every simulation
step, which is what a real motor driver does.

---

## Installation

| Problem | Symptom | Fix |
|---|---|---|
| ROCm torch wheels | `No matching distribution found for triton==...+rocm...` | install `torch torchvision torchaudio pytorch-triton-rocm` in **one** command — they pin a matching local triton build |
| pytorch3d build | machine becomes unresponsive, `sshd` cannot fork, SSH dies with `kex_exchange_identification: Connection closed` | `MAX_JOBS=8`; an unbounded build spawns 30+ `cc1plus` processes |
| pytorch3d | `No module named 'torch'` during build | `--no-build-isolation` |
| chumpy | `No module named 'pip'`, and it aborts the whole batch | install alone, then `sed` `inspect.getargspec` → `getfullargspec` and drop the removed NumPy aliases |
| lightning | crashes on `pkg_resources` | `setuptools<81` |
| ultralytics 8.2.42 | YOLO checkpoint fails to load on torch ≥ 2.6 | `ultralytics>=8.4` (`weights_only=True` became the default) |
| wis3d / pycolmap | assumed optional | they are not — `cv2_utils.py` imports them at module level |
| JAX reports `cpu` | everything is unusably slow | stop and fix ROCm before installing anything else |

---

## AMD / gfx1100 specifics

**XLA graph-size ceiling.** With

```
num_minibatches × num_updates_per_batch > 32
```

XLA segfaults during code generation, with no Python-level exception. We ruled
out VRAM (28 MB used of 48 GB), `pmap`, and the environment. We use `16 × 2`.

**brax is incompatible with JAX 0.11.** brax 0.14.2 calls
`jax.device_put_replicated`, removed with the pmap migration. NVIDIA users can
downgrade JAX; AMD users cannot, because the version is pinned by
`jax-rocm7-plugin`. A shim must be injected *before* `import brax`:

```python
if not hasattr(jax, "device_put_replicated"):
    import jax.numpy as jnp
    def _dpr(x, devices):
        n = len(devices)
        st = jax.tree_util.tree_map(lambda y: jnp.stack([jnp.asarray(y)] * n), x)
        return jax.device_put(st, devices[0]) if n == 1 else st
    jax.device_put_replicated = _dpr
```

`jax.sharding.PositionalSharding` was removed too, so do not use it in the shim.

**MuJoCo Playground defaults to a CUDA-only backend.** Set `cfg.impl = "jax"`;
otherwise you get `IndexError: list index out of range` from
`warp.get_cuda_device`, which gives no hint about the real cause.

---

## Environment and reward design

| Problem | Consequence |
|---|---|
| `data.cvel`'s linear component is measured at `subtree_com`, not the body origin | 1.0 m/s error at the wrists — use `v = cvel[3:6] + ω × (xpos − subtree_com)` |
| A free joint's `qvel[3:6]` is the **body-frame** angular rate, not world frame | velocity rewards underflow to exactly 0 |
| `sim_dt = 0.005` on Playground's G1 | integration diverges; `base_z` reached −165911. Use **0.002** |
| `action_scale` too small | brax's tanh bounds actions to [−1, 1], so a position actuator only reaches `default_pose ± action_scale`. Our references needed up to 2.05 rad where 0.5 was available — the arms physically cannot lift. Make targets relative to the **reference pose** |
| `soft_joint_pos_limit_factor = 0.9` | the reference itself violates it on 269/298 frames, so perfect tracking is penalised −2.09/step. Use **1.0** |
| Reward scaled by `dt` | brax does not normalise the entropy term; `entropy_cost=5e-3 × entropy(≈41) ≈ 0.205` against a task reward of 0.044/step. Keep rewards O(1)/step and `entropy_cost=1e-3` |
| `deterministic_eval` defaults to `False` | evaluation uses the noisy policy, so the reported metrics are not the policy's actual quality |

### The policy cannot hold a pose past the end of the reference

**Symptom** — the motion is performed correctly, but if you keep the simulation
running after the last reference frame the robot slowly sags and topples.
Measured on our salute policy, holding the final frame:

| Steps held | `base_z` | |
|---|---|---|
| +20 | 0.779 | stable |
| +45 | 0.721 | sagging |
| **+63 (1.3 s)** | — | **falls** |

**Cause** — the episode terminates the moment the reference runs out:

```python
done = tracking_failure | (motion_idx >= T - 1)
```

so the policy is never trained on what comes after, and the final states get no
bootstrap, which under-estimates their value.

**Fix** — append a hold segment to the reference, with zero velocities:

```bash
python src/motion_prep.py --inp ... --out ... --hold_seconds 1.5   # the default
```

The policy is then required to settle and stand, which is also what the motion
means physically — a salute ends at attention. This changes the training data,
so it requires a retrain.

### Validate the reward function before trusting anything

```bash
python src/diagnostics/diag_perfect.py workdir/motions_bm/<name>.npz
```

Set the state exactly to a reference frame; **all six tracking rewards must
read 1.0000**. Anything else means a frame, reference-point or unit convention
is wrong — and in such an environment no policy can score, however good it is.

Run this the same day you touch the reward. It is far cheaper than reading
curves afterwards, and it caught two of the convention bugs listed above.

---

## Deployment

| Problem | Symptom | Fix |
|---|---|---|
| Sending joint angles to a torque actuator | different policies all fail at the **same step**, with a suspiciously small tracking error | dispatch on `actuator_biastype`: `none` = torque, `affine` = position |
| Wrong initial pose | falls within ~30 steps | start from the motion's first frame; a generic standing keyframe can differ by 36° while the policy's RSI perturbation is only ±0.1 rad |
| Standing keyframe height guessed | hard landing on startup | solve by contact bisection; `geom_xpos` is the geom **centre**, not its lowest surface |
| `lo` is not multicast-capable | LowState never arrives | unicast CycloneDDS config, applied at **both** ends |
| Bridge imports pygame unconditionally | `ModuleNotFoundError: pygame` | install it even with the joystick disabled |
| Simulator started before the controller | robot collapses while waiting | do not advance physics until the first `LowCmd` arrives |
| GLFW viewer in a container | `GLFWError: DISPLAY missing` | use the headless recorder; under Xvfb, `x11grab` captures a frozen frame |
| Offscreen buffer > 640×480 | error telling you to edit a third-party XML | set `mj_model.vis.global_.offwidth/offheight` at runtime |

### Observations the robot cannot actually provide

`LowState` gives only joint angles, joint velocities, pelvis orientation and
pelvis angular rate. There is **no torso linear velocity** and **no world
position**. Both must be removed from the policy observation *before* training
— trimming dimensions afterwards means retraining.

The policy is trained in the `torso_link` frame while the IMU sits on the
pelvis, three waist joints away. Bridge the gap with one forward-kinematics
pass over the measured joint angles; no extra sensor is needed
(`src/deploy_track.py::TorsoFK`, measured orientation error 0.0000°).

---

## Method

| Lesson | Where it bit us |
|---|---|
| If very different ablations give the same curve, investigate what they share | penalties-off / entropy-off / both-off all overlapped; the cause was the wrapper |
| If two different inputs fail at the same point, the input is not the cause | two unrelated policies both fell at step 18 → a unit bug |
| Before claiming "A fixed B", confirm only A changed | "domain randomisation closed the sim2sim gap" was wrong — `kd` had changed too |
| Never use "didn't fall" as evidence of motion quality | a policy with 500/500 survival was barely moving its arms |
| A third-party simulator is not hardware | the bridge's 50 Hz zero-order hold is an implementation limit, not robot behaviour |
| Suspect your own new code first | when layer 3 fell, we validated our new torso FK (0.0000° error) before looking elsewhere |
