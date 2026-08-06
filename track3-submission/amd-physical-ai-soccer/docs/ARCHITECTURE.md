# Architecture & Design Notes

## Thesis

Robot soccer decomposes into a small set of learnable motor + decision skills.
We observed these directly in **Booster T1 RoBoLeague** matches and turn each
into an RL reward term, trained as a curriculum on a single **AMD Radeon GPU** via
**Genesis + ROCm**.

## Booster observation -> RL mapping

| Booster match behavior | Sub-task | Reward terms | Week |
|---|---|---|---|
| stay standing, footwork | balance | upright, alive | W1 |
| run to the ball | chase | approach_ball | W1 |
| keep the ball close | dribble | ball_control | W2 |
| strike toward goal | shoot | ball_to_goal, goal_scored | W2 |
| get up after a fall | recovery | fall_penalty, recovery_bonus | W1-W2 |
| attacker/defender split | coop | role-conditioned obs + shared reward | W3 |

## Curriculum

Train sequentially, warm-starting each stage from the previous checkpoint:

```
balance -> chase -> dribble -> shoot -> coop
```

This keeps early training stable (locomotion first) before adding ball dynamics
and multi-agent interaction — mirrors how a real player learns.

## System components

- **Sim**: Genesis, GPU backend, headless, `num_envs` parallel (4096 default).
- **RL**: PPO (compact in-repo loop; swappable for skrl/rsl_rl).
- **Policy**: shared-trunk MLP actor-critic, Gaussian continuous actions (joint targets).
- **Rewards**: pure batched-tensor functions, task-gated (`rewards/reward.py`).
- **GPU proof**: `scripts/benchmark_gpu.py` + `rocm-smi` for the 20-pt ROCm criterion.

## Multi-agent (coop, W3)

For simplified multi-agent play, reuse a single shared policy with a **role flag** in the
observation (attacker=0 / defender=1). Reward is team-shared for goals, with
role-specific shaping (attacker weighted on ball_to_goal, defender on
intercept-distance). This maps the attacker/defender coordination seen in Booster
matches without training separate networks — cheap and demo-friendly.

## What is NOT in scope

- sim-to-real deployment (hackathon is simulation-only).
- photorealistic rendering (offscreen frames only for demo mp4).
- custom robot URDF authoring (start from a stock humanoid, swap to T1-like later).

## Open-source contribution plan (10 pts)

- Contribute the Genesis soccer env wrapper + PPO baseline back upstream
  (either to Genesis examples or the official hackathon repo) with docs.
