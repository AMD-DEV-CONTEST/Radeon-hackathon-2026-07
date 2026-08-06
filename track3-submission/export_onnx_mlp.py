#!/usr/bin/env python3
"""Export trained high-level policy to ONNX by extracting raw MLP.

rsl_rl's MLPModel uses obs_group indexing that is incompatible with
torch.onnx.export tracing. This script extracts the underlying nn.Sequential
MLP and exports it directly, bypassing the rsl_rl wrapper.
"""
import sys, os, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml, torch

try:
    from envs.soccer_env_hierarchical import SoccerEnvHierarchical
except ImportError:
    from soccer_env_hierarchical import SoccerEnvHierarchical

import genesis as gs
from rsl_rl.runners import OnPolicyRunner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="Path to model checkpoint")
    ap.add_argument("--task", default="chase_hl")
    ap.add_argument("--output", default="models/chase_v3_policy.onnx")
    args = ap.parse_args()

    with open("configs/hierarchical_agent.yaml") as f:
        cfg = yaml.safe_load(f)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = args.task
    hl_cfg = cfg.get("high_level", {})

    gs.init(backend=gs.gpu, logging_level="warning")

    env = SoccerEnvHierarchical(
        num_envs=1,
        env_cfg=env_cfg,
        obs_cfg=cfg["obs"],
        reward_cfg=cfg["reward"],
        command_cfg=cfg["command"],
        walk_model_path=hl_cfg.get("walk_model_path",
            "/workspace/booster/booster_deploy/tasks/locomotion/models/t1_walk.pt"),
        high_level_decimation=hl_cfg.get("decimation", 5),
        show_viewer=False,
    )

    log_dir = f"runs/hierarchical_soccer_{args.task}"
    if args.model:
        model_path = args.model
    else:
        model_files = sorted(glob.glob(f"{log_dir}/model_*.pt"), key=os.path.getmtime)
        model_path = model_files[-1] if model_files else None

    if not model_path or not os.path.exists(model_path):
        print(f"ERROR: No model found at {model_path}")
        sys.exit(1)

    print(f"Loading: {model_path}")
    runner = OnPolicyRunner(env, cfg["train"], log_dir, device=gs.device)
    runner.load(model_path)

    # rsl_rl 5.4.2: PPO has .actor directly (not .actor_critic)
    if hasattr(runner.alg, 'actor'):
        policy = runner.alg.actor
    elif hasattr(runner.alg, 'actor_critic'):
        policy = runner.alg.actor_critic.actor
    else:
        policy = getattr(runner.alg, 'model', None).actor

    # Extract raw MLP (nn.Sequential) — bypass rsl_rl obs_group indexing
    mlp = policy.mlp
    obs_dim = env.hl_obs_dim
    action_dim = env.num_actions

    print(f"Obs dim: {obs_dim}, Action dim: {action_dim}")
    print(f"MLP architecture: {mlp}")

    dummy_input = torch.randn(1, obs_dim, device=gs.device)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    mlp.eval()
    with torch.no_grad():
        torch.onnx.export(
            mlp,
            dummy_input,
            args.output,
            input_names=["obs"],
            output_names=["action"],
            dynamic_axes={"obs": {0: "batch"}, "action": {0: "batch"}},
            opset_version=17,
            export_params=True, dynamo=False,           # embed weights in the ONNX file
            do_constant_folding=True,
        )

    file_size = os.path.getsize(args.output) / 1e3
    print(f"\nONNX exported: {args.output} ({file_size:.1f} KB)")
    print(f"  Input:  obs  [batch, {obs_dim}]")
    print(f"  Output: action [batch, {action_dim}]")
    print(f"  Opset: 17")

    # Validation gate: file must contain real weights
    if file_size < 10:
        print(f"  ⚠️  WARNING: File is only {file_size:.1f} KB — likely a stub export!")
        print(f"      Check that the model loaded correctly.")
    else:
        print(f"  ✓ File size {file_size:.1f} KB — weights appear embedded")


if __name__ == "__main__":
    main()
