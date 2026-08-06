"""Customer-facing JAX training entry point for pi05 (self-contained).

All configuration is via CLI args — no edit to ``src/openpi/training/config.py`` and no named config to
register. ``--norm-stats`` is REQUIRED; produce it once with ``compute_norm_stats.py``. Dispatches
in-process to ``scripts/train.py:main(config)`` (loaded under a unique module name to avoid clashes).

Note: on the RTX 5090, run the JAX trainers with ``JAX_PLATFORMS=cpu`` only when you want JAX off the
GPU; for JAX training you want it on GPU.

Examples:
  # 1) one-time norm_stats (needs only the dataset dir):
  python3 compute_norm_stats.py \
      --data-dir ~/BiGym_Dev/data/bigym_plus/cupboards_close_all \
      --output-dir ./assets/cupboards_close_all

  # 2) train:
  python3 train_jax.py \
      --action-dim 16 --action-horizon 10 \
      --camera-names high l_wrist r_wrist \
      --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
      --wrist-names l_wrist r_wrist \
      --data-dir ~/BiGym_Dev/data/bigym_plus/cupboards_close_all \
      --exp-name run1 --norm-stats ./assets/cupboards_close_all \
      --base-checkpoint gs://openpi-assets/checkpoints/pi05_base/params \
      --num-train-steps 20000 --overwrite
"""

import argparse
import importlib.util
import pathlib
import shutil

from openpi.models import pi0_config
from openpi.training import config as _config
from openpi.training import optimizer as _optimizer
from openpi.training import weight_loaders as _weight_loaders


def add_args(parser: argparse.ArgumentParser) -> None:
    """All CLI args for this trainer (model + data + training)."""
    # Model + data.
    parser.add_argument("--action-dim", type=int, required=True, help="Action dimension of THIS robot (dataset / inference dim).")
    parser.add_argument(
        "--model-action-dim",
        type=int,
        default=32,
        help="Base checkpoint action_dim. pi05_base is trained with 32-dim actions, so the model's action "
             "projection must stay 32 to match the base. Dataset actions are zero-padded to this "
             "(PadStatesAndActions) and inference slices outputs back to --action-dim (MultiCameraOutputs).",
    )
    parser.add_argument("--action-horizon", type=int, default=10, help="Action chunk horizon (pi05 typical: 10).")
    parser.add_argument(
        "--lora",
        action="store_true",
        help="Low-memory LoRA fine-tuning (gemma_2b_lora + gemma_300m_lora, base frozen). Required to fit a single 32GB GPU.",
    )
    parser.add_argument("--camera-names", nargs="+", required=True, help="Model image-token order (must match inference).")
    parser.add_argument(
        "--camera-sources",
        nargs="+",
        required=True,
        help="LeRobot flattened paths mapping to each camera name (same order as --camera-names).",
    )
    parser.add_argument(
        "--wrist-names", nargs="*", default=[], help="Subset of --camera-names that are wrist cameras."
    )
    parser.add_argument(
        "--data-dir", required=True, help="Local LeRobot dataset directory (contains meta/data/videos)."
    )
    parser.add_argument("--state-source", default="observation.state")
    parser.add_argument("--action-source", default="action")
    parser.add_argument(
        "--prompt-from-task",
        dest="prompt_from_task",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Read the prompt from the LeRobot task table.",
    )
    parser.add_argument("--default-prompt", default=None, help="Prompt injected when absent (also the inference default).")

    # Identity (drives <checkpoint_base_dir>/<config_name>/<exp_name>).
    parser.add_argument("--config-name", default=None, help="Config name. Defaults to the data-dir basename.")
    parser.add_argument("--exp-name", required=True, help="Experiment name (checkpoint subdir).")

    # norm_stats: REQUIRED, user-run via compute_norm_stats.py.
    parser.add_argument(
        "--norm-stats",
        required=True,
        help="Path to norm_stats.json or its dir (produced by compute_norm_stats.py). Required.",
    )

    # Weights.
    parser.add_argument(
        "--base-checkpoint",
        default=None,
        help="JAX params path (released base) for JAX fine-tuning. Enables CheckpointWeightLoader.",
    )
    parser.add_argument(
        "--pytorch-weight-path",
        default=None,
        help="Dir with model.safetensors for PyTorch fine-tuning (consumed by the PyTorch train loop).",
    )
    parser.add_argument("--pytorch-precision", choices=["bfloat16", "float32"], default="bfloat16")

    # LR schedule.
    parser.add_argument("--peak-lr", type=float, default=2.5e-5)
    parser.add_argument("--warmup-steps", type=int, default=1_000)
    parser.add_argument("--decay-steps", type=int, default=30_000)
    parser.add_argument("--decay-lr", type=float, default=2.5e-6)

    # Optimizer.
    parser.add_argument("--weight-decay", type=float, default=1e-10)
    parser.add_argument("--grad-clip", type=float, default=1.0)

    # Training loop.
    parser.add_argument("--num-train-steps", type=int, default=30_000)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--save-interval", type=int, default=1_000)
    parser.add_argument("--log-interval", type=int, default=100)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fsdp-devices", type=int, default=1, help="JAX FSDP device count.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite the checkpoint dir if it exists.")
    parser.add_argument("--resume", action="store_true", help="Resume from the latest checkpoint.")
    parser.add_argument("--assets-base-dir", default="./assets")
    parser.add_argument("--checkpoint-base-dir", default="./checkpoints")
    parser.add_argument(
        "--wandb",
        dest="wandb_enabled",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable wandb logging. Off by default — this environment has no wandb API key, so the default-on "
             "would crash at init_wandb before training starts. Pass --wandb to turn it on (after `wandb login`).",
    )


def build_config(args) -> _config.TrainConfig:
    """Build the openpi TrainConfig straight from parsed args (no config.py registration)."""
    if len(args.camera_names) != len(args.camera_sources):
        raise SystemExit("--camera-names and --camera-sources must have the same length.")
    cameras = tuple(
        _config.CameraSpec(name=n, source=s, is_wrist=(n in args.wrist_names))
        for n, s in zip(args.camera_names, args.camera_sources)
    )
    paligemma_variant = "gemma_2b_lora" if args.lora else "gemma_2b"
    action_expert_variant = "gemma_300m_lora" if args.lora else "gemma_300m"
    model = pi0_config.Pi0Config(
        pi05=True,
        paligemma_variant=paligemma_variant,
        action_expert_variant=action_expert_variant,
        action_dim=args.model_action_dim,  # must match the base checkpoint (pi05_base=32); dataset is padded to this
        action_horizon=args.action_horizon,
        image_keys=tuple(args.camera_names),
        wrist_image_keys=tuple(args.wrist_names),
    )
    # data_dir is the local dataset path; the data pipeline loads it offline from disk (no HF Hub).
    data = _config.LeRobotMultiCameraDataConfig(
        data_dir=args.data_dir,
        cameras=cameras,
        state_source=args.state_source,
        action_source=args.action_source,
        prompt_from_task=args.prompt_from_task,
        default_prompt=args.default_prompt,
        action_dim=args.action_dim,  # robot's real dim; drives inference output slicing (MultiCameraOutputs)
    )
    weight_loader = (
        _weight_loaders.CheckpointWeightLoader(args.base_checkpoint)
        if args.base_checkpoint
        else _weight_loaders.NoOpWeightLoader()
    )
    return _config.TrainConfig(
        name=args.config_name or pathlib.Path(args.data_dir).name,
        exp_name=args.exp_name,
        model=model,
        data=data,
        weight_loader=weight_loader,
        pytorch_weight_path=args.pytorch_weight_path,
        pytorch_training_precision=args.pytorch_precision,
        lr_schedule=_optimizer.CosineDecaySchedule(
            warmup_steps=args.warmup_steps,
            peak_lr=args.peak_lr,
            decay_steps=args.decay_steps,
            decay_lr=args.decay_lr,
        ),
        optimizer=_optimizer.AdamW(weight_decay=args.weight_decay, clip_gradient_norm=args.grad_clip),
        assets_base_dir=args.assets_base_dir,
        checkpoint_base_dir=args.checkpoint_base_dir,
        seed=args.seed,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        num_train_steps=args.num_train_steps,
        log_interval=args.log_interval,
        save_interval=args.save_interval,
        overwrite=args.overwrite,
        resume=args.resume,
        wandb_enabled=args.wandb_enabled,
        fsdp_devices=args.fsdp_devices,
        # LoRA: freeze the base params (only lora adapters are trainable) and disable EMA.
        # get_freeze_filter() returns nnx.Nothing when no lora variant is set, so this is a no-op for full finetuning.
        freeze_filter=model.get_freeze_filter(),
        ema_decay=None if args.lora else 0.99,
    )


def install_norm_stats(config: _config.TrainConfig, norm_stats) -> pathlib.Path:
    """Copy the user-provided norm_stats file/dir to where data.create() reads it from."""
    src = pathlib.Path(norm_stats)
    src_file = src / "norm_stats.json" if src.is_dir() else src
    if not src_file.exists():
        raise FileNotFoundError(f"norm_stats not found at {src_file} (resolved from {norm_stats})")
    dst_dir = config.assets_dirs / pathlib.Path(config.data.data_dir).name
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_file = dst_dir / "norm_stats.json"
    shutil.copyfile(src_file, dst_file)
    return dst_file


def load_script_module(script_filename: str, module_name: str):
    """Load a script from scripts/ under a unique module name (avoids clashes with repo-root files)."""
    path = pathlib.Path(__file__).resolve().parent / "scripts" / script_filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a pi05 policy with the JAX backend (no config.py edit).")
    add_args(parser)
    args = parser.parse_args()

    config = build_config(args)
    install_norm_stats(config, args.norm_stats)

    jax_train = load_script_module("train.py", "_openpi_jax_train")
    jax_train.main(config)


if __name__ == "__main__":
    main()
