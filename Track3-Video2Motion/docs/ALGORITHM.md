# Algorithm Design and Evolution

**From "track joint angles" to "track the whole body in 3-D" — a full rewrite**

---

## 1. What the problem actually is

A retargeted motion is a **kinematic animation**: it prescribes joint angles
frame by frame and contains **no physics**.

A human holds a pose through continuous active balancing — calf muscles
adjusting, centre of mass correcting. The reference records only the *result*
of a pose, never the *control effort* that maintains it.

So feeding joint angles straight into a physics engine makes the robot fall
immediately. That is not a retargeting defect; the information is simply absent.
Reinforcement learning supplies it: **stay close to the reference while
obeying physics and not falling over**.

---

## 2. First design: track upper-body joint angles (failed)

### 2.1 The design

Inherit MuJoCo Playground's G1 Joystick environment — it is sim2real validated
and ships a carefully tuned set of balance/contact/posture rewards. Pin the
velocity command to zero so it learns "stand still", then add upper-body
tracking on top:

```python
UPPER_START = 15                    # 0-11 legs, 12-14 waist, 15-28 arms
r_track = exp(-5.0 * mean((q[15:] - ref[15:])**2))      # weight 2.0
r_leg   = exp(-2.0 * mean((q[:15] - default[:15])**2))  # weight 0.5
```

Disable the official terms that fight against performing a prescribed motion
(`stand_still`, `pose`, `feet_air_time`, `feet_phase`).

### 2.2 The metrics looked excellent

| | Salute | Tennis |
|---|---|---|
| MJX evaluation (20 episodes) | 20/20 · 1000 steps · 9.08° | 20/20 · 1000 steps · 24.98° |
| Native MuJoCo | 500/500 · 5.64° | 500/500 · 16.94° |

### 2.3 But the robot staggered and the arms did nothing

**Both success criteria were bad:**

| Metric | Why it is bad |
|---|---|
| "500/500 steps without falling" | **standing still also scores perfectly** |
| "19.66° joint-angle error" | weakly correlated with visual similarity; after a fall the arms keep moving so the error stays small |

**The deeper problem was the reward structure.** The episode terminated only on
a fall, so:

```
don't fall → full episode length → high return
tracking is a small fraction of the per-step reward,
so ignoring the motion costs far less than falling
```

The policy rationally converged to "stand firmly, wave the arms vaguely".

### 2.4 A second, independent showstopper

At steady state a position actuator gives `q ≈ ctrl`, and
`ctrl = default_pose + action × action_scale`. brax's `NormalTanhDistribution`
squashes actions into **[−1, 1]**, so the reachable joint range is exactly
`default_pose ± 0.5 rad` (±28.6°).

Measured peak deviation required by the references:

| Motion | Peak requirement | Available | Shortfall |
|---|---|---|---|
| Salute | right elbow **1.709 rad (98°)** | 0.5 rad | **3.4×** |
| Tennis | shoulder roll **2.051 rad (118°)** | 0.5 rad | **4.1×** |

For tennis, **24% of upper-body targets are physically unreachable**. The arms
literally cannot lift. This has nothing to do with the reward, and no amount of
training fixes it.

**The two errors masked each other**: fixing the reward would give the policy
the *motivation* to track, but it still could not reach; raising
`action_scale` would let it reach, but it had no *motivation*. Fixing either
alone shows no improvement — which is why this hid for so long.

---

## 3. Second design: the BeyondMimic recipe

### 3.1 What we are following

[BeyondMimic](https://github.com/HybridRobotics/whole_body_tracking)
(UC Berkeley Hybrid Robotics) performs jumping spins, sprints and cartwheels,
and does it with **one policy per motion and a shared hyperparameter set** —
exactly the product shape we want.

**But it cannot run on AMD:**

| Implementation | Dependency | AMD |
|---|---|---|
| Official `whole_body_tracking` | Isaac Lab 2.1.0 + Isaac Sim 4.5.0 | ❌ CUDA-only |
| mjlab reproduction | MuJoCo-**Warp** | ❌ CUDA-only |
| **This project** | MuJoCo **MJX** (JAX-ROCm) | ✅ |

So the MDP had to be reimplemented on MJX from the source, term by term.

### 3.2 The key differences

| | First design | BeyondMimic recipe |
|---|---|---|
| Tracking target | 14 upper-body **joint angles** | 3-D **position / orientation / linear & angular velocity of 14 body links** + root anchor |
| Lower body | pose regularisation only | tracked as well |
| **Termination** | only on falling | **as soon as tracking error exceeds a threshold** |
| **Reset** | always standing, frame 0 | **RSI**: full state (root pose, root velocity, joint angles, joint velocities) from a random reference frame |
| Reward | leftover joystick terms + 2 custom | 6 tracking + 3 penalties, nothing else |
| Sampling | uniform | adaptive, weighted toward high-failure segments (not implemented here) |

**Why track in 3-D instead of joint space**: joint-angle error correlates
poorly with visual similarity — 5° at the shoulder and 5° at the wrist look
completely different, yet joint space weights them identically. 3-D position
error maps directly onto what the eye sees.

**Why early termination is the crux**: it makes "not tracking" immediately cut
the episode short, so the policy cannot farm survival reward. This is
DeepMimic's single most important ingredient.

### 3.3 Rewards (matched against `tracking_env_cfg.py`)

All of the form `exp(−error/std²)`:

| Term | Weight | std | Meaning |
|---|---|---|---|
| `motion_global_anchor_pos` | 0.5 | 0.30 | root height |
| `motion_global_anchor_ori` | 0.5 | 0.40 | root orientation |
| `motion_body_pos` | 1.0 | 0.30 | 3-D position of 14 bodies |
| `motion_body_ori` | 1.0 | 0.40 | orientation of 14 bodies |
| `motion_body_lin_vel` | 1.0 | 1.00 | linear velocity |
| `motion_body_ang_vel` | 1.0 | 3.14 | angular velocity |
| `action_rate_l2` | −0.1 | — | action smoothness |
| `joint_limit` | −10.0 | — | joint limits |

**Termination**: `anchor_z > 0.25 m`, anchor orientation error > 0.8, any of
the four end effectors (both ankles, both wrists) `z > 0.25 m`, or timeout.

### 3.4 Reference alignment

Before comparing, the reference is translated and rotated onto the robot's
current anchor horizontal position and yaw:

```python
delta_pos = [robot_anchor_x, robot_anchor_y, ref_anchor_z]   # z from reference
delta_ori = yaw(robot_anchor_quat · ref_anchor_quat⁻¹)       # yaw only
body_pos_rel = delta_pos + delta_ori · (ref_body_pos − ref_anchor_pos)
```

Horizontal drift and global heading are therefore **not** penalised (only the
shape of the motion is), while **height, pitch and roll still are** — so losing
balance still costs.

---

## 4. Observation design driven by deployment

This is where we go further than a straight port: **deployment constraints must
be baked into the observation before training**, because trimming dimensions
afterwards means retraining.

Unitree's `LowState` provides:

```
motor_state[i].q / .dq      29 joint angles and velocities
imu_state.quaternion        pelvis orientation
imu_state.gyroscope         pelvis angular rate
```

There is **no torso linear velocity** and **no world position** (no global
localisation).

| Term | Why removed | Cost |
|---|---|---|
| torso linear velocity | not provided by the IMU | controlled experiment: same policy, same simulator, only zeroing this term dropped survival from 500/500 to 190/500 |
| `anchor_pos_b` | requires torso world position | one retrain |

Both moved into the critic — an **asymmetric actor-critic**. BeyondMimic ships
the same idea as its `Wo-State-Estimation` configuration.

**Final policy observation, 154 dimensions:**

| Component | Dim | Source |
|---|---|---|
| reference joint angles + velocities | 58 | motion file |
| `anchor_ori_b` (orientation error, 6-D representation) | 6 | IMU quaternion |
| gyroscope | 3 | IMU |
| joint angles (relative to default pose) | 29 | `motor_state.q` |
| joint velocities | 29 | `motor_state.dq` |
| previous action | 29 | internal |

**Action**: `motor_targets = ref_joint_pos[t] + action × 0.5` — relative to the
**reference pose**, not the default pose, so reachability holds by construction
(see §2.4).

### Frame propagation

The policy is trained in the **torso_link** frame; the G1's IMU is on the
**pelvis**, three waist joints away. One forward-kinematics pass using the
measured joint angles bridges the gap — **no extra sensor required**:

```python
qpos[3:7] = pelvis_quat;  qpos[7:] = measured_q
qvel[3:6] = pelvis_gyro;  qvel[6:] = measured_dq
mj_forward()  →  xquat[torso_link],  mj_objectVelocity(torso, local)
```

Measured: orientation error **0.0000°**, angular-rate error 0.031 rad/s.

---

## 5. Differences from BeyondMimic

### 5.1 Deliberate deviations (all platform or framework driven)

| Item | BeyondMimic | This project | Reason |
|---|---|---|---|
| Simulation backend | Isaac Sim / MuJoCo-Warp | **MuJoCo MJX** | both are CUDA-only |
| RL framework | rsl_rl | **brax PPO** | the MJX ecosystem |
| Learning rate | 1e-3 with adaptive KL | **3e-4 fixed** | brax has no adaptive-KL schedule; copying the ceiling value without the schedule is not "faithful" |
| Minibatching | 4 × 5 epochs | **16 × 2** | gfx1100 XLA graph-size limit: the product must be ≤ 32 |
| `entropy_cost` | 0.005 | **0.001** | brax does not normalise the entropy term; 5e-3 made the entropy bonus outweigh the task reward (measured 0.205 vs 0.044 per step) |
| Action reference | `default_pose + a` | **`ref[t] + a`** | brax's tanh bounds actions, so reachability must be guaranteed |
| `sim_dt` | 0.005 | **0.002** | Playground's G1 is far stiffer; 0.005 diverges |
| Soft joint limit factor | 1.0 | **1.0** | matched (we briefly used 0.9, which penalised the reference itself at −2.09/step) |
| Training steps | 30000 iters ≈ 2.95B | **371M** | six-hour single-GPU budget |
| Adaptive sampling | failure-weighted | **not implemented** | validate the trunk first |

### 5.2 What we added

| Item | Description |
|---|---|
| **Deployment-aware observations** | the two unavailable terms are removed *before* training, so the policy passes layer 3 directly |
| **Torso frame propagation** | resolves IMU-on-pelvis vs policy-on-torso |
| **Three-layer progressive validation** | one variable per layer, so failures localise |
| **Pure-NumPy inference** | 251,066 parameters, zero JAX dependency; one set of weights runs across all three layers and on hardware |

---

## 6. The 8 bugs found during the port

In discovery order. **The first seven are all genuine bugs, but while the
eighth remained, fixing any of them showed no improvement.**

| # | Bug | Consequence | Fixing it alone helps? |
|---|---|---|---|
| 1 | `mjx_env` API is `make_data`, not `init` | error | required |
| 2 | `data.cvel`'s linear part is measured at **subtree_com**, not the body origin | 1.0 m/s error at the wrists | no |
| 3 | A free joint's `qvel[3:6]` is the **body-frame** angular rate | velocity rewards underflowed to exactly 0 | no |
| 4 | `sim_dt=0.005` diverges | `base_z` reached −165911 | no |
| 5 | `action_scale` too small; motion unreachable | arms physically cannot lift | no |
| 6 | Soft limit 0.9 conflicts with the reference | the reference itself penalised on 269/298 frames at −2.09/step | no |
| 7 | Reward scale / entropy ratio | entropy bonus 3.4× the task reward | no |
| 8 | **auto-reset does not restore `info`** | **all training data is garbage** | **yes** |

### How #8 was found

Three training runs all degraded monotonically (the untrained network was
best). **The ablation was decisive:**

| Group | Configuration | `ep_len` trend |
|---|---|---|
| Baseline | penalties on, entropy 1e-3 | 36 → 19.4 |
| A | both penalties off | 36 → 22.4 |
| B | penalties off + zero entropy | 36 → 20.9 |
| C | penalties on + zero entropy | 36 → 22.5 |

**Three very different configurations, nearly identical curves.** The
degradation is independent of the reward composition, so the cause must be
something *all* groups share.

Playground's `BraxAutoResetWrapper` docstring states:

> only data and obs are reset, **not the environment info**.

The reference frame index lives in `info["motion_idx"]`, so after the first
episode the physical state resets while the index keeps advancing —
permanently desynchronised. With `motion_idx >= T−1` in the termination
condition, everything after that is 1-step garbage.

Changing one boolean, `full_reset=True`, turned "gets worse with training" into
stable convergence.

> This also explains the first design's flailing arms: its index used modulo
> wrap-around, so desynchronisation did not kill the episode — it just asked the
> policy to track the **wrong phase**. The bug was there from day one; it was
> simply less lethal in the old environment.

---

## 7. How the acceptance criteria evolved

**Old criteria (both bad):**

| Metric | Why bad |
|---|---|
| "500/500 steps without falling" | standing still scores perfectly |
| "19° upper-body joint error" | weak correlation with visual similarity |

**New criteria:**

1. **Perfect-tracker check** — set the state exactly to a reference frame; all
   six tracking rewards must read **1.0000**. Any deviation means a frame,
   reference-point or unit convention is still wrong.
2. **Motion completed** — percentage of the reference actually performed (not
   "how many steps it survived").
3. **Body position error** (metres) — measured in 3-D, directly tied to what is
   visible.
4. **Side-by-side video** — reference left, policy right; judged by eye.

Criterion 4 is the final arbiter. The first three only screen out obvious
failures; they are never used to declare success.

---

## 8. Final results

| Layer | Physics | Robot model | Inference | Interface | Motion completed | Body position error |
|---|---|---|---|---|---|---|
| Zero-action baseline | — | — | — | — | 44/156 (28.2%) | 0.0772 m |
| 1 | MJX (JAX/GPU) | Playground G1 | brax | direct memory | **156/156** | **0.0269 m** |
| 2 | MuJoCo native C | Playground G1 | **pure NumPy** | direct memory | **156/156** | **0.0273 m** |
| 3 | MuJoCo native C | **Unitree official G1** | pure NumPy | **DDS** | **156/156** | 4–5° joint error |

Layers 1 and 2 differ by **0.0004 m** — swapping both the physics engine and
the entire inference stack changes almost nothing, which is what "the policy
itself is clean" looks like.

Training: 371M steps, 357.5 min, 17,326 env-steps/s. **100% completion is
reached around 112M steps (2 hours)**; the remaining time buys smoothness.
