# Chaal

A Unitree Go2 quadruped learns to walk on a command, and every part of that
happens on one AMD Radeon GPU: the physics of 4096 robots stepping in parallel,
the policy that controls them, and the PPO updates that train it. Nothing is
offloaded, and no pretrained policy is used. Training from scratch to a policy
that tracks velocity commands to within **0.096 m/s** takes **8 minutes 41
seconds** and 49.2 million environment steps.

Built for the AMD AI DevMaster Hackathon, Track 3: Physical AI. Simulation is
Genesis on its `gs.amdgpu` backend, learning is PPO via rsl_rl, both on ROCm.

## Watch it walk

**[youtu.be/MQitVuttx-w](https://youtu.be/MQitVuttx-w)**, 3 m 37 s. Four gaits
rendered from the trained checkpoint, then the measured results. The same file
is committed here as `demo-video.mp4`.

## Run it

Genesis needs an OpenGL platform to build a scene even when nothing is rendered,
and a ROCm container has no reason to ship one. This is the step that is missing
from every other set of instructions, so it comes first:

```bash
apt-get install -y libegl1 libegl-mesa0 libgl1-mesa-dri libosmesa6
```

```bash
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/chaal doctor
```

`doctor` on the box this was built on:

```
arch:            gfx1100
vram_gb:         48.0
compute_units:   48
torch:           2.10.0+rocm7.2.4.git3d3aa833
genesis:         1.3.0
gl_platform:     libEGL.so.1
ready
```

Train, evaluate, benchmark:

```bash
.venv/bin/chaal train --num-envs 4096 --iterations 500 --log-dir runs/go2
.venv/bin/chaal evaluate runs/go2/model_499.pt --num-envs 512
.venv/bin/chaal bench --envs 256,512,1024,2048,4096,8192
```

## What the GPU actually does

Every number below was measured on one Radeon PRO (`gfx1100`, RDNA 3, 48 GB)
through ROCm 7.2.4. The raw JSON is in `bench-results/`.

### Training

| | |
|---|---|
| Environments | 4096 in parallel |
| Iterations | 500 |
| Wall clock | 520.9 s |
| Experience | 49,152,000 environment steps |
| Throughput | 94,363 env-steps/s, simulation and PPO updates together |
| Per iteration | 1.042 s |
| Final mean reward | 811.94 |
| Mean episode length | 999.78 of a 1000-step cap |

Mean episode length that close to the cap would also be what standing still
looks like, so it is not evidence on its own. The velocity tracking term
contributes 45.85 of the reward, which works out to an average tracking error
around 0.14 m/s against commands drawn from -1 to +1 m/s. The robot is following
orders, not freezing.

### Where the time goes as you add environments

| environments | physics only | full training | s/iteration | peak VRAM |
|---|---|---|---|---|
| 256 | 41,518/s | 10,287/s | 0.60 | 0.18 GB |
| 512 | 81,591/s | 23,764/s | 0.52 | 0.21 GB |
| 1024 | 152,303/s | 42,282/s | 0.58 | 0.26 GB |
| 2048 | 270,530/s | 67,977/s | 0.72 | 0.36 GB |
| 4096 | 460,756/s | 93,546/s | 1.05 | 0.57 GB |
| 8192 | 849,217/s | 121,949/s | 1.61 | 0.98 GB |
| 16384 | 1,337,088/s | 138,330/s | 2.84 | 1.77 GB |
| 32768 | 1,700,322/s | 146,272/s | 5.38 | 3.42 GB |

Physics throughput rises almost linearly with environment count, 41 times over
that range. Training throughput does not. It climbs steeply to about 8192
environments and then flattens: **+13% from 8192 to 16384, and +6% from 16384 to
32768**, while the simulation work needed to feed it doubles each time. The gap
between the columns widens from 3.4x to 11.6x.

That is the finding. **Past roughly 8192 environments the simulator stops being
the bottleneck and the PPO update becomes it**, so more parallelism buys
simulation you cannot use. Anyone sizing a run on this hardware wants to know
that, and benchmarking only the simulator hides it completely.

Memory never enters into it. The largest configuration peaks at 3.42 GB on a
48 GB card. The limit is arithmetic in the update, not capacity.

Quoting the physics column alone would make this look 3 to 12 times better than
it is, depending where you took the number. Both are measured and both are in
the JSON.

## Does it survive anything it was not trained on?

Training randomises the velocity command and nothing else. Mass, friction and
disturbances are never varied, so every row below except the baseline is
off-distribution. 512 environments, 10 simulated seconds each.

| condition | survival | tracking error | return |
|---|---|---|---|
| baseline | 99.8% | 0.096 m/s | 477.1 |
| payload 3 kg | 100.0% | 0.106 m/s | 470.0 |
| payload 6 kg | 99.8% | 0.123 m/s | 450.7 |
| friction 0.5 | 100.0% | 0.113 m/s | 466.0 |
| friction 0.3 | 97.9% | 0.175 m/s | 431.0 |
| friction 0.2 | 91.2% | 0.288 m/s | 363.3 |
| push 0.5 m/s | 99.8% | 0.117 m/s | 462.4 |
| push 1.0 m/s | 98.6% | 0.147 m/s | 444.3 |

Survival on its own would be a dishonest metric, because a policy that freezes
never falls, so tracking error is reported beside it in every row.

## Two things that cost time, written down so they cost you less

Both are in [docs/upstream.md](docs/upstream.md) with reproductions.

**Genesis cannot build a scene without an OpenGL context**, even with
`show_viewer=False` and no cameras, and on a ROCm container the failure is a
PyOpenGL `AttributeError` that never mentions the real cause. Reported as
[genesis-world#3129](https://github.com/Genesis-Embodied-AI/genesis-world/issues/3129)
and closed as intended, the rendering being mandatory by design. The error
message was the part left standing, so it went upstream as a patch:
[genesis-world#3145](https://github.com/Genesis-Embodied-AI/genesis-world/pull/3145).

**`set_friction()` on one entity does nothing.** Genesis resolves a contact pair
by taking the larger of the two surfaces' friction, so changing only the robot
while the ground sits at its default of 1.0 is a silent no-op. Measured directly:

| robot mu | plane mu | survival | tracking error |
|---|---|---|---|
| 1.0 | 1.0 | 1.000 | 0.0972 m/s |
| 0.2 | 1.0 | 1.000 | 0.0973 m/s |
| 1.0 | 0.2 | 1.000 | 0.0960 m/s |
| 0.2 | 0.2 | 0.898 | 0.2977 m/s |

The first version of the robustness table above had a "low friction" row that
was really the baseline measured a second time. It does not raise, it does not
warn, and the number looks reasonable. Contributed as measurements to the
existing
[genesis-world#2718](https://github.com/Genesis-Embodied-AI/genesis-world/issues/2718).

Set both:

```python
robot.set_friction(mu)
plane.set_friction(mu)
```

## Layout

| file | what it is |
|---|---|
| `chaal/env.py` | the Go2 velocity-tracking environment, fully vectorised |
| `chaal/train.py` | PPO configuration and the training entry point |
| `chaal/bench.py` | the environment-count sweep, physics and training separately |
| `chaal/eval.py` | robustness conditions and their metrics |
| `chaal/cli.py` | `doctor`, `train`, `bench`, `evaluate` |
| `scripts/render.py` | renders a checkpoint to video, kept out of the training path |
| `bench-results/` | the raw JSON behind every number above |

## Licence

Apache-2.0. The Go2 URDF ships with Genesis. The reward formulation is the
standard velocity-tracking set used across legged locomotion work; the
contribution here is the pipeline on ROCm and the measurements, not the reward
design.
