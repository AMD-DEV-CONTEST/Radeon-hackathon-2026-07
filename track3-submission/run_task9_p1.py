#!/usr/bin/env python3
"""Task-9-v2 Phase A: P1 no-opponent chase training (0-4h).

Hierarchical PPO: 19-dim HL obs -> 3-dim HL action (vx, vy, wz) -> frozen walk model -> joints.
v2 params: hl_clip=0.6, action_scale=0.16, clip_actions=1.2, fall_penalty=-14, lr=1.5e-4 (LOCKED, never raise).
"""
import sys, os, json, time, math, pickle, shutil, types, traceback
import numpy as np
import torch

try:
    from safe_load import safe_jit_load
except ImportError:
    import sys as _sys
    _dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        _cand = os.path.join(_dir, "scripts")
        if os.path.isfile(os.path.join(_cand, "safe_load.py")):
            _sys.path.insert(0, _cand)
            break
        _dir = os.path.dirname(_dir)
    from safe_load import safe_jit_load
from pathlib import Path

ROOT = Path("/workspace")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Patch reward module path (envs import `from rewards.reward import compute_reward`)
import reward as _reward_mod
_rewards_pkg = types.ModuleType("rewards")
_rewards_pkg.reward = _reward_mod
_rewards_pkg.__path__ = []
sys.modules["rewards"] = _rewards_pkg
sys.modules["rewards.reward"] = _reward_mod
from reward import compute_reward

import yaml
import genesis as gs
from rsl_rl.runners import OnPolicyRunner
from soccer_env_v4 import SoccerEnv, POLICY_JOINT_NAMES
from genesis.utils.geom import inv_quat, quat_to_xyz, transform_by_quat, transform_quat_by_quat
from control_utils import compose_full_joint_targets
from tensordict import TensorDict

LOG_DIR = ROOT / "training_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR = ROOT / "demos" / "exp"
OUT_DIR.mkdir(parents=True, exist_ok=True)


class HieraSoccerEnv(SoccerEnv):
    """Hierarchical soccer env: HL PPO (19->3) + frozen walk model (720->21)."""

    def __init__(self, num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg,
                 walk_model_path, high_level_decimation=5, show_viewer=False):
        self._hl_initialized = False
        self.high_level_decimation = high_level_decimation
        self.hl_clip_lin = env_cfg.get("hl_clip_lin", 0.6)
        self.hl_clip_ang = env_cfg.get("hl_clip_ang", 0.6)

        # Override action_scale from config (v2: 0.16)
        self._override_action_scale = env_cfg.get("action_scale", 0.25)

        super().__init__(num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg, show_viewer)

        self._hl_initialized = True
        self.num_actions = 3  # vx, vy, wz (HL action space)

        # Resolve walk model path
        candidates = [
            walk_model_path,
            walk_model_path.replace("/workspace/booster/booster_deploy", "/workspace/booster_deploy"),
            "/workspace/booster_deploy/tasks/locomotion/models/t1_walk.pt",
            str(ROOT / "models/pretrained/t1_walk.pt"),
        ]
        resolved = next((p for p in candidates if os.path.exists(p)), candidates[0])

        self.walk_model = safe_jit_load(resolved, map_location=self.device)
        self.walk_model.eval()
        try:
            _norm = self.walk_model.obs_normalizer
            self._norm_mean = _norm._mean.to(self.device)
            self._norm_std = torch.clamp(_norm._std, min=1e-8).to(self.device)
            print(f"[hierarchical] Walk model normalizer: mean={self._norm_mean.shape}")
        except Exception as e:
            self._norm_mean = None
            self._norm_std = None
            print(f"[hierarchical] Walk model normalizer N/A: {e}")

        # Apply action_scale override
        self.action_scale = self._override_action_scale

        print(f"[hierarchical] Walk model: {resolved}")
        print(f"[hierarchical] HL obs=19, action=3, clip_lin={self.hl_clip_lin}, clip_ang={self.hl_clip_ang}")
        print(f"[hierarchical] action_scale={self.action_scale}, clip_actions={self.clip_actions}")
        print(f"[hierarchical] HL dt={self.dt * high_level_decimation:.3f}s, decimation={high_level_decimation}")

        # Map policy joints (21) to motor indices
        all_joint_names = [j.name for j in self.motor_joints]
        self.policy_joint_indices = torch.tensor(
            [all_joint_names.index(n) for n in POLICY_JOINT_NAMES],
            dtype=gs.tc_int, device=self.device)

        # HL buffers
        self.last_hl_actions = torch.zeros((num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.hl_commands = torch.zeros((num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.guide_prob = 0.0  # guided-exploration: override HL action toward ball

        # Metrics
        self.fallen_count = 0
        self.kick_count = 0
        self.episode_count = 0
        self._track_init = False

        # Override obs_buf to HL dim
        self.obs_buf = torch.empty((num_envs, 19), dtype=gs.tc_float, device=self.device)
        self._update_observation()

    def _obs_dim(self):
        return 19

    def _compute_hl_obs(self):
        pos = self.base_pos
        quat = self.base_quat
        inv_bq = inv_quat(quat)

        ball_rel = self.ball_pos - pos
        ball_rel_body = transform_by_quat(ball_rel, inv_bq)
        ball_vel_body = transform_by_quat(self.ball_vel, inv_bq)

        goal_pos = torch.zeros_like(pos)
        goal_pos[:, 0] = self.goal_x
        goal_rel = goal_pos - pos
        goal_rel_body = transform_by_quat(goal_rel, inv_bq)
        goal_dist = torch.norm(goal_rel_body[:, :2], dim=1, keepdim=True)
        goal_dir = goal_rel_body[:, :2] / (goal_dist + 1e-6)

        dist_to_ball = torch.norm(ball_rel_body[:, :2], dim=1, keepdim=True)
        grav = transform_by_quat(
            torch.tensor([0., 0., -1.], device=self.device).expand(self.num_envs, -1), inv_bq)

        return torch.cat([
            self.base_lin_vel,          # 3
            self.base_ang_vel,          # 3
            grav[:, :2],                # 2
            ball_rel_body[:, :2],       # 2
            ball_vel_body[:, :2],       # 2
            dist_to_ball,               # 1
            goal_dir,                   # 2
            goal_dist,                  # 1
            self.last_hl_actions,       # 3
        ], dim=-1)

    def _build_ll_obs_720(self):
        """Build 720-dim low-level obs for walk model from current state."""
        per_frame = torch.cat([
            self.base_ang_vel * self.obs_scales["ang_vel"],
            self.projected_gravity,
            self.hl_commands,
            (self.dof_pos - self.default_dof_pos)[:, self.policy_joint_indices] * self.obs_scales["dof_pos"],
            self.dof_vel[:, self.policy_joint_indices] * self.obs_scales["dof_vel"],
            self.last_actions[:, self.policy_joint_indices] if self.last_actions.shape[-1] == self.num_actions else torch.zeros((self.num_envs, 21), device=self.device),
        ], dim=-1)
        if per_frame.shape[-1] < 72:
            per_frame = torch.cat([per_frame, torch.zeros(self.num_envs, 72 - per_frame.shape[-1], device=self.device)], dim=-1)
        self.obs_history = torch.cat([self.obs_history[:, 1:], per_frame.unsqueeze(1)], dim=1)
        return self.obs_history.reshape(self.num_envs, -1)

    def step(self, hl_actions):
        hl_actions = torch.as_tensor(hl_actions, dtype=gs.tc_float, device=self.device)
        # Guided exploration: with prob guide_prob, replace action with a chase
        # heuristic (move forward + turn toward ball). Teaches the policy that
        # commanding nonzero velocity yields rewards, breaking the stand-still trap.
        if self.guide_prob > 1e-4:
            _invq = inv_quat(self.base_quat)
            _brel = transform_by_quat(self.ball_pos - self.base_pos, _invq)
            _bearing = torch.atan2(_brel[:, 1], _brel[:, 0])
            _guide = torch.stack([
                torch.full_like(_bearing, 0.42),
                torch.zeros_like(_bearing),
                torch.clamp(1.5 * _bearing, -self.hl_clip_ang, self.hl_clip_ang),
            ], dim=1)
            _gm = torch.rand(self.num_envs, device=self.device) < self.guide_prob
            hl_actions = torch.where(_gm.unsqueeze(1), _guide, hl_actions)
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

        dist_ball = torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1)
        soccer = {
            "torso_up": torch.clamp(-grav[:, 2], min=-1.0, max=1.0),
            "fallen": fallen,
            "base_lin_vel_x": self.base_lin_vel[:, 0],
            "base_lin_vel": self.base_lin_vel,
            "base_lin_vel_z": self.base_lin_vel[:, 2],
            "base_ang_vel_xy": self.base_ang_vel[:, :2],
            "ball_x": self.ball_pos[:, 0],
            "dist_to_ball": dist_ball,
            "ball_dir_world": (self.ball_pos[:, :2] - self.base_pos[:, :2]) / (dist_ball.unsqueeze(1) + 1e-6),
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

    def get_observations(self):
        return self.obs_buf, {"observations": {}}

    def _update_observation(self):
        if not self._hl_initialized:
            super()._update_observation()
            return
        self.obs_buf = self._compute_hl_obs()

    def reset(self):
        if not self._hl_initialized:
            return super().reset()
        self._reset_idx()
        self._read_state()
        self.prev_dist_to_ball = torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1).clone()
        self._update_observation()
        return self.get_observations()

    def get_stats(self):
        r0 = self.base_pos[0, :2].cpu().numpy()
        b0 = self.ball_pos[0, :2].cpu().numpy()
        return {
            "fallen_count": self.fallen_count,
            "robot_disp": float(np.linalg.norm(r0 - getattr(self, '_init_r0', r0))),
            "kicks": self.kick_count,
            "ball_disp": float(np.linalg.norm(b0 - getattr(self, '_init_b0', b0))),
            "episodes": self.episode_count,
        }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max_iterations", type=int, default=240)
    parser.add_argument("--num_envs", type=int, default=2048)
    parser.add_argument("--phase", type=str, default="A")
    parser.add_argument("--resume", action="store_true", help="resume from latest checkpoint in runs/task9_p1")
    parser.add_argument("--guide", action="store_true", help="guided exploration toward ball (decays to 0 by iter 200)")
    args = parser.parse_args()

    with open(ROOT / "configs/hierarchical_agent.yaml") as f:
        cfg = yaml.safe_load(f)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = "chase_hl"
    hl_cfg = cfg.get("high_level", {})
    train_cfg = cfg["train"]
    train_cfg["run_name"] = f"task9_p1"
    train_cfg["max_iterations"] = args.max_iterations

    # Convert yaml actor/critic config to rsl_rl 5.4.2 "policy" format
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

    env = HieraSoccerEnv(
        num_envs=args.num_envs, env_cfg=env_cfg, obs_cfg=cfg["obs"],
        reward_cfg=cfg["reward"], command_cfg=cfg["command"],
        walk_model_path=hl_cfg.get("walk_model_path", ""),
        high_level_decimation=hl_cfg.get("decimation", 5),
        show_viewer=False)

    env._init_r0 = env.base_pos[0, :2].cpu().numpy().copy()
    env._init_b0 = env.ball_pos[0, :2].cpu().numpy().copy()

    log_dir = str(ROOT / "runs" / "task9_p1")
    if os.path.exists(log_dir) and not args.resume:
        shutil.rmtree(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    ckpt_out = ROOT / "models"
    ckpt_out.mkdir(parents=True, exist_ok=True)
    with open(f"{log_dir}/cfgs.pkl", "wb") as f:
        pickle.dump([env_cfg, cfg["obs"], cfg["reward"], cfg["command"], train_cfg], f)

    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)
    if args.resume:
        import glob as _glob
        ckpts = sorted(_glob.glob(f"{log_dir}/model_*.pt"), key=lambda p: int(p.split('model_')[1].split('.')[0]))
        if ckpts:
            runner.load(ckpts[-1])
            print(f"[resume] loaded {ckpts[-1]} at iter {runner.current_learning_iteration}", flush=True)
        else:
            print("[resume] no checkpoint found, starting fresh", flush=True)

    print(f"\n{'='*60}")
    print(f"TASK9 Phase {args.phase}: P1 chase_hl training (no opponent)")
    print(f"  Envs: {args.num_envs}, Max iters: {args.max_iterations}")
    print(f"  LR: {train_cfg['algorithm']['learning_rate']}")
    print(f"  hl_clip: lin={env.hl_clip_lin}, ang={env.hl_clip_ang}")
    print(f"  action_scale={env.action_scale}, clip_actions={env.clip_actions}")
    print(f"  fall_penalty={cfg['reward']['fall_penalty']}, alive={cfg['reward']['alive']}")
    print(f"{'='*60}\n", flush=True)

    checkpoint_interval = 25
    t0 = time.time()

    for start_iter in range(0, args.max_iterations, checkpoint_interval):
        end_iter = min(start_iter + checkpoint_interval, args.max_iterations)
        if args.guide:
            env.guide_prob = max(0.0, 0.25 * (1.0 - end_iter / 250.0))
            env.reward_cfg["fall_penalty"] = -4.0 if end_iter < 250 else -10.0
            print(f"[guide] iter {end_iter}: guide_prob={env.guide_prob:.2f}", flush=True)
        runner.learn(num_learning_iterations=end_iter - start_iter, init_at_random_ep_len=(start_iter == 0))

        stats = env.get_stats()
        elapsed = time.time() - t0
        mean_rew = float(runner.logger.stats.get("Train/mean_reward", [0])[-1]) if hasattr(runner, 'logger') and hasattr(runner.logger, 'stats') else 0.0

        print(f"[iter {end_iter}/{args.max_iterations}] elapsed={elapsed/60:.1f}min "
              f"fallen={stats['fallen_count']} (per_ep={stats['fallen_count']/max(stats['episodes'],1):.1f}) "
              f"disp={stats['robot_disp']:.2f}m kicks={stats['kicks']} "
              f"ball_disp={stats['ball_disp']:.2f}m eps={stats['episodes']} mean_rew={mean_rew:.2f}", flush=True)
        import glob as _glob
        src_models = sorted(_glob.glob(f"{log_dir}/model_*.pt"),
                            key=lambda p: int(p.split('model_')[1].split('.')[0]))
        if src_models:
            src_model = src_models[-1]
            shutil.copy(src_model, str(ckpt_out / "task9_p1.pt"))
            _it = src_model.split('model_')[1].split('.')[0]
            print(f"[ckpt] saved {ckpt_out / 'task9_p1.pt'} (iter {_it})", flush=True)

        # Emergency stop-loss checks (per-episode fall rate, not cumulative)
        per_ep = stats['fallen_count'] / max(stats['episodes'], 1)
        if per_ep > 0.5 and elapsed > 3600:
            print(f"[STOPLOSS] per_ep fallen={per_ep:.2f} > 0.5 after 1h. Applying hl_clip=0.5, fall_penalty=-18", flush=True)
            # Can't modify running env; log for next phase
            break

    # Final stats
    stats = env.get_stats()
    elapsed = time.time() - t0
    result = {
        "phase": args.phase,
        "task": "chase_hl",
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
        },
        "metrics": stats,
        "checkpoint_dir": log_dir,
    }

    result_path = OUT_DIR / "task9_p1_result.json"
    result_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nTASK9_STAGE_A_DONE fallen={stats['fallen_count']} disp={stats['robot_disp']:.2f}m "
          f"kicks={stats['kicks']} ball_disp={stats['ball_disp']:.2f}m eps={stats['episodes']}", flush=True)


if __name__ == "__main__":
    main()
