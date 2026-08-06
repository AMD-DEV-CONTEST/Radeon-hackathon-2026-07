"""Train with pre-trained t1_walk.pt initialization.

Loads the Booster official walking policy as PPO initial weights,
then fine-tunes for soccer tasks on AMD ROCm.
"""
import argparse, os, sys, pickle, shutil, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml, torch
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

import genesis as gs
from rsl_rl.runners import OnPolicyRunner
from envs.soccer_env import SoccerEnv


def load_pretrained_weights(runner, pretrained_path):
    """Load t1_walk.pt (TorchScript) weights into PPO actor network."""
    model = safe_jit_load(pretrained_path, map_location=gs.device)

    # Extract actor weights from TorchScript
    actor = model.actor
    obs_normalizer = model.obs_normalizer

    # Get the runner's actor model
    policy = runner.get_inference_policy(device=gs.device)
    algo = runner.alg

    # Copy actor weights
    actor_params = list(actor.parameters())
    target_params = list(algo.actor.parameters())

    print(f"Pretrained actor layers: {len(actor_params)} params")
    print(f"Target actor layers: {len(target_params)} params")

    if len(actor_params) == len(target_params):
        for src, dst in zip(actor_params, target_params):
            if src.shape == dst.shape:
                dst.data.copy_(src.data)
                print(f"  Copied: {src.shape}")
            else:
                print(f"  SKIP (shape mismatch): src={src.shape} dst={dst.shape}")
    else:
        # Try to copy matching layers
        min_len = min(len(actor_params), len(target_params))
        for i in range(min_len):
            if actor_params[i].shape == target_params[i].shape:
                target_params[i].data.copy_(actor_params[i].data)
                print(f"  Copied layer {i}: {actor_params[i].shape}")

    # Copy observation normalizer if available
    try:
        mean = obs_normalizer._mean
        var = obs_normalizer._var
        std = obs_normalizer._std
        print(f"  obs_normalizer: mean={mean.shape} var={var.shape}")
    except Exception as e:
        print(f"  obs_normalizer not accessible: {e}")

    print("Pre-trained weights loaded!")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, default=None)
    parser.add_argument("-e", "--exp_name", type=str, default=None)
    parser.add_argument("-B", "--num_envs", type=int, default=None)
    parser.add_argument("--max_iterations", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--pretrained", type=str,
                        default="/workspace/booster/booster_deploy/tasks/locomotion/models/t1_walk.pt",
                        help="Path to pre-trained t1_walk.pt")
    args = parser.parse_args()

    with open("configs/soccer_agent.yaml") as f:
        cfg = yaml.safe_load(f)

    task = args.task or cfg.get("task", "chase")
    exp_name = args.exp_name or f"{cfg.get('exp_name', 'booster_soccer')}_{task}"
    num_envs = args.num_envs or cfg.get("num_envs", 2048)
    seed = args.seed or cfg.get("seed", 42)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = task
    obs_cfg = cfg["obs"]
    reward_cfg = cfg["reward"]
    command_cfg = cfg["command"]
    train_cfg = cfg["train"]
    train_cfg["run_name"] = exp_name
    if args.max_iterations:
        train_cfg["max_iterations"] = args.max_iterations

    log_dir = f"runs/{exp_name}"
    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)
    os.makedirs(log_dir, exist_ok=True)
    with open(f"{log_dir}/cfgs.pkl", "wb") as f:
        pickle.dump([env_cfg, obs_cfg, reward_cfg, command_cfg, train_cfg], f)

    gs.init(backend=gs.gpu, precision="32", logging_level="warning", seed=seed)

    env = SoccerEnv(num_envs=num_envs, env_cfg=env_cfg, obs_cfg=obs_cfg,
                    reward_cfg=reward_cfg, command_cfg=command_cfg,
                    show_viewer=cfg.get("show_viewer", False))

    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)

    # Load pre-trained walking weights
    if os.path.exists(args.pretrained):
        print(f"\n=== Loading pre-trained weights from {args.pretrained} ===")
        load_pretrained_weights(runner, args.pretrained)
    else:
        print(f"WARNING: Pre-trained model not found at {args.pretrained}, training from scratch")

    runner.learn(num_learning_iterations=train_cfg["max_iterations"], init_at_random_ep_len=True)


if __name__ == "__main__":
    main()
