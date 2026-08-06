# SafeSort-RL

## Language-Conditioned Reinforcement Learning for Safe Hazardous Material Handling

SafeSort-RL is a Track 3 robotics simulation project for AMD Radeon GPUs and
ROCm. It trains and demonstrates a policy for sorting simulated hazardous and
recyclable waste objects from natural-language task instructions.

## Submission Contents

This directory is the dedicated source-code repository for the project. It
contains:

- `env.py` - PyBullet waste-sorting environment
- `vision.py` - CLIP-based detector with an offline fallback
- `policy.py` - language-conditioned PyTorch policy module
- `train.py` - Stable-Baselines3 PPO training entry point
- `demo.py` - reproducible command-line demo
- `Dockerfile` - ROCm/PyTorch image containing the complete source tree
- `Genesis/` - bundled Genesis source used by the AMD environment/notebook
- `models/` - trained policy artifacts
- `results/` - final evaluation outputs
- `videos/` - demonstration video asset
- `SafeSort_RL_Track3_Technical_Paper.pdf` - technical report
- `SafeSort_RL_FINAL_PRESENTATION_READY.ipynb` - final notebook

## Docker Reproduction

Build the image from this directory:

```bash
cd SafeSort-RL
docker build -t safesort-rl:rocm .
```

Run the non-GUI demo on an AMD ROCm host:

```bash
docker run --rm \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  --ipc=host \
  --shm-size=8g \
  safesort-rl:rocm
```

Run with an interactive shell:

```bash
docker run --rm -it \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  --ipc=host \
  --shm-size=8g \
  safesort-rl:rocm bash
```

Export the image for submission or offline transfer:

```bash
docker save safesort-rl:rocm | gzip > safesort-rl-rocm.tar.gz
```

Evaluators can load it with:

```bash
gunzip -c safesort-rl-rocm.tar.gz | docker load
```

## Local ROCm Setup

On the provided Radeon Cloud environment, activate and verify the configured
ROCm stack:

```bash
cd SafeSort-RL
source ./setup_radeon.sh
```

For a fresh Python environment outside Docker:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e Genesis
```

Use a ROCm-enabled PyTorch build for AMD GPU acceleration. The Docker image
uses `rocm/pytorch:latest` as the base image.

## Quick Checks

```bash
python env.py
python vision.py
python policy.py
```

## Training

Train a PPO policy:

```bash
python train.py \
  --timesteps 500000 \
  --n-envs 4 \
  --device cuda \
  --verbose 1
```

For a short smoke test:

```bash
python train.py --timesteps 1000 --n-envs 1 --device cpu
```

Training outputs are written to `models/` and `logs/`.

## Demo

Run the saved policy in headless mode:

```bash
python demo.py --episodes 3
```

Run with the PyBullet GUI when a display is available:

```bash
python demo.py --gui --episodes 3
```

## Technical Overview

The environment uses PyBullet to simulate four waste objects: battery,
chemical bottle, plastic bottle, and syringe. A policy observes a 64x64 RGB
camera image and predicts continuous actions for a simplified robot gripper.

The detector uses CLIP prompts for zero-shot object identification when CLIP
weights are available. In offline environments, it falls back to a deterministic
image-statistics detector so the reproducibility scripts still execute.

Training uses Stable-Baselines3 PPO on top of PyTorch. On ROCm, AMD Radeon GPUs
are exposed through PyTorch's `cuda` device API.

## References

- PyBullet: https://github.com/bulletphysics/bullet3
- CLIP: https://github.com/openai/CLIP
- Stable-Baselines3: https://stable-baselines3.readthedocs.io
- ROCm: https://rocm.docs.amd.com
