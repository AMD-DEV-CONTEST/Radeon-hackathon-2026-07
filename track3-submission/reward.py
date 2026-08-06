"""Booster-derived reward curriculum for humanoid soccer.

Adds gait-related rewards from booster_gym:
    tracking_lin_vel_x/y  -> velocity tracking (exponential kernel)
    tracking_ang_vel      -> angular velocity tracking
    feet_swing            -> rewards correct swing phase per gait cycle
    feet_slip             -> penalize foot sliding when in contact
"""
from __future__ import annotations

import torch


def r_upright(torso_up: torch.Tensor) -> torch.Tensor:
    return torch.clamp(torso_up, min=0.0)


def r_alive(fallen: torch.Tensor) -> torch.Tensor:
    return (~fallen).float()


def r_tracking_lin_vel_x(command, actual, sigma):
    return torch.exp(-torch.square(command - actual) / sigma)


def r_tracking_lin_vel_y(command, actual, sigma):
    return torch.exp(-torch.square(command - actual) / sigma)


def r_tracking_ang_vel(command, actual, sigma):
    return torch.exp(-torch.square(command - actual) / sigma)


def r_feet_swing(gait_process, gait_frequency, feet_contact, swing_period):
    left_swing = (torch.abs(gait_process - 0.25) < 0.5 * swing_period) & (gait_frequency > 1e-8)
    right_swing = (torch.abs(gait_process - 0.75) < 0.5 * swing_period) & (gait_frequency > 1e-8)
    return (left_swing & ~feet_contact[:, 0]).float() + (right_swing & ~feet_contact[:, 1]).float()


def r_feet_slip(feet_pos, last_feet_pos, feet_contact, dt, episode_length_buf):
    vel_sq = torch.square((last_feet_pos - feet_pos) / dt).sum(dim=-1)
    return (vel_sq * feet_contact.float()).sum(dim=-1) * (episode_length_buf > 1).float()


def r_approach_ball(dist_to_ball, prev_dist):
    # Soft clamp via tanh: preserves weak negative gradient when ball moves away
    # (bad contact), while capping large spikes from ball bounces. This gives
    # the policy a signal to prefer contact that pushes ball toward goal.
    delta = prev_dist - dist_to_ball
    return torch.tanh(delta)


def r_vel_to_ball(base_lin_vel, ball_dir_world):
    """Reward actual linear velocity component toward the ball (world frame).

    Unlike the tanh-scaled ``approach_ball`` delta, this scales directly with
    real forward progress, so standing still yields zero regardless of distance.
    Only progress toward the ball counts; moving away gives zero.
    """
    vel_toward = torch.sum(base_lin_vel[:, :2] * ball_dir_world, dim=-1)
    return torch.clamp(vel_toward, min=0.0)


def r_ball_progress(ball_goal_dist, prev_ball_goal_dist):
    """Potential-based shaping: reward ANY reduction in ball-to-goal distance,
    including kicks. This is the main 'play the ball forward' signal."""
    return prev_ball_goal_dist - ball_goal_dist


def r_ball_contact(min_foot_dist, contact_radius=0.15):
    """Bonus while either foot is within contact radius of the ball."""
    return (min_foot_dist < contact_radius).float()


def r_approach_angle(ball_rel_body, goal_dir_body):
    """Reward approaching the ball from the side OPPOSITE the goal.

    When the robot is between the ball and its own goal, it will push the ball
    toward the attack goal on contact.  +1 = perfectly behind ball, -1 = in front.
    """
    ball_dir = ball_rel_body / (torch.norm(ball_rel_body, dim=-1, keepdim=True) + 1e-6)
    return (ball_dir * goal_dir_body).sum(dim=-1)


def r_directed_contact(min_foot_dist, ball_vel_to_goal, contact_radius=0.20):
    """Bonus for foot-near-ball WHILE the ball is moving toward the goal."""
    in_contact = (min_foot_dist < contact_radius).float()
    good_direction = torch.clamp(ball_vel_to_goal, min=0.0)
    return in_contact * good_direction


def r_ball_control(dist_to_ball, radius):
    return torch.exp(-torch.clamp(dist_to_ball - radius, min=0.0) * 3.0)


def r_ball_to_goal(ball_vel_to_goal):
    return torch.clamp(ball_vel_to_goal, min=0.0)


def r_goal(scored):
    return scored.float()


# ─────────────────────────────────────────────────────────────────────────
# Cooperative (multi-robot) shaping terms.
# These are OPT-IN: compute_reward only applies them when the corresponding
# term name is in the active task AND the required obs fields are present, so
# single-agent training (chase_hl) is completely unaffected. They read team-
# level geometry that the multi-agent harness supplies via the obs dict.
# ─────────────────────────────────────────────────────────────────────────

def r_defensive_position(self_xy, ball_xy, defend_goal_xy, in_possession,
                         spread=2.0, lateral_tol=0.5):
    """Reward a robot for staying goal-side of the ball when its team is NOT in
    possession (zonal defending). High when the robot lies between the ball and
    its own goal, dropping as it drifts ball-side or wanders too wide.

    Disabled (zeroed) when the team has the ball — then the robot should push up.
    """
    axis = defend_goal_xy - ball_xy                       # (N,2) ball→own-goal
    axis_len = torch.norm(axis, dim=-1, keepdim=True) + 1e-9
    axis_u = axis / axis_len
    rel = self_xy - ball_xy                              # (N,2)
    proj = torch.sum(rel * axis_u, dim=-1, keepdim=True)  # goal-side distance
    lateral = torch.norm(rel - proj * axis_u, dim=-1, keepdim=True)
    on_side = torch.sigmoid(proj / spread)              # 0..1
    tight = torch.exp(-torch.clamp(lateral - lateral_tol, min=0.0))
    return (on_side * tight).squeeze(-1) * (1.0 - in_possession.squeeze(-1))


def r_support_position(self_xy, ball_xy, attack_goal_xy, in_possession,
                       push=1.5, crowd_tol=0.5):
    """Reward a non-carrier for offering an advanced, un-crowded passing outlet
    when its team HAS the ball. High when the robot is ahead of the ball (toward
    the attack goal) but not crowding the carrier. Disabled when not in possession.
    """
    axis = attack_goal_xy - ball_xy
    axis_len = torch.norm(axis, dim=-1, keepdim=True) + 1e-9
    axis_u = axis / axis_len
    rel = self_xy - ball_xy
    proj = torch.sum(rel * axis_u, dim=-1, keepdim=True)
    lateral = torch.norm(rel - proj * axis_u, dim=-1, keepdim=True)
    advanced = torch.sigmoid((proj - push) / 1.0)
    not_crowding = torch.exp(-torch.clamp(crowd_tol - lateral, min=0.0) * 2.0)
    return (advanced * not_crowding).squeeze(-1) * in_possession.squeeze(-1)


def r_coop_goal(scored, scored_my_team):
    """Shared-credit goal reward: ALL three teammates are rewarded when the team
    scores, so supporters learn to enable the scorer instead of ball-watching.
    `scored_my_team` is a per-env float (1 if the goal was for my team).
    """
    return scored.float() * scored_my_team.float()


def r_fall(fallen):
    return fallen.float()


def r_recovery(just_recovered):
    return just_recovered.float()


def r_energy(action):
    return torch.sum(action ** 2, dim=-1)


def r_lin_vel_z(base_lin_vel_z):
    return torch.square(base_lin_vel_z)


def r_ang_vel_xy(base_ang_vel_xy):
    return torch.sum(torch.square(base_ang_vel_xy), dim=-1)


def r_orientation(projected_gravity_xy):
    return torch.sum(torch.square(projected_gravity_xy), dim=-1)


def r_action_rate(last_actions, actions):
    return torch.sum(torch.square(last_actions - actions), dim=-1)


def r_command_penalty(actions):
    """Penalize non-zero velocity commands — encourages 'do nothing' first."""
    return torch.sum(torch.square(actions), dim=-1)


def r_dof_acc(last_dof_vel, dof_vel, dt):
    return torch.sum(torch.square((last_dof_vel - dof_vel) / dt), dim=-1)


TASK_TERMS = {
    "balance": {"upright", "alive", "tracking_lin_vel_x", "tracking_lin_vel_y", "tracking_ang_vel",
                "feet_swing", "feet_slip", "lin_vel_z", "ang_vel_xy", "orientation",
                "fall", "recovery", "energy", "action_rate", "dof_acc"},
    "chase":   {"upright", "alive", "tracking_lin_vel_x", "tracking_lin_vel_y", "tracking_ang_vel",
                "feet_swing", "feet_slip", "approach_ball",
                "lin_vel_z", "ang_vel_xy", "orientation",
                "fall", "recovery", "energy", "action_rate", "dof_acc"},
    "dribble": {"upright", "alive", "tracking_lin_vel_x", "tracking_lin_vel_y", "tracking_ang_vel",
                "feet_swing", "feet_slip", "approach_ball", "ball_control",
                "lin_vel_z", "ang_vel_xy", "orientation",
                "fall", "recovery", "energy", "action_rate", "dof_acc"},
    "shoot":   {"upright", "alive", "tracking_lin_vel_x", "tracking_lin_vel_y", "tracking_ang_vel",
                "feet_swing", "feet_slip", "ball_control", "ball_to_goal", "goal_scored",
                "lin_vel_z", "ang_vel_xy", "orientation",
                "fall", "recovery", "energy", "action_rate", "dof_acc"},
    "coop":    {"upright", "alive", "tracking_lin_vel_x", "tracking_lin_vel_y", "tracking_ang_vel",
                "feet_swing", "feet_slip", "ball_control", "ball_to_goal", "goal_scored",
                "lin_vel_z", "ang_vel_xy", "orientation",
                "fall", "recovery", "energy", "action_rate", "dof_acc"},
    # Hierarchical: frozen low-level handles gait; high-level outputs velocity commands.
    # Drops tracking/feet terms (low-level concern), keeps ball-focused + safety terms.
    "chase_hl": {"upright", "alive", "approach_ball", "vel_to_ball", "approach_angle", "ball_control", "ball_progress",
                 "ball_contact", "directed_contact", "ball_to_goal", "goal_scored",
                 "lin_vel_z", "ang_vel_xy", "orientation",
                 "fall", "recovery", "action_rate"},
    "balance_hl": {"upright", "alive", "lin_vel_z", "ang_vel_xy", "orientation",
                   "fall", "recovery", "action_rate", "command_penalty"},
    # multi-robot cooperative task: extends chase_hl with team-shaping terms. Only active
    # in multi-agent training (multiagent_obs on) and when the harness supplies
    # the team-geometry obs fields; otherwise these terms are inert.
    "coop_hl": {"upright", "alive", "approach_ball", "approach_angle", "ball_control", "ball_progress",
                 "ball_contact", "directed_contact", "ball_to_goal", "goal_scored",
                 "defensive_position", "support_position", "coop_goal",
                 "lin_vel_z", "ang_vel_xy", "orientation",
                 "fall", "recovery", "action_rate"},
}


"""Phase-B robustness training reuses the chase_hl reward contract."""
TASK_TERMS["chase_hl_robust"] = TASK_TERMS["chase_hl"]


ACCEPTANCE_REWARD_COMPONENTS = (
    "approach_ball",
    "ball_control",
    "ball_contact",
    "ball_progress",
    "goal_scored",
    "fall_penalty",
)


def compute_reward_components(obs: dict, w: dict, task: str) -> dict[str, dict[str, torch.Tensor]]:
    """Return the acceptance reward terms using the production reward formulas.

    Components not active for ``task`` are omitted rather than reported as
    synthetic zeroes.  ``fall_penalty`` is unconditional in ``compute_reward``
    and is therefore always present.
    """
    terms = TASK_TERMS.get(task, TASK_TERMS["chase"])
    raw: dict[str, torch.Tensor] = {}
    if "approach_ball" in terms:
        raw["approach_ball"] = r_approach_ball(obs["dist_to_ball"], obs["prev_dist_to_ball"])
    if "ball_control" in terms:
        raw["ball_control"] = r_ball_control(obs["dist_to_ball"], w.get("_ball_radius", 0.11))
    if "ball_contact" in terms:
        raw["ball_contact"] = r_ball_contact(obs["min_foot_dist"])
    if "ball_progress" in terms:
        raw["ball_progress"] = r_ball_progress(obs["ball_goal_dist"], obs["prev_ball_goal_dist"])
    if "goal_scored" in terms:
        raw["goal_scored"] = r_goal(obs["scored"])
    raw["fall_penalty"] = r_fall(obs["fallen"])

    return {
        name: {"raw": value, "weighted": w[name] * value}
        for name, value in raw.items()
    }


def compute_reward(obs: dict, action: torch.Tensor, w: dict, task: str) -> torch.Tensor:
    terms = TASK_TERMS.get(task, TASK_TERMS["chase"])
    total = torch.zeros_like(obs["torso_up"])
    sigma = w.get("tracking_sigma", 0.25)

    if "upright" in terms:
        total += w["upright"] * r_upright(obs["torso_up"])
    if "alive" in terms:
        total += w["alive"] * r_alive(obs["fallen"])
    if "tracking_lin_vel_x" in terms:
        total += w.get("tracking_lin_vel_x", 1.0) * r_tracking_lin_vel_x(
            obs["commands"][:, 0], obs["base_lin_vel_x"], sigma)
    if "tracking_lin_vel_y" in terms:
        total += w.get("tracking_lin_vel_y", 1.0) * r_tracking_lin_vel_y(
            obs["commands"][:, 1], obs["base_lin_vel_y_y"], sigma)
    if "tracking_ang_vel" in terms:
        total += w.get("tracking_ang_vel", 0.5) * r_tracking_ang_vel(
            obs["commands"][:, 2], obs["base_ang_vel_z"], sigma)
    if "feet_swing" in terms:
        total += w.get("feet_swing", 3.0) * r_feet_swing(
            obs["gait_process"], obs["gait_frequency"], obs["feet_contact"],
            w.get("swing_period", 0.2))
    if "feet_slip" in terms:
        total += w.get("feet_slip", -0.1) * r_feet_slip(
            obs["feet_pos"], obs["last_feet_pos"], obs["feet_contact"],
            w.get("dt", 0.02), obs["episode_length_buf"])
    components = compute_reward_components(obs, w, task)
    for name in ("approach_ball", "ball_control", "ball_progress", "ball_contact"):
        if name in components:
            total += components[name]["weighted"]
    if "approach_angle" in terms:
        total += w.get("approach_angle", 2.0) * r_approach_angle(
            obs.get("ball_rel_body", torch.zeros_like(obs["torso_up"]).unsqueeze(1).expand(-1, 2)),
            obs.get("goal_dir_body", torch.zeros_like(obs["torso_up"]).unsqueeze(1).expand(-1, 2)))
    if "vel_to_ball" in terms and "base_lin_vel" in obs:
        total += w.get("vel_to_ball", 6.0) * r_vel_to_ball(
            obs["base_lin_vel"], obs.get("ball_dir_world",
            torch.zeros_like(obs["torso_up"]).unsqueeze(1).expand(-1, 2)))
    if "directed_contact" in terms:
        total += w.get("directed_contact", 5.0) * r_directed_contact(
            obs["min_foot_dist"], obs["ball_vel_to_goal"])
    if "ball_to_goal" in terms:
        total += w["ball_to_goal"] * r_ball_to_goal(obs["ball_vel_to_goal"])
    if "goal_scored" in components:
        total += components["goal_scored"]["weighted"]
    if "defensive_position" in terms and "self_xy" in obs:
        total += w["defensive_position"] * r_defensive_position(
            obs["self_xy"], obs["ball_xy"], obs["defend_goal_xy"], obs["in_possession"])
    if "support_position" in terms and "self_xy" in obs:
        total += w["support_position"] * r_support_position(
            obs["self_xy"], obs["ball_xy"], obs["attack_goal_xy"], obs["in_possession"])
    if "coop_goal" in terms and "self_xy" in obs:
        scored_my_team = obs.get("scored_my_team", torch.ones_like(obs["scored"]))
        total += w["coop_goal"] * r_coop_goal(obs["scored"], scored_my_team)
    if "lin_vel_z" in terms:
        total += w.get("lin_vel_z", -2.0) * r_lin_vel_z(obs.get("base_lin_vel_z", torch.zeros_like(obs["torso_up"])))
    if "ang_vel_xy" in terms:
        total += w.get("ang_vel_xy", -0.2) * r_ang_vel_xy(obs.get("base_ang_vel_xy", torch.zeros_like(obs["torso_up"]).unsqueeze(1).expand(-1, 2)))
    if "orientation" in terms:
        total += w.get("orientation", -5.0) * r_orientation(obs.get("projected_gravity_xy", torch.zeros_like(obs["torso_up"]).unsqueeze(1).expand(-1, 2)))

    total += components["fall_penalty"]["weighted"]
    total += w["recovery_bonus"] * r_recovery(obs["just_recovered"])
    total += w["energy_penalty"] * r_energy(action)

    if "action_rate" in terms and "last_actions" in obs:
        total += w.get("action_rate", -1.0) * r_action_rate(obs["last_actions"], action)
    if "command_penalty" in terms:
        total += w.get("command_penalty", -1.0) * r_command_penalty(action)
    if "dof_acc" in terms and "last_dof_vel" in obs:
        total += w.get("dof_acc", -1e-7) * r_dof_acc(obs["last_dof_vel"], obs.get("dof_vel", obs["last_dof_vel"]), w.get("dt", 0.02))

    return total
