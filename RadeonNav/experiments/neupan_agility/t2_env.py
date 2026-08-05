#!/usr/bin/env python3
"""T2 Phase-0: vectorized frozen-stack environment + feasibility spike.

Vectorizes the deployment stack (TSC teacher-branch obs -> commander ->
frozen BBC -> UniLab MuJoCo BatchEnvPool) with NO rendering: the height
scan comes from the per-task analytic proxy heightfield. Spike gates
(preregistered T2 detail, 2026-07-31 12:40 UTC):

G1 throughput: >=2000 env-steps/s at num_envs=64;
G2 init equivalence: vectorized argmax/mean stack reproduces the frozen
   deployment adapter (teacher branch, zero history) bit-for-bit for 100
   steps at num_envs=1;
G3 gradient sanity: one PPO-style update on the trainable copy touches
   only actor_trunk/actor_d/actor_c, losses finite, KL(new||ref)=0 before
   the step.
"""

from __future__ import annotations

import argparse
import copy
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from cpp_loco_sanity import (  # noqa: E402
    DEFAULT_CPP_LOCO_CONTRACT,
    BackendAdapter,
    UNILAB,
    _sha256,
    create_env,
    ensure_registries,
)
from run_bbc_sanity import _device, _write_json  # noqa: E402
from run_source_task import (  # noqa: E402
    AGILITY_ROOT,
    HIGH_CHECKPOINT,
    POLICY_PROFILES,
    ROBOT_JOINTS,
)
from source_tasks import (  # noqa: E402
    GOAL_DELAY_STEPS,
    HORIZONTAL_SCALE,
    SCAN_X,
    SCAN_Y,
    TASKS,
    VERTICAL_SCALE,
    proxy_sampler,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityTscPolicyAdapter,
    agility_action_to_unilab,
    build_agility_proprio,
    expand_source_tsc_command,
)
from unilab.terrains import HfFlatTerrainCfg  # noqa: E402

RESULTS_ROOT = ROOT / "experiment-results/quadrupedal-agility/NAG-T2"
OBSTACLE_JOINTS = {"tire_jump": (("source_tire_joint", 0.475),),
                   "seesaw": (("source_seesaw_joint", -float(np.arcsin(0.25 / 1.5))),)}
TRAINABLE_MODULES = ("actor_trunk", "actor_d", "actor_c")
FROZEN_MODULES = ("scan_encoder", "priv_encoder", "history_encoder")


def compose_vector_env(
    task: str,
    num_envs: int,
    seed: int,
    fragment_file: Path | None = None,
    backend: str = "mujoco",
):
    """The NAG runner env composition, generalized to num_envs."""
    from hydra import compose, initialize_config_dir
    from hydra.core.global_hydra import GlobalHydra

    GlobalHydra.instance().clear()
    with initialize_config_dir(config_dir=str(UNILAB / "conf/ppo"), version_base="1.3"):
        cfg = compose(
            config_name="config",
            overrides=[
                f"task=go2_joystick_rough/{backend}",
                f"algo.num_envs={num_envs}",
                f"training.play_env_num={num_envs}",
                "training.no_play=true",
                "hydra.run.dir=.",
                "hydra.output_subdir=null",
                "hydra/job_logging=disabled",
                "hydra/hydra_logging=disabled",
            ],
        )
    env_override = BackendAdapter(
        cfg, root_dir=UNILAB, algo_name="ppo"
    ).build_task_env_cfg_override()
    env_override["commands"]["resampling_time"] = 0.0
    env_override["commands"]["heading_command"] = False
    env_override["control_config"]["Kp"] = 40.0
    env_override["control_config"]["Kd"] = 1.0
    env_override["control_config"]["simulate_action_latency"] = True
    env_override["control_config"]["clip_actions"] = (
        DEFAULT_CPP_LOCO_CONTRACT.unilab_clip_actions
    )
    env_override["terrain_curriculum"]["enabled"] = False
    env_override["scene"]["terrain"]["generator"].update(
        {
            "seed": seed,
            "curriculum": False,
            "size": [8.0, 8.0],
            "horizontal_scale": HORIZONTAL_SCALE,
            "vertical_scale": VERTICAL_SCALE,
            "border_width": 10.0,
            "num_rows": 1,
            "num_cols": 1,
            "sub_terrains": {
                "flat": HfFlatTerrainCfg(
                    proportion=1.0,
                    horizontal_scale=HORIZONTAL_SCALE,
                    vertical_scale=VERTICAL_SCALE,
                )
            },
        }
    )
    env_override["terrain_scan"].update(
        {
            "measured_points_x": list(SCAN_X),
            "measured_points_y": list(SCAN_Y),
            "vertical_offset": 0.3,
            "scale": 1.0,
        }
    )
    for key in (
        "randomize_base_mass",
        "random_com",
        "randomize_kp",
        "randomize_kd",
        "randomize_ground_friction",
        "push_robots",
    ):
        env_override["domain_rand"][key] = False
    env_override["domain_rand"]["randomize_ground_friction"] = True
    env_override["domain_rand"]["ground_friction_multiplier_range"] = [1.0, 1.0]
    scene = env_override["scene"]
    model_file = Path(scene["model_file"])
    if not model_file.is_absolute():
        scene["model_file"] = str((UNILAB / model_file).resolve())
    scene["fragment_files"] = [
        str((UNILAB / p).resolve()) if not Path(p).is_absolute() else str(p)
        for p in scene.get("fragment_files", [])
    ]
    fragment = fragment_file if fragment_file is not None else (
        TASKS[task].fragment_file if task in TASKS else None
    )
    if fragment is not None:
        scene["fragment_files"].append(str(Path(fragment).resolve()))
    ensure_registries()
    return create_env(cfg, num_envs=num_envs, env_cfg_override=env_override)


def vector_set_commands(
    commander, skill: torch.Tensor, continuous: torch.Tensor
) -> torch.Tensor:
    """Batched replica of go2_deploy CommandBuilder.set_commands (fp32).

    Same op order as the source single-env builder so the N=1 slice is
    bit-identical: per-skill 6-value block -> clip -> (c+1)/2 -> offset +
    range scaling on [:5], 6th value passes through as latent eps, and the
    jump mode zeroes the locomotion-height slot (others zero jump height).
    """
    d = skill.long().clamp(0, commander.mode_count - 1)
    arange6 = torch.arange(6, device=continuous.device)
    block = torch.gather(continuous, 1, d.unsqueeze(1) * 6 + arange6.unsqueeze(0))
    block = torch.clip(block, -1, 1)
    eps = block[:, 5:6]
    c01 = (block + 1) / 2
    scaled = (
        commander.command_offset_mat[d] + commander.command_range_mat[d] * c01[:, :5]
    ).clone()
    jump = d == int(commander.jump_mode)
    scaled[jump, 4] = 0
    scaled[~jump, 3] = 0
    return torch.cat([scaled, eps, commander.latent_c_one_hot[d]], dim=1)


def _yaw_from_quat(quat_wxyz: np.ndarray) -> np.ndarray:
    w, x, y, z = quat_wxyz[:, 0], quat_wxyz[:, 1], quat_wxyz[:, 2], quat_wxyz[:, 3]
    return np.arctan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _wrap(a: np.ndarray) -> np.ndarray:
    return (a + np.pi) % (2.0 * np.pi) - np.pi


class VectorAgilityStack:
    """Batched deployment stack on one source task (teacher branch)."""

    def __init__(
        self,
        task: str,
        num_envs: int,
        device: torch.device,
        seed: int,
        spec=None,
        sampler=None,
        fragment_file: Path | None = None,
        backend: str = "mujoco",
    ):
        self.task = task
        self.spec = spec if spec is not None else TASKS[task]
        self.num_envs = num_envs
        self.device = device
        self.env = compose_vector_env(
            task, num_envs, seed, fragment_file=fragment_file, backend=backend
        )
        self.backend = self.env._backend
        self.sampler = sampler if sampler is not None else proxy_sampler(task)
        self.adapter = AgilityTscPolicyAdapter(
            AGILITY_ROOT,
            HIGH_CHECKPOINT,
            POLICY_PROFILES["deployment3"].low_checkpoint,
            device=device,
            low_contract=POLICY_PROFILES["deployment3"].low_contract,
            low_mode_count=POLICY_PROFILES["deployment3"].low_mode_count,
            command_profile="deployment",
            high_branch="teacher",
            use_half=False,
        )
        self.goals = np.asarray(self.spec.goals, dtype=np.float64)
        self.contract = POLICY_PROFILES["deployment3"].low_contract
        grid = np.meshgrid(SCAN_X, SCAN_Y, indexing="ij")
        self.scan_offsets = np.stack(
            (grid[0].reshape(-1), grid[1].reshape(-1)), axis=1
        ).astype(np.float64)
        self.reset_all()

    # -- state --------------------------------------------------------
    def reset_all(self) -> None:
        n = self.num_envs
        qpos = np.tile(
            np.asarray(self.env._init_qpos, dtype=np.float32).reshape(1, -1), (n, 1)
        )
        qvel = np.tile(
            np.zeros_like(np.asarray(self.env._init_qvel, dtype=np.float32)).reshape(
                1, -1
            ),
            (n, 1),
        )
        start = self.goals[0]
        qpos[:, 0], qpos[:, 1], qpos[:, 2] = start[0], start[1], 0.42
        qpos[:, 3:7] = (1.0, 0.0, 0.0, 0.0)
        idx = self.backend.get_joint_dof_pos_indices(ROBOT_JOINTS) + 7
        qpos[:, idx] = self.contract.source_default_dof
        for joint, value in OBSTACLE_JOINTS.get(self.task, ()):
            j = self.backend.get_joint_dof_pos_indices((joint,))[0] + 7
            qpos[:, int(j)] = value
        self.state = self.env.init_state()
        self.env.set_autoreset(False)
        self.backend.set_state(np.arange(n, dtype=np.int32), qpos, qvel)
        self.state = self.env.update_state(self.state)
        self.previous_action = np.zeros((n, 12), dtype=np.float32)
        self.previous_contact = np.zeros((n, 4), dtype=np.float32)
        self.goal_index = np.ones(n, dtype=np.int64)  # spawn at goals[0]
        self.goal_timer = np.zeros(n, dtype=np.int64)
        self.adapter.bbc.history.fill(0.0)

    # -- observation --------------------------------------------------
    def observe(self) -> dict[str, Any]:
        base_pos = self.backend.get_base_pos().copy()
        base_quat = self.backend.get_base_quat().copy()
        gyro = self.env.get_gyro().copy()
        dof_pos = self.env.get_dof_pos().copy()
        dof_vel = self.env.get_dof_vel().copy()
        feet = (np.linalg.norm(self.env.feet_force, axis=2) > 2.0).astype(np.float32)
        contact = np.maximum(feet, self.previous_contact)
        self.previous_contact = feet
        proprio = build_agility_proprio(
            base_quat, gyro, dof_pos, dof_vel, self.previous_action, contact
        )
        yaw = _yaw_from_quat(base_quat.astype(np.float64))
        # goal-chain delta yaw (source semantics, vectorized)
        pos2 = base_pos[:, :2].astype(np.float64)
        cur = self.goals[np.minimum(self.goal_index, len(self.goals) - 1), :2]
        dist = np.linalg.norm(cur - pos2, axis=1)
        reached = dist < 0.4
        self.goal_timer = np.where(reached, self.goal_timer + 1, 0)
        advance = (self.goal_timer > GOAL_DELAY_STEPS) & (
            self.goal_index < len(self.goals) - 1
        )
        self.goal_index = np.where(advance, self.goal_index + 1, self.goal_index)
        self.goal_timer = np.where(advance, 0, self.goal_timer)
        cur = self.goals[np.minimum(self.goal_index, len(self.goals) - 1), :2]
        nxt = self.goals[np.minimum(self.goal_index + 1, len(self.goals) - 1), :2]
        d_cur = _wrap(np.arctan2(cur[:, 1] - pos2[:, 1], cur[:, 0] - pos2[:, 0]) - yaw)
        d_nxt = _wrap(np.arctan2(nxt[:, 1] - pos2[:, 1], nxt[:, 0] - pos2[:, 0]) - yaw)
        delta_yaw = np.stack((d_cur, d_nxt), axis=1).astype(np.float32)
        # analytic proxy scan
        c, s = np.cos(yaw), np.sin(yaw)
        rot = np.stack(
            (np.stack((c, -s), axis=1), np.stack((s, c), axis=1)), axis=1
        )  # (N,2,2)
        world = (
            self.scan_offsets[None, :, :] @ rot.transpose(0, 2, 1)
        ) + pos2[:, None, :]
        ground = self.sampler.sample_height(world.reshape(-1, 2)).reshape(
            self.num_envs, -1
        )
        scan = np.clip(
            base_pos[:, 2:3].astype(np.float64) - 0.3 - ground, -1.0, 1.0
        ).astype(np.float32)
        one_hot = np.zeros((self.num_envs, 6), dtype=np.float32)
        one_hot[:, self.spec.obstacle_index] = 1.0
        return {
            "proprio": proprio,
            "delta_yaw": delta_yaw,
            "one_hot": one_hot,
            "scan": scan,
            "base_pos": base_pos,
            "base_quat": base_quat,
            "gyro": gyro,
            "dof_pos": dof_pos,
            "dof_vel": dof_vel,
            "contact": contact,
        }

    def high_input(self, obs: dict[str, Any]) -> torch.Tensor:
        t = lambda a: torch.as_tensor(a, device=self.device, dtype=torch.float32)
        proprio = t(obs["proprio"])
        with torch.no_grad():
            explicit = self.adapter.high_estimator(proprio)
        return torch.cat(
            (
                proprio,
                t(obs["delta_yaw"]),
                t(obs["one_hot"]),
                t(obs["scan"]),
                explicit,
                torch.zeros(
                    (self.num_envs, 570), device=self.device, dtype=torch.float32
                ),
            ),
            dim=1,
        )

    # -- transition ---------------------------------------------------
    # Optional hook: callable(low_input_tensor) -> (N, 12) source-action
    # tensor. When set, replaces the frozen BBC forward (T3-P2 trial).
    bbc_forward = None

    def step_with_action(
        self, obs: dict[str, Any], skill: torch.Tensor, continuous: torch.Tensor
    ) -> None:
        command = vector_set_commands(self.adapter.commander, skill, continuous)
        if self.adapter.low_mode_count == 5:
            command = expand_source_tsc_command(command)
        t = lambda a: torch.as_tensor(a, device=self.device, dtype=torch.float32)
        proprio = t(obs["proprio"])
        with torch.no_grad():
            explicit = self.adapter.bbc.estimator(proprio)
            low_input = torch.cat(
                (
                    proprio,
                    explicit,
                    torch.zeros(
                        (self.num_envs, 29), device=self.device, dtype=torch.float32
                    ),
                    torch.zeros(
                        (self.num_envs, 570), device=self.device, dtype=torch.float32
                    ),
                    command,
                ),
                dim=1,
            )
            if self.bbc_forward is not None:
                source_action = (
                    self.bbc_forward(low_input).cpu().numpy().astype(np.float32)
                )
            else:
                source_action = (
                    self.adapter.bbc.model.act_inference(low_input, hist_encoding=True)
                    .cpu()
                    .numpy()
                    .astype(np.float32)
                )
        self.previous_action = source_action
        action = agility_action_to_unilab(source_action, self.contract)
        self.state = self.env.step(action)


def spike(args: argparse.Namespace) -> dict[str, Any]:
    device = _device(args.device)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    checks: dict[str, Any] = {}
    metrics: dict[str, Any] = {}

    # ---- G2: init equivalence at num_envs=1 --------------------------
    stack = VectorAgilityStack(args.task, 1, device, args.seed)
    adapter = stack.adapter
    actor = adapter.high_model
    max_abs = 0.0
    for _ in range(100):
        obs = stack.observe()
        high_input = stack.high_input(obs)
        with torch.no_grad():
            embedding = actor(high_input, hist_encoding=True, scandots_latent=None)
            skill = torch.argmax(actor.actor_d(embedding), dim=-1)
            continuous = actor.actor_c(embedding)
        adapter.bbc.history.fill(0.0)
        command_ref, diag = adapter.preview_command(
            base_quat_wxyz=obs["base_quat"],
            base_ang_vel=obs["gyro"],
            dof_pos=obs["dof_pos"],
            dof_vel=obs["dof_vel"],
            foot_contact=obs["contact"],
            height_scan=obs["scan"],
            delta_yaw=obs["delta_yaw"],
            obstacle_type=int(stack.spec.obstacle_index),
        )
        ref_prev = adapter.bbc.previous_action.copy()
        adapter.bbc.history.fill(0.0)
        action_ref, low = adapter.bbc.act(
            base_quat_wxyz=obs["base_quat"],
            base_ang_vel=obs["gyro"],
            dof_pos=obs["dof_pos"],
            dof_vel=obs["dof_vel"],
            foot_contact=obs["contact"],
            command=command_ref,
            explicit=None,
        )
        # vector path consumes the same pre-act previous_action state
        stack.previous_action = ref_prev
        command_vec = vector_set_commands(adapter.commander, skill, continuous)
        max_abs = max(
            max_abs,
            float(np.abs(command_vec.cpu().numpy() - command_ref).max()),
            float(abs(int(skill[0]) - int(diag["skill"][0]))),
        )
        stack.previous_action = low["source_action"]
        stack.state = stack.env.step(
            agility_action_to_unilab(low["source_action"], stack.contract)
        )
    checks["init_equivalence_100_steps"] = max_abs == 0.0
    metrics["equivalence_max_abs_diff"] = max_abs
    stack.env.close()

    # ---- G1: throughput at num_envs=N ---------------------------------
    stack = VectorAgilityStack(args.task, args.num_envs, device, args.seed)
    actor = stack.adapter.high_model
    for _ in range(10):  # warmup
        obs = stack.observe()
        with torch.no_grad():
            emb = actor(stack.high_input(obs), hist_encoding=True, scandots_latent=None)
            stack.step_with_action(
                obs, torch.argmax(actor.actor_d(emb), -1), actor.actor_c(emb)
            )
    started = time.monotonic()
    for _ in range(args.throughput_steps):
        obs = stack.observe()
        with torch.no_grad():
            emb = actor(stack.high_input(obs), hist_encoding=True, scandots_latent=None)
            stack.step_with_action(
                obs, torch.argmax(actor.actor_d(emb), -1), actor.actor_c(emb)
            )
    elapsed = time.monotonic() - started
    throughput = args.num_envs * args.throughput_steps / elapsed
    checks["throughput_gate_2000"] = throughput >= 2000.0
    metrics["env_steps_per_sec"] = throughput
    metrics["num_envs"] = args.num_envs

    # ---- G3: gradient sanity ------------------------------------------
    trainable = copy.deepcopy(actor).float()
    for name, parameter in trainable.named_parameters():
        parameter.requires_grad_(any(name.startswith(m) for m in TRAINABLE_MODULES))
    std = torch.exp(
        torch.zeros(18, device=device)
    )  # placeholder; real std warm-started in trainer
    obs = stack.observe()
    high_input = stack.high_input(obs)
    with torch.no_grad():
        ref_emb = actor(high_input, hist_encoding=True, scandots_latent=None)
        ref_logits = actor.actor_d(ref_emb)
        ref_mean = actor.actor_c(ref_emb)
    emb = trainable(high_input, hist_encoding=True, scandots_latent=None)
    logits = trainable.actor_d(emb)
    mean = trainable.actor_c(emb)
    kl_pre = float(
        (
            F.kl_div(
                F.log_softmax(logits, -1), F.softmax(ref_logits, -1), reduction="batchmean"
            )
            + ((mean - ref_mean) ** 2 / (2 * std**2)).sum(-1).mean()
        )
    )
    dist_d = torch.distributions.Categorical(logits=logits)
    dist_c = torch.distributions.Normal(mean, std)
    sample_d, sample_c = dist_d.sample(), dist_c.sample()
    log_prob = dist_d.log_prob(sample_d) + dist_c.log_prob(sample_c).sum(-1)
    advantage = torch.randn_like(log_prob)
    loss = -(log_prob * advantage).mean() + 0.5 * ((mean - ref_mean) ** 2).mean()
    loss.backward()
    frozen_grads = [
        name
        for name, p in trainable.named_parameters()
        if any(name.startswith(m) for m in FROZEN_MODULES) and p.grad is not None
    ]
    trainable_grads = [
        name
        for name, p in trainable.named_parameters()
        if any(name.startswith(m) for m in TRAINABLE_MODULES)
        and (p.grad is None or not torch.isfinite(p.grad).all())
    ]
    checks["grads_only_trunk_and_heads"] = not frozen_grads and not trainable_grads
    checks["kl_zero_at_init"] = kl_pre < 1e-6
    checks["loss_finite"] = bool(torch.isfinite(loss))
    metrics["kl_pre_update"] = kl_pre
    metrics["loss"] = float(loss)
    metrics["frozen_modules_with_grads"] = frozen_grads[:5]
    stack.env.close()

    return {
        "run_id": f"NAG-T2-SPIKE-{args.task}",
        "status": "PASSED" if all(v for v in checks.values() if isinstance(v, bool)) else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "simulation_only",
        "scope": "T2 phase-0 feasibility spike (vectorized stack, no training)",
        "seed": args.seed,
        "task": args.task,
        "checks": checks,
        "metrics": metrics,
        "contracts": {
            "trainable_modules": TRAINABLE_MODULES,
            "frozen_modules": FROZEN_MODULES,
            "history_convention": "zeros + hist_encoding=True (cell-D deployment)",
            "high_checkpoint_sha256": _sha256(HIGH_CHECKPOINT),
            "runner_sha256": _sha256(Path(__file__)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="tire_jump", choices=tuple(TASKS))
    parser.add_argument("--num-envs", type=int, default=64)
    parser.add_argument("--throughput-steps", type=int, default=200)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    out = RESULTS_ROOT / "spike"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        payload = spike(args)
    except Exception as exc:  # archived, not raised: spike is a gate
        payload = {
            "run_id": f"NAG-T2-SPIKE-{args.task}",
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    path = out / f"result_{stamp}.json"
    _write_json(path, payload)
    shutil.copy2(path, out / "result.json")
    print(f"{payload['status']}: {path}")
    if "metrics" in payload:
        print("checks:", payload["checks"])
        print("throughput:", payload["metrics"].get("env_steps_per_sec"))
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
