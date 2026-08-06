# Booster Agent — RL Chase Policy for SoccerSim

This directory contains the Booster Studio Agent code for Sim2Sim validation
of the trained RL chase policy (`chase_v3_policy.onnx`).

## Architecture

```
src/booster_agent/
├── src/
│   ├── main.py           # Agent entry point (AgentBase subclass)
│   └── rl_playbook.py    # RL-enhanced playbook (ONNX policy for chaser)
├── models/
│   └── chase_v3_policy.onnx  # Trained high-level policy (19→3 dim)
├── res/                  # Resources (icons, etc.)
└── README.md             # This file
```

## How It Works

1. **Agent entry** (`main.py`): Loads ONNX model, initializes SoccerTeamRuntime
2. **RL Playbook** (`rl_playbook.py`): Overrides `chaser_command()` to use ONNX policy
   - Builds 19-dim observation from match state (ball position, goal direction, robot pose)
   - Runs ONNX inference → velocity command (vx, vy, vyaw)
   - Clips to training range: vx/vy ∈ [-0.3, 0.3], vyaw ∈ [-0.4, 0.4]
   - Kicks when within 0.3m of ball
3. **Other roles** (supporter, goalkeeper): Use default rule-based behavior

## ONNX Model Interface

| Property | Value |
|----------|-------|
| Input | `obs` [batch, 19] (float32) |
| Output | `action` [batch, 3] (float32) — vx, vy, wz |
| Opset | 17 |
| Architecture | MLP: 19→256→128→64→3 (ELU activations) |

### Observation Layout (19-dim)

| Index | Component | Source |
|-------|-----------|--------|
| 0-2 | filtered_lin_vel (body frame) | Robot odometry/IMU |
| 3-5 | filtered_ang_vel (body frame) | Robot IMU |
| 6-7 | projected_gravity (xy) | Robot orientation |
| 8-9 | ball_rel_body (xy) | Ball position - robot position, rotated to body frame |
| 10-11 | ball_vel_body (xy) | Ball velocity (estimated from position delta) |
| 12 | dist_to_ball | Euclidean distance to ball |
| 13-14 | goal_dir (xy, normalized) | Goal direction in body frame |
| 15 | goal_dist | Distance to opponent goal |
| 16-18 | last_hl_actions (vx, vy, wz) | Previous velocity command |

## Deployment in Booster Studio

1. Copy this directory to the AMD GPU cloud instance
2. Place `chase_v3_policy.onnx` in `models/`
3. Open Booster Studio via VNC
4. Open SoccerSim
5. Load this agent directory as the team agent
6. Configure opponent as rule-based AI
7. Start match

## Training Environment Match

The ONNX model was trained in Genesis with:
- Floating-base T1 humanoid (6-DoF trunk)
- Frozen t1_walk.pt for low-level locomotion (720→21 dim)
- PPO high-level policy (19→3 dim, 10 Hz)
- Curriculum: clip 0.05→0.1→0.2→0.3/0.4, approach_ball=30
- Chase v3 results: 0 falls, ball_d monotonically decreasing, ep_len 200+
