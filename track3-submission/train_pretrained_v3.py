"""Train with pre-trained t1_walk.pt initialization — exact weight transfer.

Maps TorchScript param names (0.weight) to rsl-rl names (mlp.0.weight).
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
    """Load t1_walk.pt (TorchScript) weights into PPO actor."""
    model = safe_jit_load(pretrained_path, map_location=gs.device)
    actor = model.actor
    obs_normalizer = model.obs_normalizer

    algo = runner.alg

    # === Get pretrained params as dict ===
    pretrained_dict = {}
    for name, param in actor.named_parameters():
        pretrained_dict[name] = param.data.clone()

    print(f"Pretrained params: {len(pretrained_dict)}")
    for name, p in pretrained_dict.items():
        print(f"  {name}: {p.shape}")

    # === Get target params and map ===
    # TorchScript: "0.weight" → rsl-rl: "mlp.0.weight"
    target_dict = dict(algo.actor.named_parameters())

    print(f"\nTarget params: {len(target_dict)}")
    copied = 0
    for name, param in target_dict.items():
        # Map: mlp.X.weight → X.weight, mlp.X.bias → X.bias
        src_name = name.replace("mlp.", "") if name.startswith("mlp.") else name
        if src_name in pretrained_dict:
            src = pretrained_dict[src_name]
            if src.shape == param.shape:
                param.data.copy_(src)
                copied += 1
                print(f"  ✓ {name} ← {src_name}: {src.shape}")
            else:
                print(f"  ✗ {name} shape mismatch: src={src.shape} dst={param.shape}")
        else:
            print(f"  - {name}: no pretrained source (skipped)")

    # distribution.std_param — copy from pretrained if available
    if hasattr(model, 'actor') and hasattr(model.actor, 'distribution'):
        try:
            std = model.actor.distribution.std_param
            if hasattr(algo.actor, 'distribution') and hasattr(algo.actor.distribution, 'std_param'):
                if std.shape == algo.actor.distribution.std_param.shape:
                    algo.actor.distribution.std_param.data.copy_(std.data)
                    print(f"  ✓ distribution.std_param: {std.shape}")
        except Exception as e:
            print(f"  - distribution.std_param: {e}")

    # === Obs normalizer ===
    try:
        mean = obs_normalizer._mean
        var = obs_normalizer._var
        std = obs_normalizer._std
        count = obs_normalizer.count
        print(f"\n  Obs normalizer: mean={mean.shape} var={var.shape} count={count.item()}")

        # rsl-rl uses Identity() by default — need to replace with running mean/var
        # Check if the actor has a replaceable normalizer
        if hasattr(algo.actor, 'obs_normalizer'):
            from rsl_rl.models.running_mean_std import RunningMeanStd
            # Replace Identity with RunningMeanStd
            new_norm = RunningMeanStd(mean.shape[-1]).to(gs.device)
            new_norm._mean.data.copy_(mean.data)
            new_norm._var.data.copy_(var.data)
            new_norm._std.data.copy_(std.data)
            new_norm.count.data.copy_(count.data)
            algo.actor.obs_normalizer = new_norm
            print(f"  ✓ Obs normalizer installed: mean={mean.shape}")
    except Exception as e:
        print(f"  Obs normalizer skipped: {e}")

    print(f"\nTotal copied: {copied}/{len(pretrained_dict)} layers")
    print("Pre-trained weights loaded!\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=str, default=None)
    parser.add_argument("-e", "--exp_name", type=str, default=None)
    parser.add_argument("-B", "--num_envs", type=int, default=None)
    parser.add_argument("--max_iterations", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--pretrained", type=str,
                        default="/workspace/booster/booster_deploy/tasks/locomotion/models/t1_walk.pt")
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

    if os.path.exists(args.pretrained):
        print(f"\n=== Loading pre-trained weights from {args.pretrained} ===")
        load_pretrained_weights(runner, args.pretrained)
    else:
        print(f"WARNING: Pre-trained model not found at {args.pretrained}")

    runner.learn(num_learning_iterations=train_cfg["max_iterations"], init_at_random_ep_len=True)


if __name__ == "__main__":
    main()
