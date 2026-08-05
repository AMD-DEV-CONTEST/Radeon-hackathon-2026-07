# Open Drawer

A Franka Panda opens the drawer a prompt names, pulls it to a stop it cannot see,
feels the stop, and lets go before it drags the cabinet. Simulated in Genesis,
with pi0.5 fine-tuned to use a fingertip tactile array.

The question behind it: can touch make a vision-language-action policy safe to
use on a mechanism whose limit it cannot see?

**Source:** [github.com/Akbro23/open-drawer](https://github.com/Akbro23/open-drawer)

**Technical report:** [REPORT.md](REPORT.md) — measurements, scaling results,
and the reasoning behind the task design, the tactile pathway and the training
configuration.

**Demonstration video:** https://youtu.be/ys5NUw7-f2Q — the whole pipeline, from
collection through training to closed-loop evaluation.

## Demonstration

### Scripted teacher

One episode, shown twice. The only difference is whether the tactile release can
fire — on the right it is put out of reach, so the arm pulls for the full budget
and what moves is the furniture.

| Releasing on the felt stop | Same episode, release disabled |
|---|---|
| ![Teacher opening the left drawer and releasing on the felt stop](media/teacher_demo.gif) | ![The same episode with the tactile release disabled, dragging the cabinet](media/over_pull.gif) |
| cabinet moves **0.3 mm** | cabinet moves **92 mm** |

### Trained policy

The fine-tuned checkpoint driving the same loop, in both outcomes. The failure is
the more informative one: a grasp failure, upstream of language, vision and
touch.

| Reaches the stop and releases | Never moves the drawer |
|---|---|
| ![The trained policy opening the drawer and releasing](media/policy_success.gif) | ![The trained policy failing to move the drawer](media/policy_fail.gif) |
| stop found at **111.1 mm**, unseen until felt | by far the **most common failure** |

## Overview

```
"open the left drawer"  ->  approach  ->  descend onto the rail  ->  grip
                        ->  pull  ->  feel the stop  ->  release  ->  retract
```

A two-drawer cabinet stands free on a table. Three properties make each of the
three modalities load-bearing rather than decorative:

- **Language decides *which*.** The two drawers are geometrically and visually
  identical, so the prompt is the only thing that selects a target.
- **Touch decides *when*.** Each drawer's travel stop is randomized per episode
  and per environment, and nothing about a closed drawer reveals how far it will
  open. It cannot be memorized or seen; it has to be felt.
- **Over-pulling costs something.** The cabinet is not bolted down. Keep pulling
  after the drawer bottoms out and the cabinet slides, which fails the episode —
  so pulling for the maximum duration is not a winning strategy.

That last property is what the setup is for: finishing the task and doing it
safely are the same event, so a success rate here is also a safety measure.

The pipeline is three stages: a scripted teacher records demonstrations in
batched simulation, pi0.5 is fine-tuned on them with a tactile pathway added to
its action expert, and the checkpoint is scored closed-loop in the same
simulator.

## Requirements

| | |
|---|---|
| Python | 3.12 exactly (`requires-python = "==3.12.*"`) |
| GPU | ROCm-capable, ≥32 GB for training; collection and evaluation need ~2 GB |
| Disk | ~100 GB — dataset ~256 MB, each training checkpoint ~17 GB |
| Accounts | Hugging Face (with the PaliGemma licence accepted), Weights & Biases |

### Install uv

Everything is driven through [uv](https://docs.astral.sh/uv/), which manages the
Python version, the virtual environment and the dependencies together.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the shell afterwards, or `source $HOME/.local/bin/env`, so `uv` is on
the path. `uv --version` should answer.

### Dependency specifications

Declared in `pyproject.toml`, resolved in `uv.lock`. Nothing is installed by
hand — `uv sync` reads both.

| Package | Version |
|---|---|
| `torch`, `torchvision`, `torchaudio`, `triton` | ROCm 7.2.1 wheels, pinned by URL to `repo.radeon.com` |
| `genesis-world` | 1.2.3 |
| `lerobot` | with the `training` and `pi` extras |
| `bitsandbytes` | ≥0.50 |

The PyTorch wheels are pinned by exact URL rather than by version specifier, so
the ROCm build is not something the resolver can substitute.

## Setup

```bash
git clone https://github.com/Akbro23/open-drawer.git
cd open-drawer
```

### 1. Credentials

```bash
cp .env.example .env
```

Then open `.env` and fill in two values:

- **`HF_TOKEN`** — a *read* token from
  https://huggingface.co/settings/tokens. Used to download `lerobot/pi05_base`
  and its PaliGemma tokenizer.
- **`WANDB_API_KEY`** — from https://wandb.ai/authorize. Training logs only;
  pass `--wandb.enable=false` to train without one.

**Then accept the PaliGemma licence** at
https://huggingface.co/google/paligemma-3b-pt-224, signed in as the same
account. This is a separate step from creating the token, and skipping it is the
most common way setup fails: the tokenizer download returns 403 no matter how
valid the token is.

`.env` is gitignored and is read by the next step.

### 2. Environment

```bash
source scripts/instance-env.sh
```

This does three things:

1. **Points the uv and Hugging Face caches at persistent storage.** A
   container's own filesystem does not survive a restart, and pi0.5 plus its
   tokenizer are several GB that are not worth fetching twice.
2. **Loads `.env`**, exporting `HF_TOKEN` and `WANDB_API_KEY`.
3. **Switches package and model downloads to mirrors** — `UV_DEFAULT_INDEX` to
   the Tsinghua PyPI mirror and `HF_ENDPOINT` to `hf-mirror.com`. This matters
   **if you are running from mainland China**, where PyPI and `huggingface.co`
   are effectively unreachable. Outside China, either skip this step entirely or
   export your own values first: every variable it sets honours one already
   present, so `UV_DEFAULT_INDEX=https://pypi.org/simple` set beforehand wins.

It prints what it set, reporting the two secrets as `set` or `MISSING` without
echoing them, and appends itself to `~/.bashrc` so later shells pick it up.

### 3. Install

```bash
uv sync
```

Installs the ROCm PyTorch stack, Genesis, lerobot and bitsandbytes, and installs
this project itself so its commands (`render`, `rollout`, `collect`, `train`,
`evaluate`) exist on the path.

**Source step 2 before this.** Both mirrors replace their upstream rather than
adding to it, and `UV_DEFAULT_INDEX` decides the URLs written into `uv.lock` —
so a lock produced in a shell that never sourced it points at the wrong index.

### 4. Check it works

```bash
uv run render --envs 1
```

Runs one scripted episode and writes `out/episode.mp4` and
`out/episode_wrist.mp4`, plus a dump of the derived geometry. It should report
`success=True`. This exercises the simulator, the renderer and the tactile
sensors without needing any model weights, so it separates setup problems from
model problems.

## Reproducing the results

Three stages, in order. Each depends on the previous one's output, and the
default paths chain automatically.

### 1. Collect the dataset

```bash
uv run collect
```

Runs the scripted teacher over 1024 episodes — 8 batches of 128 environments —
and writes them in LeRobot format to `data/open_drawer`. Only successful
episodes are recorded. **Takes about 80 minutes** and produces ~256 MB.

Then verify the dataset means what the deployment loop thinks it means:

```bash
uv run evaluate --regression
```

This is the replay regression: it feeds the teacher's own recorded actions back
through the inference loop and checks that the episodes reproduce. It needs no
checkpoint and takes under a minute. **If it fails, do not train** — the
recorded actions and the evaluation loop disagree, and a policy trained on them
would be solving a different control problem.

### 2. Train

```bash
scripts/train.sh
```

Fine-tunes pi0.5 with the tactile pathway for 10000 steps at batch 16, using an
8-bit AdamW. **Takes about 10 hours.** The script launches it detached from the
terminal, so the session can be closed; it prints the log path and the commands
to follow, check and stop the run. Checkpoints land in
`out/train/open_drawer/checkpoints/` every 2500 steps.

```bash
tail -f out/train-<timestamp>.log        # follow
ps -p $(cat out/train.pid)               # still alive?
scripts/train.sh --resume=true           # continue after a crash
```

To run in the foreground, or to change anything, call the command directly —
every lerobot flag is passed through and overrides the defaults:

```bash
uv run train --steps=2000 --batch_size=8 --wandb.enable=false
```

In wandb, `tactile_cond_norm` and `tactile_cond_ratio` report the magnitude of
the tactile contribution to the action expert's conditioning. Both start at
exactly zero by construction, so their climbing is the evidence that touch is
being used at all.

### 3. Evaluate

```bash
uv run evaluate
```

Runs the trained checkpoint closed-loop in the simulator and scores it by the
same criteria as the teacher: the target drawer reached its stop, the gripper
released, the other drawer never moved, and the cabinet stayed put. It also
reports **release latency** — control steps between the true stop and the
release — which is the measure of whether the tactile channel is doing its job.

It scores 64 episodes — 4 batches of 16 environments, `--envs` and `--batches`
to change that — reading
`out/train/open_drawer/checkpoints/last/pretrained_model` unless `--checkpoint`
says otherwise. Add `--video out/eval.mp4` to film one environment of the first
batch with the live task state burned in, which is how the policy clips above
were made.

> Do not evaluate while training is running. Both load a 4B model onto the same
> GPU.

## Command reference

| Command | What it does |
|---|---|
| `uv run render` | Film one teacher episode to mp4, with live task state burned in |
| `uv run rollout` | Teacher success rate and physics throughput; `--scaling 32,64,128` sweeps |
| `uv run collect` | Record the LeRobot dataset; `--scaling 8,16,32` probes the host-RAM ceiling |
| `uv run train` | Fine-tune pi0.5 + tactile |
| `uv run evaluate` | Score a checkpoint closed-loop; `--regression` replays the teacher instead |
| `scripts/instance-env.sh` | Caches, secrets and mirrors (source it) |
| `scripts/train.sh` | Launch training detached, with disk and duplicate-run checks |

Every command takes `--help`.

## Repository map

```
open_drawer/
  config.py          every tunable, frozen dataclasses; asserts its own geometry
  assets.py          generated cabinet MJCF: carcass, two drawers, rails
  randomize.py       target side, per-drawer stops, cabinet pose, grasp residual
  scene.py           batched build and reset; per-env travel limits
  robot.py           batched IK, velocity-limited moves, the control tick
  tactile.py         taxel grids, the 24-dim feature, the peak reading
  task_state.py      rail pose, success latch, release latency
  teacher.py         the six phases, in lockstep across environments
  record.py          (observation, action) pairs at 25 Hz
  collect.py         LeRobot dataset writer, plus a RAM scaling probe
  policy_tactile.py  pi0.5 with tactile wired into the action expert
  train.py           lerobot-train wrapper with an 8-bit optimizer
  eval.py            policy in the loop; the replay regression
  rollout.py         success rate and throughput
  render_episode.py  mp4 plus the derived-geometry dump

scripts/
  instance-env.sh    caches, secrets and mirrors
  train.sh           detached training launcher
```

Generated directories — `assets/` (rewritten from config on every scene build),
`data/` and `out/` — are gitignored.

## Credits

This project is [Apache-2.0](LICENSE) licensed. That covers the code here; the
fine-tuned checkpoint is a derivative of pi0.5 and carries Gemma's terms, below.

The pipeline this project started from — Genesis scene, scripted teacher,
LeRobot dataset, policy fine-tune and closed-loop evaluation, all on a single
Radeon — follows the shape of
[wangxunx/franka_fruit_pick_demo](https://github.com/wangxunx/franka_fruit_pick_demo).

Built on [Genesis](https://github.com/Genesis-Embodied-AI/Genesis) and
[LeRobot](https://github.com/huggingface/lerobot), both Apache-2.0. The weights
are `lerobot/pi05_base`, LeRobot's port of
[openpi](https://github.com/Physical-Intelligence/openpi) by Physical
Intelligence; [policy_tactile.py](open_drawer/policy_tactile.py) subclasses that
implementation and replicates one initializer from it, for the reason given
there. The Franka Panda description arrives with Genesis and is
[MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie)'s
(Apache-2.0), derived from Franka Emika's published URDF. The cabinet is
generated from `config.py`.

pi0.5 is built on PaliGemma, so the checkpoint produced here inherits its
licence: *Gemma is provided under and subject to the Gemma Terms of Use found at
[ai.google.dev/gemma/terms](https://ai.google.dev/gemma/terms)*.

Every stage of this project ran on a Radeon Pro W7900D under ROCm, on cloud
instance time provided by AMD for the Radeon hackathon.
