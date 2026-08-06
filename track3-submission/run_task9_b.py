#!/usr/bin/env python3
"""Task-9-v2 Phase B: robust chase_hl training with torso push disturbances.

Same structure as run_task9_p1.py (Phase A). Phase-B differences:
  * Random horizontal pushes on the robot torso link, per-env independent
    timers: interval uniform 4-8 s, push duration uniform 0.3-0.5 s.
  * Push force follows a curriculum: 2.0 N at iter 0, +2.0 N every 25 iters,
    capped at 15.0 N. B-STOPLOSS halves the cap after 2 consecutive bad
    checkpoint windows (per_ep fallen > 1.0), without exiting.
  * Uses genesis rigid_solver.apply_links_external_force. The installed API
    has NO duration argument, so the script maintains its own "pushing" state
    and re-applies the force on every physics substep while active.
  * Optional (--ball_perturb): random small ball linear-velocity kicks to a
    small fraction of envs every 5 s (simulated collision deflection).

Rewards/HP fully inherit configs/hierarchical_agent.yaml (lr=1.5e-4 LOCKED).
"""
import sys, os, json, time, math, pickle, shutil, glob
import numpy as np
import torch
from pathlib import Path

ROOT = Path("/workspace")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import yaml
import genesis as gs
from rsl_rl.runners import OnPolicyRunner
# Reuse the Phase-A hierarchical env as the base (imports reward/control_utils
# and patches the `rewards` package path exactly like run_task9_p1.py).
from run_task9_p1 import HieraSoccerEnv
from genesis.utils.geom import inv_quat, transform_by_quat
from control_utils import compose_full_joint_targets
from reward import compute_reward

OUT_DIR = ROOT / "demos" / "exp"
OUT_DIR.mkdir(parents=True, exist_ok=True)


class RobustSoccerEnv(HieraSoccerEnv):
    """HieraSoccerEnv + Phase-B disturbance injection.

    Push injection: per-env countdown timers in high-level step units
    (hl_dt = dt * high_level_decimation = 0.1 s). When a push triggers, the
    torso link receives a horizontal (world-frame x-y) force of magnitude
    `push_cap` in a random direction for 0.3-0.5 s, applied every physics
    substep of the active window.
    """

    # Curriculum / perturbation defaults (all in seconds / Newtons)
    PUSH_INTERVAL_S = (4.0, 8.0)
    PUSH_DURATION_S = (0.3, 0.5)
    PUSH_CAP_START = 2.0
    PUSH_CAP_STEP = 2.0            # +2 N every 25 training iterations
    PUSH_CAP_MAX = 15.0
    PUSH_CAP_FLOOR = 1.0           # stop-loss halves never go below this
    BALL_PERTURB_INTERVAL_S = 5.0
    BALL_PERTURB_FRAC = 0.05
    BALL_PERTURB_SPEED = 0.3

    def __init__(self, num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg,
                 walk_model_path, high_level_decimation=5, show_viewer=False,
                 ball_perturb=False):
        self._push_init = False
        self.ball_perturb_enabled = bool(ball_perturb)
        super().__init__(num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg,
                         walk_model_path, high_level_decimation=high_level_decimation,
                         show_viewer=show_viewer)

        self.hl_dt = self.dt * self.high_level_decimation
        self._push_lo = max(1, int(self.PUSH_INTERVAL_S[0] / self.hl_dt))
        self._push_hi = max(self._push_lo + 1, int(self.PUSH_INTERVAL_S[1] / self.hl_dt))
        self._dur_lo = max(1, int(self.PUSH_DURATION_S[0] / self.hl_dt))
        self._dur_hi = max(self._dur_lo + 1, int(self.PUSH_DURATION_S[1] / self.hl_dt))

        # Torso link: URDF has floating world_joint -> "Trunk" (env reads
        # links[1] as the trunk). Resolve by name with links[1] fallback.
        link_names = [l.name for l in self.robot.links]
        self._torso_link_idx = link_names.index("Trunk") if "Trunk" in link_names else 1

        # Push state (HL-step units)
        self.push_cap = self.PUSH_CAP_START
        self.push_remaining = torch.zeros((self.num_envs,), dtype=gs.tc_int, device=self.device)
        self.push_interval_steps = torch.zeros((self.num_envs,), dtype=gs.tc_int, device=self.device)
        self.push_force_xy = torch.zeros((self.num_envs, 2), dtype=gs.tc_float, device=self.device)

        # Optional ball velocity perturbation state
        self._ball_timer = 0
        self._ball_interval = max(1, int(self.BALL_PERTURB_INTERVAL_S / self.hl_dt))

        self._push_init = True
        self._resample_push_intervals(None)
        print(f"[robust] torso link idx={self._torso_link_idx} ({link_names[self._torso_link_idx]})", flush=True)
        print(f"[robust] push cap={self.push_cap:.1f}N (-> +{self.PUSH_CAP_STEP:.1f}N/25iter, max {self.PUSH_CAP_MAX:.1f}N) "
              f"interval={self.PUSH_INTERVAL_S[0]}-{self.PUSH_INTERVAL_S[1]}s "
              f"duration={self.PUSH_DURATION_S[0]}-{self.PUSH_DURATION_S[1]}s "
              f"ball_perturb={self.ball_perturb_enabled}", flush=True)

    # ------------------------------------------------------------------ #
    # Push machinery
    # ------------------------------------------------------------------ #
    def set_push_cap(self, cap):
        """Set the curriculum force cap and rescale any active pushes."""
        cap = max(float(cap), self.PUSH_CAP_FLOOR)
        self.push_cap = cap
        active = self.push_remaining > 0
        if active.any():
            mag = torch.norm(self.push_force_xy, dim=1)
            scale = torch.where(mag > 1e-9, cap / mag.clamp(min=1e-9), torch.zeros_like(mag))
            self.push_force_xy[active] *= scale[active].unsqueeze(1)

    def _resample_push_intervals(self, idx):
        if idx is None:
            n = self.num_envs
            self.push_interval_steps[:] = torch.randint(
                self._push_lo, self._push_hi + 1, (n,), device=self.device, dtype=torch.int32)
        else:
            self.push_interval_steps[idx] = torch.randint(
                self._push_lo, self._push_hi + 1, (len(idx),), device=self.device, dtype=torch.int32)

    def _update_push_timers(self):
        """One call per env.step (HL step): decrement counters, trigger pushes."""
        if not self._push_init:
            return
        self.push_remaining = torch.clamp(self.push_remaining - 1, min=0)
        self.push_interval_steps -= 1
        trigger = self.push_interval_steps <= 0
        if trigger.any():
            idx = trigger.nonzero(as_tuple=False).flatten()
            n = len(idx)
            ang = torch.rand(n, device=self.device) * (2.0 * math.pi)
            self.push_force_xy[idx, 0] = torch.cos(ang) * self.push_cap
            self.push_force_xy[idx, 1] = torch.sin(ang) * self.push_cap
            self.push_remaining[idx] = torch.randint(
                self._dur_lo, self._dur_hi + 1, (n,), device=self.device, dtype=torch.int32)
            self._resample_push_intervals(idx)
        if self.ball_perturb_enabled:
            self._maybe_perturb_ball()

    def _apply_push_force(self):
        """Apply the active horizontal push forces before one physics substep."""
        if not self._push_init:
            return
        active = self.push_remaining > 0
        if not active.any():
            return
        idx = active.nonzero(as_tuple=False).flatten()
        n = len(idx)
        force = torch.zeros((n, 3), dtype=gs.tc_float, device=self.device)
        force[:, 0] = self.push_force_xy[idx, 0]
        force[:, 1] = self.push_force_xy[idx, 1]
        self.scene.rigid_solver.apply_links_external_force(
            force.unsqueeze(1), links_idx=[self._torso_link_idx], envs_idx=idx)

    def _maybe_perturb_ball(self):
        """Optional: every N s, kick a small fraction of balls with a small
        random horizontal velocity (simulated collision deflection)."""
        self._ball_timer += 1
        if self._ball_timer < self._ball_interval:
            return
        self._ball_timer = 0
        k = max(1, int(self.num_envs * self.BALL_PERTURB_FRAC))
        idx = torch.randperm(self.num_envs, device=self.device)[:k]
        ang = torch.rand(k, device=self.device) * (2.0 * math.pi)
        vel = torch.zeros((k, 3), dtype=gs.tc_float, device=self.device)
        vel[:, 0] = torch.cos(ang) * self.BALL_PERTURB_SPEED
        vel[:, 1] = torch.sin(ang) * self.BALL_PERTURB_SPEED
        self.ball.set_dofs_velocity(vel, dofs_idx_local=[0, 1, 2], envs_idx=idx)

    def _reset_idx(self, envs_idx=None):
        super()._reset_idx(envs_idx)
        if not self._push_init:
            return
        if envs_idx is None:
            self.push_remaining.zero_()
            self.push_force_xy.zero_()
            self._resample_push_intervals(None)
        else:
            idx = envs_idx.nonzero(as_tuple=False).flatten()
            if idx.numel():
                self.push_remaining[idx] = 0
                self.push_force_xy[idx] = 0.0
                self._resample_push_intervals(idx)

    # ------------------------------------------------------------------ #
    # step(): identical to run_task9_p1.HieraSoccerEnv.step + 2 hooks:
    #   *_update_push_timers() before stepping,
    #   *_apply_push_force() before every physics substep.
    # ------------------------------------------------------------------ #
    def step(self, hl_actions):
        self._update_push_timers()
        hl_actions = torch.as_tensor(hl_actions, dtype=gs.tc_float, device=self.device)
        vx = torch.clamp(hl_actions[:, 0], -self.hl_clip_lin, self.hl_clip_lin)
        vy = torch.clamp(hl_actions[:, 1], -self.hl_clip_lin, self.hl_clip_lin)
        wz = torch.clamp(hl_actions[:, 2], -self.hl_clip_ang, self.hl_clip_ang)
        cmds = torch.stack([vx, vy, wz], dim=1)
        cmds = torch.where(torch.abs(cmds) < 0.05, torch.zeros_like(cmds), cmds)
        self.hl_commands = cmds

        joint_actions = None
        for _ in range(self.high_level_decimation):
            ll_obs = self._build_ll_obs_720()
            with torch.no_grad():
                obs_n = (ll_obs - self._norm_mean) / self._norm_std if self._norm_mean is not None else ll_obs
                joint_actions = self.walk_model.actor(obs_n)
            joint_actions = torch.clip(joint_actions, -self.clip_actions, self.clip_actions)
            target = compose_full_joint_targets(
                joint_actions, self.action_scale, self.default_dof_pos, self.policy_joint_indices)
            self.robot.control_dofs_position(
                target[:, self.actions_dof_idx] if hasattr(self, 'actions_dof_idx') else target,
                slice(self.base_dof_start, self.base_dof_start + len(self.motor_joints)))
            for _ in range(self.substeps if hasattr(self, 'substeps') else 10):
                self._apply_push_force()
                self.scene.step()
            self.episode_length_buf += 1
            self._read_state()

        # Build soccer state for reward
        inv_bq = inv_quat(self.base_quat)
        ball_rel = self.ball_pos - self.base_pos
        ball_rel_body = transform_by_quat(ball_rel, inv_bq)
        goal_pos = torch.zeros_like(self.base_pos)
        goal_pos[:, 0] = self.goal_x
        goal_rel = goal_pos - self.base_pos
        goal_rel_body = transform_by_quat(goal_rel, inv_bq)
        goal_dist_t = torch.norm(goal_rel_body[:, :2], dim=1)
        ball_goal_dist = torch.norm(self.ball_pos[:, :2] - goal_pos[:, :2], dim=1)
        prev_ball_goal_dist = torch.norm(
            (self.ball_pos[:, :2] - goal_pos[:, :2]).clone(), dim=1)
        grav = transform_by_quat(
            torch.tensor([0., 0., -1.], device=self.device).expand(self.num_envs, -1), inv_bq)

        scored = (self.ball_pos[:, 0] > self.goal_x) & (torch.abs(self.ball_pos[:, 1]) < self.goal_half)
        fallen = (self.base_pos[:, 2] < self.fall_height) | (torch.abs(self.base_euler[:, 1]) > 45) | (torch.abs(self.base_euler[:, 0]) > 45)

        soccer = {
            "torso_up": torch.clamp(-grav[:, 2], min=-1.0, max=1.0),
            "fallen": fallen,
            "base_lin_vel_x": self.base_lin_vel[:, 0],
            "base_lin_vel_z": self.base_lin_vel[:, 2],
            "base_ang_vel_xy": self.base_ang_vel[:, :2],
            "ball_x": self.ball_pos[:, 0],
            "dist_to_ball": torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1),
            "prev_dist_to_ball": self.prev_dist_to_ball,
            "ball_vel_to_goal": torch.sum(self.ball_vel[:, :2] * goal_rel_body[:, :2] / (goal_dist_t.unsqueeze(1) + 1e-6), dim=1),
            "scored": scored,
            "just_recovered": self.fallen_prev & (~fallen),
            "ball_rel_body": ball_rel_body[:, :2],
            "goal_dir_body": goal_rel_body[:, :2] / (goal_dist_t.unsqueeze(1) + 1e-6),
            "min_foot_dist": torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1),  # approx
            "ball_goal_dist": ball_goal_dist,
            "prev_ball_goal_dist": prev_ball_goal_dist,
            "projected_gravity_xy": grav[:, :2],
            "last_actions": self.last_hl_actions,
        }

        w = dict(self.reward_cfg)
        w["_ball_radius"] = self.ball_radius
        self.rew_buf = compute_reward(soccer, cmds, w, self.task)

        # Metrics
        self.fallen_count += int(fallen.sum().item())
        kick_mask = soccer["dist_to_ball"] < 0.5
        self.kick_count += int(kick_mask.sum().item())

        # Termination
        self.reset_buf = self.episode_length_buf > self.max_episode_length
        self.reset_buf |= fallen
        self.reset_buf |= scored
        self.reset_buf |= self.scene.rigid_solver.get_error_envs_mask()
        self.extras["time_outs"] = (self.episode_length_buf > self.max_episode_length).to(dtype=gs.tc_float)
        self.extras["fallen"] = fallen
        self.extras["scored"] = scored

        if self.reset_buf.any():
            self.episode_count += int(self.reset_buf.sum().item())
            self._reset_idx(self.reset_buf)

        self.extras["observations"] = {}
        self.prev_dist_to_ball = soccer["dist_to_ball"].clone()
        self.last_hl_actions = cmds.clone()
        self._update_observation()
        return self.obs_buf, self.rew_buf, self.reset_buf, self.extras


def curriculum_push_cap(iteration):
    """Push force cap at a given training iteration (2.0N -> +2N/25 -> 15N)."""
    return min(RobustSoccerEnv.PUSH_CAP_START + RobustSoccerEnv.PUSH_CAP_STEP * (iteration // 25),
               RobustSoccerEnv.PUSH_CAP_MAX)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max_iterations", type=int, default=480)
    parser.add_argument("--num_envs", type=int, default=2048)
    parser.add_argument("--phase", type=str, default="B")
    parser.add_argument("--resume", action="store_true", help="resume from latest checkpoint in runs/task9_b")
    parser.add_argument("--ckpt", type=str, default=None,
                        help="Phase-B start weights (e.g. /workspace/models/task9_p1.pt); copied to runs/task9_b/model_0.pt")
    parser.add_argument("--ball_perturb", action="store_true",
                        help="optional: random small ball velocity perturbation every 5 s")
    args = parser.parse_args()

    with open(ROOT / "configs/hierarchical_agent.yaml") as f:
        cfg = yaml.safe_load(f)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = "chase_hl_robust"
    hl_cfg = cfg.get("high_level", {})
    train_cfg = cfg["train"]
    train_cfg["run_name"] = "task9_b"
    train_cfg["max_iterations"] = args.max_iterations

    # Convert yaml actor/critic config to rsl_rl 5.4.2 "policy" format (same as P1)
    actor_cfg = cfg["train"].get("actor", {})
    critic_cfg = cfg["train"].get("critic", {})
    dist_cfg = actor_cfg.get("distribution_cfg", {})
    train_cfg["policy"] = {
        "class_name": "ActorCritic",
        "actor_class_name": actor_cfg.get("class_name", "MLPModel"),
        "actor_hidden_dims": actor_cfg.get("hidden_dims", [256, 128, 64]),
        "actor_activation": actor_cfg.get("activation", "elu"),
        "critic_class_name": critic_cfg.get("class_name", "MLPModel"),
        "critic_hidden_dims": critic_cfg.get("hidden_dims", [256, 128, 64]),
        "critic_activation": critic_cfg.get("activation", "elu"),
        "init_noise_std": dist_cfg.get("init_std", 1.0),
        "std_type": dist_cfg.get("std_type", "scalar"),
    }
    train_cfg["empirical_normalization"] = False

    gs.init(backend=gs.gpu, precision="32", logging_level="warning", seed=42)

    env = RobustSoccerEnv(
        num_envs=args.num_envs, env_cfg=env_cfg, obs_cfg=cfg["obs"],
        reward_cfg=cfg["reward"], command_cfg=cfg["command"],
        walk_model_path=hl_cfg.get("walk_model_path", ""),
        high_level_decimation=hl_cfg.get("decimation", 5),
        show_viewer=False, ball_perturb=args.ball_perturb)

    env._init_r0 = env.base_pos[0, :2].cpu().numpy().copy()
    env._init_b0 = env.ball_pos[0, :2].cpu().numpy().copy()

    log_dir = str(ROOT / "runs" / "task9_b")
    if os.path.exists(log_dir) and not (args.resume or args.ckpt):
        shutil.rmtree(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    ckpt_out = ROOT / "models"
    ckpt_out.mkdir(parents=True, exist_ok=True)
    with open(f"{log_dir}/cfgs.pkl", "wb") as f:
        pickle.dump([env_cfg, cfg["obs"], cfg["reward"], cfg["command"], train_cfg], f)

    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)
    if args.ckpt and os.path.exists(args.ckpt):
        seed_ckpt = os.path.join(log_dir, "model_0.pt")
        if not os.path.exists(seed_ckpt):
            shutil.copy(args.ckpt, seed_ckpt)
        runner.load(seed_ckpt)
        print(f"[ckpt] seeded Phase-B weights from {args.ckpt} at iter {runner.current_learning_iteration}", flush=True)
    elif args.ckpt:
        print(f"[ckpt] WARNING: --ckpt {args.ckpt} not found, starting fresh", flush=True)
        if args.resume:
            _ckpts = sorted(glob.glob(f"{log_dir}/model_*.pt"),
                            key=lambda p: int(p.split('model_')[1].split('.')[0]))
            if _ckpts:
                runner.load(_ckpts[-1])
                print(f"[resume] loaded {_ckpts[-1]} at iter {runner.current_learning_iteration}", flush=True)
    elif args.resume:
        _ckpts = sorted(glob.glob(f"{log_dir}/model_*.pt"),
                        key=lambda p: int(p.split('model_')[1].split('.')[0]))
        if _ckpts:
            runner.load(_ckpts[-1])
            print(f"[resume] loaded {_ckpts[-1]} at iter {runner.current_learning_iteration}", flush=True)
        else:
            print("[resume] no checkpoint found, starting fresh", flush=True)

    print(f"\n{'='*60}")
    print(f"TASK9 Phase {args.phase}: chase_hl_robust training (torso push disturbances)")
    print(f"  Envs: {args.num_envs}, Max iters: {args.max_iterations}")
    print(f"  LR: {train_cfg['algorithm']['learning_rate']}")
    print(f"  hl_clip: lin={env.hl_clip_lin}, ang={env.hl_clip_ang}")
    print(f"  action_scale={env.action_scale}, clip_actions={env.clip_actions}")
    print(f"  fall_penalty={cfg['reward']['fall_penalty']}, alive={cfg['reward']['alive']}")
    print(f"  push cap: {RobustSoccerEnv.PUSH_CAP_START:.1f}N -> +{RobustSoccerEnv.PUSH_CAP_STEP:.1f}N/25iter "
          f"-> max {RobustSoccerEnv.PUSH_CAP_MAX:.1f}N")
    print(f"{'='*60}\n", flush=True)

    checkpoint_interval = 25
    t0 = time.time()
    bad_windows = 0

    for start_iter in range(0, args.max_iterations, checkpoint_interval):
        end_iter = min(start_iter + checkpoint_interval, args.max_iterations)
        env.set_push_cap(curriculum_push_cap(start_iter))
        runner.learn(num_learning_iterations=end_iter - start_iter, init_at_random_ep_len=(start_iter == 0))

        stats = env.get_stats()
        elapsed = time.time() - t0
        per_ep = stats['fallen_count'] / max(stats['episodes'], 1)
        mean_rew = float(runner.logger.stats.get("Train/mean_reward", [0])[-1]) if hasattr(runner, 'logger') and hasattr(runner.logger, 'stats') else 0.0

        print(f"[iter {end_iter}/{args.max_iterations}] elapsed={elapsed/60:.1f}min "
              f"fallen={stats['fallen_count']} (per_ep={per_ep:.1f}) "
              f"disp={stats['robot_disp']:.2f}m kicks={stats['kicks']} "
              f"ball_disp={stats['ball_disp']:.2f}m eps={stats['episodes']} mean_rew={mean_rew:.2f}", flush=True)

        # Checkpoint every 25 iters -> runs/task9_b/model_N.pt + models/task9_b.pt
        src_models = sorted(glob.glob(f"{log_dir}/model_*.pt"),
                            key=lambda p: int(p.split('model_')[1].split('.')[0]))
        if src_models:
            src_model = src_models[-1]
            shutil.copy(src_model, str(ckpt_out / "task9_b.pt"))
            _it = src_model.split('model_')[1].split('.')[0]
            print(f"[ckpt] saved {ckpt_out / 'task9_b.pt'} (iter {_it}, push cap {env.push_cap:.1f}N)", flush=True)

        # Phase-B stop-loss: 2 consecutive windows with per_ep fallen > 1.0
        # -> halve the current push force cap (does not exit).
        bad_windows = bad_windows + 1 if per_ep > 1.0 else 0
        if bad_windows >= 2:
            env.set_push_cap(env.push_cap / 2.0)
            print(f"[B-STOPLOSS] push cap {env.push_cap:.1f}N", flush=True)
            bad_windows = 0

    # Final stats
    stats = env.get_stats()
    elapsed = time.time() - t0
    result = {
        "phase": args.phase,
        "task": "chase_hl_robust",
        "started_at": t0,
        "ended_at": time.time(),
        "duration_s": round(elapsed, 1),
        "iterations": args.max_iterations,
        "num_envs": args.num_envs,
        "config_snapshot": {
            "hl_clip_lin": env.hl_clip_lin,
            "hl_clip_ang": env.hl_clip_ang,
            "action_scale": env.action_scale,
            "clip_actions": env.clip_actions,
            "fall_penalty": cfg["reward"]["fall_penalty"],
            "alive": cfg["reward"]["alive"],
            "upright": cfg["reward"]["upright"],
            "action_rate": cfg["reward"]["action_rate"],
            "energy_penalty": cfg["reward"]["energy_penalty"],
            "approach_ball": cfg["reward"]["approach_ball"],
            "ball_progress": cfg["reward"]["ball_progress"],
            "ball_to_goal": cfg["reward"]["ball_to_goal"],
            "goal_scored": cfg["reward"]["goal_scored"],
            "learning_rate": train_cfg["algorithm"]["learning_rate"],
            "episode_length_s": env_cfg["episode_length_s"],
            "push_cap_start": RobustSoccerEnv.PUSH_CAP_START,
            "push_cap_step_per_25_iter": RobustSoccerEnv.PUSH_CAP_STEP,
            "push_cap_max": RobustSoccerEnv.PUSH_CAP_MAX,
            "push_interval_s": list(RobustSoccerEnv.PUSH_INTERVAL_S),
            "push_duration_s": list(RobustSoccerEnv.PUSH_DURATION_S),
            "final_push_cap": env.push_cap,
            "ball_perturb": args.ball_perturb,
        },
        "metrics": stats,
        "checkpoint_dir": log_dir,
    }

    result_path = OUT_DIR / "task9_b_result.json"
    result_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nTASK9_STAGE_B_DONE fallen={stats['fallen_count']} disp={stats['robot_disp']:.2f}m "
          f"kicks={stats['kicks']} ball_disp={stats['ball_disp']:.2f}m eps={stats['episodes']}", flush=True)


if __name__ == "__main__":
    main()
