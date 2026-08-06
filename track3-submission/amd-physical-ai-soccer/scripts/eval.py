"""Roll out a trained humanoid-soccer policy and record a demo video.

Run on the cloud instance:
    python scripts/eval.py -e booster_soccer_shoot --task shoot --video demo/soccer.mp4

Opens the viewer so you can watch; if a camera is attached it records frames.
The camera attachment is the one Genesis call worth double-checking on your
image version (gs.Cam API). Everything else is standard.
"""
import argparse
import os
import sys

# allow running `python scripts/eval.py` from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

import genesis as gs
from rsl_rl.runners import OnPolicyRunner

from envs.soccer_env import SoccerEnv
from bridge.genesis_logger import DistillLogger, record_step


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--exp_name", required=True)
    parser.add_argument("--task", type=str, default=None)
    parser.add_argument("-B", "--num_envs", type=int, default=1)
    parser.add_argument("--steps", type=int, default=600)
    parser.add_argument("--video", type=str, default="demo/soccer.mp4")
    args = parser.parse_args()

    with open("configs/soccer_agent.yaml") as f:
        cfg = yaml.safe_load(f)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = args.task or cfg.get("task", "chase")
    obs_cfg = cfg["obs"]
    reward_cfg = cfg["reward"]
    command_cfg = cfg["command"]
    train_cfg = cfg["train"]

    log_dir = f"runs/{args.exp_name}"
    gs.init(backend=gs.gpu, precision="32", logging_level="warning", seed=42)

    env = SoccerEnv(
        num_envs=args.num_envs,
        env_cfg=env_cfg,
        obs_cfg=obs_cfg,
        reward_cfg=reward_cfg,
        command_cfg=command_cfg,
        show_viewer=False,
    )

    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)
    # find latest checkpoint
    import glob
    model_files = sorted(glob.glob(f"{log_dir}/model_*.pt"), key=os.path.getmtime)
    if not model_files:
        raise FileNotFoundError(f"No model_*.pt found in {log_dir}")
    runner.load(model_files[-1])  # loads the latest checkpoint
    policy = runner.get_inference_policy(device=gs.device)

    obs = env.reset()
    os.makedirs("demo", exist_ok=True)

    # distill logger: record rollout for Booster bridge extraction
    distill_logger = DistillLogger("bridge/rollout.jsonl")

    # optional camera; harmless if your Genesis version lacks gs.Cam
    cam = None
    try:
        cam = gs.Cam(
            pos=(6.0, 6.0, 4.0),
            lookat=(0.0, 0.0, 0.5),
            field_of_view=40,
            resolution=(1280, 720),
            spp=1,
        )
        cam.attach(env.scene)
    except Exception as e:  # pragma: no cover
        print(f"[eval] camera not attached: {e}")

    for i in range(args.steps):
        actions = policy(obs)
        obs, rews, dones, _ = env.step(actions)
        soccer = env._soccer_state()
        record_step(distill_logger, env, soccer)
        if cam is not None:
            cam.render()
        if (i + 1) % 100 == 0:
            print(f"step {i + 1}/{args.steps}  mean_reward={rews.mean().item():.3f}")

    n = distill_logger.save()
    print(f"[eval] distill log saved: {n} steps -> bridge/rollout.jsonl")

    if cam is not None:
        try:
            cam.stop_recording(save_to_filename=args.video, fps=50)
            print(f"[eval] video saved -> {args.video}")
        except Exception as e:  # pragma: no cover
            print(f"[eval] could not save video: {e}")


if __name__ == "__main__":
    main()
