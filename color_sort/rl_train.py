"""PPO RL training for color-sorting with Genesis multi-env parallel simulation.

Uses n_envs=128+ for massive parallel RL. Pure PyTorch PPO (no external RL lib).
The policy is a simple MLP: state (9D joint pos) → action (9D joint target).
Reward = grasp + lift + place bonuses, shaped by distance to target.

Usage:
    python rl_train.py --n-envs 128 --steps 5000 --save-freq 1000
    python rl_train.py --n-envs 256 --steps 5000
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from build_scene import build_scene
from scene_config import (
    FRANKA_QPOS, FRANKA_KP, FRANKA_KV, FRANKA_FORCE_MIN, FRANKA_FORCE_MAX,
    COLORS, PICKABLE_GEOMETRIES, OBJECT_LAYOUT, OBJECT_SIZE,
    TABLE_TOP_Z, REACH_X, REACH_Y,
    object_rest_z_offset,
)
from genesis.utils.geom import euler_to_quat, trans_R_to_T, euler_to_R

# Motion constants
PREGRASP_CLEARANCE = 0.18
LIFT_HAND_Z = TABLE_TOP_Z + 0.30
PLACE_HAND_Z_ABOVE_TARGET = 0.16
HAND_TO_FINGERTIP = 0.105
GRIPPER_OPEN = 0.04
MOVE_MAX_DQ = 0.006
MOTORS_DOF = np.arange(7)
FINGERS_DOF = np.arange(7, 9)
CLOSE_FORCE = -12.0
TRAIN_COLORS = ("red", "blue", "green")
CONTROL_FPS = 100


class PPOPolicy(nn.Module):
    """Simple MLP policy: 9D state → 9D action mean + std + value."""

    def __init__(self, state_dim=9, action_dim=9, hidden=256, init_std=0.5):
        super().__init__()
        self.actor = nn.Sequential(
            nn.Linear(state_dim, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.Tanh(),
            nn.Linear(hidden, action_dim),
        )
        self.critic = nn.Sequential(
            nn.Linear(state_dim, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.Tanh(),
            nn.Linear(hidden, 1),
        )
        self.log_std = nn.Parameter(torch.ones(action_dim) * np.log(init_std))

    def forward(self, state):
        mean = self.actor(state)
        value = self.critic(state).squeeze(-1)
        std = self.log_std.exp()
        return mean, std, value

    def get_action(self, state):
        mean, std, value = self.forward(state)
        dist = torch.distributions.Normal(mean, std)
        action = dist.sample()
        log_prob = dist.log_prob(action).sum(-1)
        return action, log_prob, value

    def evaluate(self, state, action):
        mean, std, value = self.forward(state)
        dist = torch.distributions.Normal(mean, std)
        log_prob = dist.log_prob(action).sum(-1)
        entropy = dist.entropy().sum(-1)
        return log_prob, entropy, value


class ParallelSortEnv:
    """Batched color-sorting RL environment with n_envs parallel envs.

    Action: 9D joint position delta (delta from current qpos, clamped).
    Reward: shaped distance to grasp + lift + place.
    Episode: fixed length (400 steps), reset with randomized objects.
    """

    def __init__(self, bundle, n_envs, colors=TRAIN_COLORS, max_steps=400, seed=0):
        self.bundle = bundle
        self.n = n_envs
        self.colors = colors
        self.max_steps = max_steps
        self.device = torch.device("cuda")
        self.step_count = torch.zeros(n_envs, dtype=torch.long, device=self.device)
        self.done = torch.zeros(n_envs, dtype=torch.bool, device=self.device)
        self.rng = np.random.default_rng(seed)

        # Pick pool
        self.pick_pool = [f"{c}_{g}" for c in colors for g in PICKABLE_GEOMETRIES]
        # Per-env assignments
        self.pick_objects = [self.rng.choice(self.pick_pool) for _ in range(n_envs)]
        self.place_colors = [p.rsplit("_", 1)[0] for p in self.pick_objects]

        # Object home positions
        self.home = {}
        for name in bundle.objects:
            color, geom = name.rsplit("_", 1)
            x, y = OBJECT_LAYOUT[color][geom]
            self.home[name] = np.array([x, y])

        # Precompute target positions per env
        self._update_targets()

        # Episode rewards tracking
        self.episode_rewards = torch.zeros(n_envs, device=self.device)
        self.success_count = torch.zeros(n_envs, dtype=torch.long, device=self.device)

    def _update_targets(self):
        """Get current object + container positions for all envs."""
        n = self.n
        # Object positions
        self.obj_pos = {}
        for obj_name in self.bundle.objects:
            pos = self.bundle.objects[obj_name].get_pos().cpu().numpy()  # [n, 3]
            self.obj_pos[obj_name] = torch.tensor(pos, device=self.device, dtype=torch.float32)

        # Container positions (same across envs for fixed containers)
        self.cont_pos = {}
        for color in self.colors:
            pos = self.bundle.containers[color].get_pos().cpu().numpy()  # [n, 3]
            self.cont_pos[color] = torch.tensor(pos, device=self.device, dtype=torch.float32)

    def _get_pick_positions(self):
        """Get [n, 3] positions of each env's pick object."""
        pos = torch.zeros(self.n, 3, device=self.device)
        for i in range(self.n):
            obj = self.pick_objects[i]
            pos[i] = self.obj_pos[obj][i]
        return pos

    def _get_place_positions(self):
        """Get [n, 3] positions of each env's place target."""
        pos = torch.zeros(self.n, 3, device=self.device)
        for i in range(self.n):
            color = self.place_colors[i]
            pos[i] = self.cont_pos[color][i]
        return pos

    def get_state(self):
        """Return [n, 9] current joint positions."""
        qpos = self.bundle.franka.get_qpos()  # [n, 9] tensor
        return qpos.float()

    def reset(self, seeds=None):
        """Reset all envs with randomized object positions."""
        n = self.n
        # Reset robot
        qpos = torch.tensor(np.tile(np.array(FRANKA_QPOS), (n, 1)), device=self.device)
        self.bundle.franka.set_qpos(qpos.cpu().numpy(), zero_velocity=True)

        # Randomize objects per env
        for obj_name in self.bundle.objects:
            positions = np.zeros((n, 3))
            quats = np.zeros((n, 4))
            for i in range(n):
                ep_seed = seeds[i] if seeds is not None else self.rng.integers(0, 2**31)
                ep_rng = np.random.default_rng(ep_seed)
                color, geom = obj_name.rsplit("_", 1)
                x, y = OBJECT_LAYOUT[color][geom]
                dx, dy = ep_rng.uniform(-0.04, 0.04, size=2)
                x = float(np.clip(x + dx, *REACH_X))
                y = float(np.clip(y + dy, *REACH_Y))
                z = TABLE_TOP_Z + object_rest_z_offset(geom) + 0.002
                dyaw = float(ep_rng.uniform(-30.0, 30.0))
                quat = euler_to_quat(np.array([0.0, 0.0, dyaw]))
                positions[i] = [x, y, z]
                quats[i] = quat
            entity = self.bundle.objects[obj_name]
            entity.set_pos(positions, zero_velocity=True, skip_forward=True)
            entity.set_quat(quats, zero_velocity=True, skip_forward=False)

        # Reassign pick objects per env
        if seeds is not None:
            for i in range(n):
                self.pick_objects[i] = str(self.rng.choice(self.pick_pool))
                self.place_colors[i] = self.pick_objects[i].rsplit("_", 1)[0]

        # Settle
        hold = np.tile(np.array(FRANKA_QPOS), (n, 1))
        for _ in range(80):
            self.bundle.franka.control_dofs_position(hold)
            self.bundle.scene.step()
            self.bundle.update_wrist_cam()

        self._update_targets()
        self.step_count[:] = 0
        self.done[:] = False
        self.episode_rewards[:] = 0
        self.success_count[:] = 0

        return self.get_state()

    def step(self, actions):
        """Apply [n, 9] joint position actions, return (state, reward, done).

        Action is clamped delta from current position: action = current + clamp(delta)
        """
        n = self.n
        # Clamp actions to reasonable range
        current_qpos = self.bundle.franka.get_qpos().cpu().numpy()  # [n, 9]
        # Actions are absolute joint targets, clamped to joint limits
        actions_np = actions.cpu().numpy()
        # Clamp arm joints to Franka limits (approximate)
        arm_limits = np.array([
            [-2.9, 2.9], [-1.76, 1.76], [-2.9, 2.9], [-3.07, -0.07],
            [-2.9, 2.9], [-0.02, 3.75], [-2.9, 2.9],
        ])
        for j in range(7):
            actions_np[:, j] = np.clip(actions_np[:, j], arm_limits[j, 0], arm_limits[j, 1])
        # Clamp gripper
        actions_np[:, 7:9] = np.clip(actions_np[:, 7:9], 0.0, 0.04)

        self.bundle.franka.control_dofs_position(actions_np)
        self.bundle.scene.step()
        self.bundle.update_wrist_cam()

        self.step_count += 1
        self._update_targets()

        # Compute rewards
        rewards = self._compute_reward(actions_np)

        # Check done
        timeout = self.step_count >= self.max_steps
        self.done = timeout

        return self.get_state(), rewards, self.done

    def _compute_reward(self, actions_np):
        """Shaped reward: distance to object + grasp + lift + place."""
        n = self.n
        device = self.device

        # Hand position (link 8 = hand)
        hand_pos = self.bundle.franka.get_link("hand").get_pos().cpu().numpy()  # [n, 3]
        hand_pos_t = torch.tensor(hand_pos, device=device, dtype=torch.float32)

        # Pick object positions
        pick_pos = self._get_pick_positions()  # [n, 3]
        place_pos = self._get_place_positions()  # [n, 3]

        # Distance from hand to pick object (horizontal)
        dist_to_obj = torch.norm(hand_pos_t[:, :2] - pick_pos[:, :2], dim=1)

        # Object height (is it lifted?)
        obj_height = pick_pos[:, 2]
        table_z = TABLE_TOP_Z
        lift_height = torch.clamp(obj_height - table_z, min=0, max=0.3)

        # Distance from object to place target
        dist_to_place = torch.norm(pick_pos[:, :2] - place_pos[:, :2], dim=1)

        # Gripper state (fingers open or closed)
        finger_pos = self.bundle.franka.get_qpos().cpu().numpy()[:, 7:9]  # [n, 2]
        finger_width = np.mean(finger_pos, axis=1)  # [n]
        gripper_closed = torch.tensor(finger_width < 0.02, device=device, dtype=torch.float32)

        # Reward components
        reward = torch.zeros(n, device=device)

        # 1. Approach reward: closer to object = better
        reward -= 2.0 * dist_to_obj  # negative distance (max ~2m → -4)

        # 2. Grasp reward: close to object + gripper closed
        near_obj = (dist_to_obj < 0.05).float()
        reward += 5.0 * near_obj * gripper_closed  # +5 for grasping

        # 3. Lift reward: object lifted above table
        reward += 10.0 * lift_height  # +10 per meter lifted (max +3)

        # 4. Transport reward: object closer to place target
        if_lifted = (lift_height > 0.05).float()
        reward -= 1.0 * dist_to_place * if_lifted  # closer to target when lifted

        # 5. Place reward: object at target + lifted
        at_target = (dist_to_place < 0.06).float()
        on_bin = (pick_pos[:, 2] > TABLE_TOP_Z + 0.02).float()
        reward += 50.0 * at_target * on_bin  # +50 for success

        self.episode_rewards += reward

        return reward

    def get_success(self):
        """Check which envs successfully placed object in bin."""
        n = self.n
        successes = torch.zeros(n, dtype=torch.bool, device=self.device)
        for i in range(n):
            obj = self.pick_objects[i]
            color = self.place_colors[i]
            obj_pos = self.bundle.objects[obj].get_pos().cpu().numpy()[i]
            cont_pos = self.bundle.containers[color].get_pos().cpu().numpy()[i]

            horizontal = np.linalg.norm(obj_pos[:2] - cont_pos[:2])
            obj_z = obj_pos[2]
            if horizontal < 0.08 and obj_z > TABLE_TOP_Z + 0.02:
                successes[i] = True
        return successes


def ppo_train(env, policy, optimizer, *, n_steps=5000, rollout_len=64,
              gamma=0.99, gae_lambda=0.95, clip_ratio=0.2, entropy_coef=0.01,
              value_coef=0.5, max_grad_norm=0.5, n_epochs=4, batch_size=256,
              save_freq=500, save_dir="outputs/rl"):
    """PPO training loop."""
    n = env.n
    device = torch.device("cuda")
    policy = policy.to(device)
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    state = env.reset()
    global_step = 0
    best_success = 0.0
    history = []
    t0 = time.time()

    print(f"PPO training: n_envs={n}, rollout_len={rollout_len}, n_epochs={n_epochs}")
    print(f"{'step':>6} | {'ep_reward':>10} | {'success%':>8} | {'loss':>8} | {'fps':>8} | {'GPU%':>6}")
    print("-" * 65)

    for step in range(n_steps):
        # Collect rollout
        states_buf, actions_buf, rewards_buf, dones_buf, log_probs_buf, values_buf = [], [], [], [], [], []

        for _ in range(rollout_len):
            with torch.no_grad():
                mean, std, value = policy(state)
                dist = torch.distributions.Normal(mean, std)
                action = dist.sample()
                log_prob = dist.log_prob(action).sum(-1)

            states_buf.append(state.clone())
            actions_buf.append(action.clone())
            log_probs_buf.append(log_prob.clone())
            values_buf.append(value.clone())

            next_state, reward, done = env.step(action)
            rewards_buf.append(reward.clone())
            dones_buf.append(done.clone())

            state = next_state
            global_step += n

            # Reset done envs
            if done.any():
                done_idx = done.cpu().numpy()
                if done_idx.any():
                    seeds = np.random.randint(0, 2**31, size=done_idx.sum())
                    # Reset only done envs
                    reset_state = env.reset(seeds=seeds)
                    state[done] = reset_state[done]

        # Compute GAE
        states = torch.stack(states_buf)  # [rollout_len, n, 9]
        actions = torch.stack(actions_buf)  # [rollout_len, n, 9]
        rewards = torch.stack(rewards_buf)  # [rollout_len, n]
        dones = torch.stack(dones_buf)  # [rollout_len, n]
        old_log_probs = torch.stack(log_probs_buf)  # [rollout_len, n]
        old_values = torch.stack(values_buf)  # [rollout_len, n]

        # GAE
        advantages = torch.zeros_like(rewards)
        returns = torch.zeros_like(rewards)
        gae = torch.zeros(n, device=device)
        for t in reversed(range(rollout_len)):
            if t == rollout_len - 1:
                with torch.no_grad():
                    _, _, next_value = policy(state)
            else:
                next_value = old_values[t + 1]
            delta = rewards[t] + gamma * next_value * (1 - dones[t].float()) - old_values[t]
            gae = delta + gae_lambda * gamma * (1 - dones[t].float()) * gae
            advantages[t] = gae
            returns[t] = advantages[t] + old_values[t]

        # PPO update
        flat_states = states.reshape(-1, 9)
        flat_actions = actions.reshape(-1, 9)
        flat_old_log_probs = old_log_probs.reshape(-1)
        flat_advantages = advantages.reshape(-1)
        flat_returns = returns.reshape(-1)
        flat_old_values = old_values.reshape(-1)

        # Normalize advantages
        flat_advantages = (flat_advantages - flat_advantages.mean()) / (flat_advantages.std() + 1e-8)

        total_loss = 0
        for epoch in range(n_epochs):
            idx = torch.randperm(flat_states.shape[0], device=device)
            for start in range(0, len(idx), batch_size):
                batch_idx = idx[start:start + batch_size]
                s = flat_states[batch_idx]
                a = flat_actions[batch_idx]
                olp = flat_old_log_probs[batch_idx]
                adv = flat_advantages[batch_idx]
                ret = flat_returns[batch_idx]

                new_log_prob, entropy, new_value = policy.evaluate(s, a)
                ratio = (new_log_prob - olp).exp()
                clipped_ratio = ratio.clamp(1 - clip_ratio, 1 + clip_ratio)

                actor_loss = -(torch.min(ratio * adv, clipped_ratio * adv)).mean()
                critic_loss = 0.5 * ((new_value - ret) ** 2).mean()
                entropy_loss = -entropy_coef * entropy.mean()
                loss = actor_loss + value_coef * critic_loss + entropy_loss

                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(policy.parameters(), max_grad_norm)
                optimizer.step()
                total_loss = loss.item()

        # Logging
        if step % 10 == 0 or step == n_steps - 1:
            # Check success rate
            successes = env.get_success()
            success_rate = successes.float().mean().item()
            ep_reward = env.episode_rewards.mean().item()

            # GPU util
            import subprocess
            try:
                r = subprocess.run(["rocm-smi", "--showuse"], capture_output=True, text=True, timeout=3)
                gpu = "?"
                for line in r.stdout.split("\n"):
                    if "GPU use (%):" in line:
                        gpu = line.split("GPU use (%):")[1].strip() + "%"
            except:
                gpu = "?"

            print(f"{step:>6} | {ep_reward:>10.2f} | {success_rate:>7.1%} | {total_loss:>8.4f} | {global_step/(time.time()-t0):>7.0f} | {gpu:>6}")
            history.append((step, ep_reward, success_rate, total_loss))

        # Save checkpoint
        if (step + 1) % save_freq == 0 or step == n_steps - 1:
            ckpt_path = save_dir / f"ppo_step_{step+1}.pt"
            torch.save({
                "step": step + 1,
                "policy_state_dict": policy.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "success_rate": success_rate if 'success_rate' in dir() else 0,
            }, ckpt_path)
            print(f"  -> saved {ckpt_path}")

            if success_rate > best_success:
                best_success = success_rate
                best_path = save_dir / "ppo_best.pt"
                torch.save({
                    "step": step + 1,
                    "policy_state_dict": policy.state_dict(),
                    "success_rate": best_success,
                }, best_path)
                print(f"  -> NEW BEST: {best_success:.1%} -> {best_path}")

    return history


def main():
    parser = argparse.ArgumentParser(description="PPO RL training for color-sorting")
    parser.add_argument("--n-envs", type=int, default=128)
    parser.add_argument("--steps", type=int, default=5000, help="PPO update steps")
    parser.add_argument("--rollout-len", type=int, default=64, help="Steps per rollout")
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--hidden", type=int, default=256)
    parser.add_argument("--max-eps-steps", type=int, default=400)
    parser.add_argument("--save-freq", type=int, default=500)
    parser.add_argument("--save-dir", default="outputs/rl")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    t0 = time.time()

    gs.init(backend=gs.gpu)
    bundle = build_scene(
        n_envs=args.n_envs,
        add_world_cam=False,
        add_wrist_cam=False,
        colors=TRAIN_COLORS,
    )

    env = ParallelSortEnv(bundle, args.n_envs, max_steps=args.max_eps_steps, seed=args.seed)
    policy = PPOPolicy(state_dim=9, action_dim=9, hidden=args.hidden)
    optimizer = torch.optim.Adam(policy.parameters(), lr=args.lr)

    print(f"\n{'='*70}")
    print(f"PPO Color-Sorting RL Training")
    print(f"  n_envs={args.n_envs}, steps={args.steps}, rollout={args.rollout_len}")
    print(f"  lr={args.lr}, hidden={args.hidden}, max_ep_steps={args.max_eps_steps}")
    print(f"{'='*70}\n")

    history = ppo_train(
        env, policy, optimizer,
        n_steps=args.steps,
        rollout_len=args.rollout_len,
        save_freq=args.save_freq,
        save_dir=args.save_dir,
    )

    elapsed = time.time() - t0
    print(f"\nTraining complete: {args.steps} steps in {elapsed:.0f}s ({args.steps*args.n_envs*args.rollout_len/elapsed:.0f} env-steps/s)")

    # Save history
    import json
    with open(Path(args.save_dir) / "training_history.json", "w") as f:
        json.dump([{"step": h[0], "reward": h[1], "success": h[2], "loss": h[3]} for h in history], f)


if __name__ == "__main__":
    main()