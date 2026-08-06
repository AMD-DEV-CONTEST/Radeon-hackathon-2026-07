#!/usr/bin/env python3
"""Export trained high-level policy to ONNX for Booster Studio deployment."""
import sys, os, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml, torch
import genesis as gs

try:
    from envs.soccer_env_hierarchical import SoccerEnvHierarchical
except ImportError:
    from soccer_env_hierarchical import SoccerEnvHierarchical
from rsl_rl.runners import OnPolicyRunner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="Path to model checkpoint")
    ap.add_argument("--task", default="chase_hl")
    ap.add_argument("--output", default="models/soccer_policy.onnx")
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
    policy = runner.get_inference_policy(device=gs.device)

    obs = env.reset()
    obs_dim = obs.shape[-1]
    print(f"Obs dim: {obs_dim}")
    print(f"Action dim: {env.num_actions}")

    dummy_input = torch.randn(1, obs_dim, device=gs.device)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    class PolicyWrapper(torch.nn.Module):
        def __init__(self, policy):
            super().__init__()
            self.policy = policy

        def forward(self, obs):
            return self.policy(obs)

    wrapped = PolicyWrapper(policy).eval()
    with torch.no_grad():
        torch.onnx.export(
            wrapped,
            dummy_input,
            args.output,
            input_names=["obs"],
            output_names=["action"],
            dynamic_axes={"obs": {0: "batch"}, "action": {0: "batch"}},
            opset_version=17,
        )

    file_size = os.path.getsize(args.output) / 1e6
    print(f"\nONNX exported: {args.output} ({file_size:.1f} MB)")
    print(f"  Input: obs [batch, {obs_dim}]")
    print(f"  Output: action [batch, {env.num_actions}]")


if __name__ == "__main__":
    main()
