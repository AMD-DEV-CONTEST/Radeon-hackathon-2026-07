#!/usr/bin/env python3
"""Task-9 P1 eval: single-scene (1 robot) chase_hl with trained checkpoint.
Outputs metrics comparable to baseline: fallen_count/robot_disp/kicks/ball_disp/scored per 300 steps.
Usage: python3 run_task9_eval.py [--ckpt path] [--steps 300]
"""
import sys, os, json, time, glob, types, argparse
import numpy as np, torch

ROOT = "/workspace"
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + "/scripts")

import reward as _reward_mod
_rewards_pkg = types.ModuleType("rewards"); _rewards_pkg.reward = _reward_mod
_rewards_pkg.__path__ = []; sys.modules["rewards"] = _rewards_pkg; sys.modules["rewards.reward"] = _reward_mod

import yaml
import genesis as gs
from soccer_env_v4 import SoccerEnv, POLICY_JOINT_NAMES
from rsl_rl.modules import ActorCritic

ap = argparse.ArgumentParser()
ap.add_argument("--ckpt", default="")
ap.add_argument("--steps", type=int, default=300)
args = ap.parse_args()

with open(ROOT + "/configs/hierarchical_agent.yaml") as f:
    cfg = yaml.safe_load(f)
env_cfg = dict(cfg["env"]); env_cfg["task"] = "chase_hl"
hl_cfg = cfg.get("high_level", {})
train_cfg = cfg["train"]

gs.init(backend=gs.gpu, precision="32", logging_level="error", seed=7)

from run_task9_p1 import HieraSoccerEnv
env = HieraSoccerEnv(
    num_envs=1, env_cfg=env_cfg, obs_cfg=cfg["obs"],
    reward_cfg=cfg["reward"], command_cfg=cfg["command"],
    walk_model_path=hl_cfg.get("walk_model_path", ""),
    high_level_decimation=hl_cfg.get("decimation", 5),
    show_viewer=False)

if not args.ckpt:
    ckpts = sorted(glob.glob(ROOT + "/runs/task9_p1/model_*.pt"),
                   key=lambda p: int(p.split("model_")[1].split(".")[0]))
    args.ckpt = ckpts[-1]
ckpt = torch.load(args.ckpt, map_location=env.device)

actor_cfg = train_cfg.get("actor", {})
critic_cfg = train_cfg.get("critic", {})
dist_cfg = actor_cfg.get("distribution_cfg", {})
pc = {
    "actor_hidden_dims": actor_cfg.get("hidden_dims", [256, 128, 64]),
    "actor_activation": actor_cfg.get("activation", "elu"),
    "critic_hidden_dims": critic_cfg.get("hidden_dims", [256, 128, 64]),
    "critic_activation": critic_cfg.get("activation", "elu"),
    "init_noise_std": dist_cfg.get("init_std", 1.0),
    "std_type": dist_cfg.get("std_type", "scalar"),
}
ac = ActorCritic(19, 19, 3, **pc).to(env.device)
ac.load_state_dict(ckpt["model_state_dict"])
ac.eval()
print(f"[eval] ckpt={args.ckpt} iter={ckpt.get('iter','?')} steps={args.steps}", flush=True)

env.reset()
env._init_r0 = env.base_pos[0, :2].cpu().numpy().copy()
env._init_b0 = env.ball_pos[0, :2].cpu().numpy().copy()
env.fallen_count = 0; env.kick_count = 0; env.episode_count = 0

obs, extras = env.get_observations()
critic_obs = extras["observations"].get("critic", obs)
scored = False
with torch.inference_mode():
    for step in range(1, args.steps + 1):
        try:
            actions = ac.act_inference(obs)
        except AttributeError:
            actions = ac.actor(obs)
        obs, rew, dones, infos = env.step(actions)
        if bool(infos.get("scored", torch.zeros(1, dtype=torch.bool, device=env.device)).any().item()):
            scored = True
        if step % 50 == 0:
            st = env.get_stats()
            print(f"  step {step}: fallen={st['fallen_count']} disp={st['robot_disp']:.2f}m kicks={st['kicks']} ball_disp={st['ball_disp']:.2f}m eps={st['episodes']}", flush=True)

st = env.get_stats()
result = {
    "eval": "task9_p1_single_scene_300steps",
    "ckpt": args.ckpt, "steps": args.steps,
    "fallen_count": st["fallen_count"],
    "robot_disp_m": round(st["robot_disp"], 3),
    "kicks": st["kicks"],
    "ball_disp_m": round(st["ball_disp"], 3),
    "episodes": st["episodes"],
    "scored": scored,
    "mean_reward_reported": None,
}
out = ROOT + "/demos/exp/task9_p1_eval.json"
json.dump(result, open(out, "w"), indent=2)
print("\nTASK9_EVAL_DONE " + json.dumps(result))

