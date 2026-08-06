"""Booster-derived reward curriculum for humanoid soccer.

Real Booster T1 RoBoLeague match skills -> RL reward terms:

    stay upright / footwork      -> upright, alive
    chase the ball               -> approach_ball
    dribble / keep control       -> ball_control
    shoot toward goal            -> ball_to_goal, goal_scored
    get up after a fall          -> fall_penalty, recovery_bonus
    efficient movement           -> energy_penalty

Each helper is a pure function of tensors so it runs batched on the AMD GPU.
`compute_reward` selects/weights terms per the active task, letting you run a
curriculum: balance -> chase -> dribble -> shoot -> coop.
"""
from __future__ import annotations

import torch


def r_upright(torso_up: torch.Tensor) -> torch.Tensor:
    # torso_up: cosine of torso z-axis vs world-up in [-1, 1]; reward closeness to 1.
    return torch.clamp(torso_up, min=0.0)


def r_alive(fallen: torch.Tensor) -> torch.Tensor:
    return (~fallen).float()


def r_approach_ball(dist_to_ball: torch.Tensor, prev_dist: torch.Tensor) -> torch.Tensor:
    # dense progress reward: positive when the robot closes distance to the ball.
    return (prev_dist - dist_to_ball)


def r_ball_control(dist_to_ball: torch.Tensor, radius: float) -> torch.Tensor:
    # reward keeping the ball within ~2 body radii (dribbling).
    return torch.exp(-torch.clamp(dist_to_ball - radius, min=0.0) * 3.0)


def r_ball_to_goal(ball_vel_to_goal: torch.Tensor) -> torch.Tensor:
    # component of the ball velocity pointing at the goal (m/s), clamped.
    return torch.clamp(ball_vel_to_goal, min=0.0)


def r_goal(scored: torch.Tensor) -> torch.Tensor:
    return scored.float()


def r_fall(fallen: torch.Tensor) -> torch.Tensor:
    return fallen.float()


def r_recovery(just_recovered: torch.Tensor) -> torch.Tensor:
    return just_recovered.float()


def r_energy(action: torch.Tensor) -> torch.Tensor:
    return torch.sum(action ** 2, dim=-1)


# tasks -> which terms are active (curriculum gating)
TASK_TERMS = {
    "balance": {"upright", "alive", "fall", "recovery", "energy"},
    "chase":   {"upright", "alive", "approach_ball", "fall", "recovery", "energy"},
    "dribble": {"upright", "alive", "approach_ball", "ball_control", "fall", "recovery", "energy"},
    "shoot":   {"upright", "alive", "ball_control", "ball_to_goal", "goal_scored", "fall", "recovery", "energy"},
    "coop":    {"upright", "alive", "ball_control", "ball_to_goal", "goal_scored", "fall", "recovery", "energy"},
}


def compute_reward(obs: dict, action: torch.Tensor, w: dict, task: str) -> torch.Tensor:
    """Return per-env scalar reward tensor.

    `obs` is a dict of batched tensors produced by envs/soccer_env.py, expected keys:
        torso_up, fallen, dist_to_ball, prev_dist_to_ball, ball_vel_to_goal,
        scored, just_recovered
    `w` is the reward-weight block from the YAML config.
    """
    terms = TASK_TERMS.get(task, TASK_TERMS["chase"])
    total = torch.zeros_like(obs["torso_up"])

    if "upright" in terms:
        total += w["upright"] * r_upright(obs["torso_up"])
    if "alive" in terms:
        total += w["alive"] * r_alive(obs["fallen"])
    if "approach_ball" in terms:
        total += w["approach_ball"] * r_approach_ball(obs["dist_to_ball"], obs["prev_dist_to_ball"])
    if "ball_control" in terms:
        total += w["ball_control"] * r_ball_control(obs["dist_to_ball"], w.get("_ball_radius", 0.11))
    if "ball_to_goal" in terms:
        total += w["ball_to_goal"] * r_ball_to_goal(obs["ball_vel_to_goal"])
    if "goal_scored" in terms:
        total += w["goal_scored"] * r_goal(obs["scored"])

    # penalties / bonuses always applied when present
    total += w["fall_penalty"] * r_fall(obs["fallen"])
    total += w["recovery_bonus"] * r_recovery(obs["just_recovered"])
    total += w["energy_penalty"] * r_energy(action)
    return total
