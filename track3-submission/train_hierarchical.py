"""Train high-level velocity policy with frozen t1_walk.pt low-level.

Architecture:
    High-level PPO (19 obs → 3 action: vx, vy, wz)
        ↓ velocity commands (injected into low-level obs)
    Frozen t1_walk.pt (720 obs → 21 action: joint targets)
        ↓ PD control at 50 Hz
    Genesis physics (AMD Radeon GPU)

The high-level policy directly observes ball position, velocity, and goal
direction in body frame. The frozen walking model handles balance and gait.

Usage (on cloud):
    cd /workspace/amd-physical-ai-soccer
    python train_hierarchical.py --max_iterations 500

    # Fewer envs for debugging:
    python train_hierarchical.py --num_envs 256 --max_iterations 100

    # Custom walk model path:
    python train_hierarchical.py --pretrained /path/to/t1_walk.pt
"""
import argparse, os, sys, pickle, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml, torch
import genesis as gs
from rsl_rl.runners import OnPolicyRunner

# Import env (works both locally and on remote)
try:
    from envs.soccer_env_hierarchical import SoccerEnvHierarchical
except ImportError:
    from soccer_env_hierarchical import SoccerEnvHierarchical


def main():
    parser = argparse.ArgumentParser(description="Hierarchical soccer training")
    parser.add_argument("--task", type=str, default=None)
    parser.add_argument("-e", "--exp_name", type=str, default=None)
    parser.add_argument("-B", "--num_envs", type=int, default=None)
    parser.add_argument("--max_iterations", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--pretrained", type=str,
                        default="/workspace/booster/booster_deploy/tasks/locomotion/models/t1_walk.pt",
                        help="Path to frozen t1_walk.pt")
    parser.add_argument("--decimation", type=int, default=None,
                        help="High-level decimation (default: 5 = 10 Hz)")
    parser.add_argument("--resume", type=str, default=None,
                        help="Resume from checkpoint path")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to config YAML (default: configs/hierarchical_agent.yaml)")
    parser.add_argument("--clip_lin", type=float, default=None,
                        help="Override HL linear velocity clip (m/s). For parallel A/B runs.")
    parser.add_argument("--clip_ang", type=float, default=None,
                        help="Override HL angular velocity clip (rad/s). For parallel A/B runs.")
    args = parser.parse_args()

    config_path = args.config or "configs/hierarchical_agent.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    task = args.task or cfg.get("task", "chase_hl")
    exp_name = args.exp_name or f"{cfg.get('exp_name', 'hierarchical_soccer')}_{task}"
    num_envs = args.num_envs or cfg.get("num_envs", 2048)
    seed = args.seed or cfg.get("seed", 42)

    hl_cfg = cfg.get("high_level", {})
    walk_model_path = args.pretrained
    decimation = args.decimation or hl_cfg.get("decimation", 5)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = task
    if args.clip_lin is not None:
        env_cfg["hl_clip_lin"] = args.clip_lin
    if args.clip_ang is not None:
        env_cfg["hl_clip_ang"] = args.clip_ang
    obs_cfg = cfg["obs"]
    reward_cfg = cfg["reward"]
    command_cfg = cfg["command"]
    train_cfg = cfg["train"]
    train_cfg["run_name"] = exp_name
    if args.max_iterations:
        train_cfg["max_iterations"] = args.max_iterations

    log_dir = f"runs/{exp_name}"
    if args.resume is None:
        if os.path.exists(log_dir):
            shutil.rmtree(log_dir)
        os.makedirs(log_dir, exist_ok=True)
    else:
        os.makedirs(log_dir, exist_ok=True)
    with open(f"{log_dir}/cfgs.pkl", "wb") as f:
        pickle.dump([env_cfg, obs_cfg, reward_cfg, command_cfg, train_cfg], f)

    gs.init(backend=gs.gpu, precision="32", logging_level="warning", seed=seed)

    env = SoccerEnvHierarchical(
        num_envs=num_envs,
        env_cfg=env_cfg,
        obs_cfg=obs_cfg,
        reward_cfg=reward_cfg,
        command_cfg=command_cfg,
        walk_model_path=walk_model_path,
        high_level_decimation=decimation,
        show_viewer=cfg.get("show_viewer", False),
    )

    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)

    # Resume from checkpoint if specified
    if args.resume:
        print(f"\n=== Resuming from {args.resume} ===")
        runner.load(args.resume)

    print(f"\n{'='*60}")
    print(f"  Hierarchical Soccer Training")
    print(f"{'='*60}")
    print(f"  High-level obs dim:    {env.hl_obs_dim}")
    print(f"  High-level action dim: {env.num_actions} (vx, vy, wz)")
    print(f"  Low-level model:       {walk_model_path}")
    print(f"  Decimation:            {decimation} (HL dt = {env.high_level_dt:.3f}s)")
    print(f"  Envs:                  {num_envs}")
    print(f"  Max iterations:        {train_cfg['max_iterations']}")
    print(f"  Save interval:         {train_cfg.get('save_interval', 50)}")
    print(f"  Log dir:               {log_dir}")
    print(f"{'='*60}\n")

    runner.learn(
        num_learning_iterations=train_cfg["max_iterations"],
        init_at_random_ep_len=True,
    )

    print(f"\n=== Training complete ===")
    print(f"  Models saved in: {log_dir}")
    print(f"  Best model: {log_dir}/model_{train_cfg['max_iterations']}.pt")


if __name__ == "__main__":
    main()
