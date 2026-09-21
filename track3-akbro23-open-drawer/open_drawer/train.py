"""Fine-tune pi0.5-with-tactile on the recorded demonstrations.

    uv run train
    uv run train --steps=8000 --batch_size=24

A wrapper around `lerobot-train`, not a reimplementation of it. It does three
things the stock entrypoint cannot: register the tactile policy so
`--policy.type=tactile_pi05` resolves, register an 8-bit AdamW so
`--optimizer.type=adamw_8bit` resolves, and fill in the defaults this task needs
so the command is short enough to type correctly. Anything passed on the CLI
wins over a default. Dataloading, checkpointing and resume are all lerobot's.

TWO TRAPS, both load-bearing.

`use_policy_training_preset` defaults to True, and in that mode
`TrainPipelineConfig.validate()` OVERWRITES `cfg.optimizer` with the policy's own
preset. An `--optimizer.type=adamw_8bit` passed alongside it parses fine, is
silently discarded, and training runs in 32-bit AdamW -- no warning, just a lot
of extra memory. So the preset is off here. For pi0.5 that costs nothing else:
`PI05Policy.get_optim_params()` returns `self.parameters()`, exactly what the
non-preset path uses anyway.

CHUNK SIZE IS THE DATA CONTRACT. `chunk_size=16` / `n_action_steps=4` is the
horizon the dataset was recorded for, against pi05_base's own default of 50/50.
At 25 Hz that is 640 ms predicted, 160 ms executed open-loop. It only sets
sequence lengths in the action expert -- no weight is sized by it -- so the
pretrained checkpoint still loads.

Nothing here runs on a dev box: torch, lerobot and bitsandbytes are all
instance-side.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import torch

from lerobot.optim.optimizers import OptimizerConfig, OptimizerParams

from .config import DATASET_REPO_ID, DATASET_ROOT, TRAIN_DIR, EnvConfig


def _for_save(state: dict) -> dict:
    """Optimizer state, rebuilt into something safetensors accepts."""
    seen: set[int] = set()

    def walk(key, value):
        if isinstance(value, dict):
            return {k: walk(k, v) for k, v in value.items()}
        if key == "step" and isinstance(value, int):
            return torch.tensor(value)
        if torch.is_tensor(value):
            ptr = value.untyped_storage().data_ptr()
            if ptr in seen:            # a repeat of storage already written
                return value.clone()
            seen.add(ptr)
        return value

    return {k: walk(k, v) for k, v in state.items()}


def _for_load(state: dict) -> dict:
    """The inverse, for `--resume`. Clones need no undoing."""
    def walk(key, value):
        if isinstance(value, dict):
            return {k: walk(k, v) for k, v in value.items()}
        if key == "step" and torch.is_tensor(value):
            return int(value.item())
        return value

    return {k: walk(k, v) for k, v in state.items()}


@OptimizerConfig.register_subclass("adamw_8bit")
@dataclass
class AdamW8bitConfig(OptimizerConfig):
    """AdamW with 8-bit quantized moment state.

    Adam remembers two running values per parameter, and with
    `policy.dtype=bfloat16` torch allocates them with `zeros_like`, so the
    moments are bf16 too. Quantizing them block-wise to 8 bits halves that,
    which is roughly what decides how much is left for activations.

    Defaults mirror `PI05Config.get_optimizer_preset()`, so switching to 8-bit
    changes the memory footprint and nothing about the hyperparameters.
    bitsandbytes already leaves tensors under `min_8bit_size` (4096 elements)
    in 32-bit, so norms and biases are excluded without being asked -- which
    also covers the freshly-initialized tactile encoder's bias.
    """

    lr: float = 2.5e-5
    betas: tuple[float, float] = (0.9, 0.95)
    eps: float = 1e-8
    weight_decay: float = 0.01
    grad_clip_norm: float = 1.0   # applied by the train loop, not by the optimizer

    def build(self, params: OptimizerParams) -> torch.optim.Optimizer:
        import bitsandbytes as bnb

        class AdamW8bit(bnb.optim.AdamW8bit):
            """Optimizer state that lerobot can actually checkpoint.

            It saves through safetensors, which bitsandbytes' state violates
            twice: `step` is a Python int where torch uses a 0-dim tensor, and
            the quantization maps are one shared tensor referenced from every
            parameter's state, which safetensors rejects as aliased storage.

            Both are fixed at the serialization boundary only -- the kernels
            index `step` as an int, and the maps are meant to be shared in
            memory. Only repeat tensors are cloned: cloning all of them would
            duplicate the moments to save a few KB of lookup table.
            """

            def state_dict(self):
                sd = super().state_dict()
                sd["state"] = _for_save(sd["state"])
                return sd

            def load_state_dict(self, sd, **kw):
                return super().load_state_dict(
                    {**sd, "state": _for_load(sd["state"])}, **kw)

        return AdamW8bit(
            params, lr=self.lr, betas=self.betas, eps=self.eps,
            weight_decay=self.weight_decay)


DEFAULTS = {
    # Where `collect` wrote the dataset and where the checkpoints go. Fixed so
    # the stages chain; lerobot raises rather than overwrite an existing
    # output_dir, so a second run wants --resume=true or a cleared directory.
    "--dataset.repo_id": DATASET_REPO_ID,
    "--dataset.root": DATASET_ROOT,
    # lerobot defaults to torchcodec whenever the package merely imports, but
    # it links against system ffmpeg. pyav carries its own.
    "--dataset.video_backend": "pyav",
    "--output_dir": TRAIN_DIR,
    # Not `--policy.path`: that loads the checkpoint's config too, and its
    # camera names then override the dataset's. This keeps a fresh config and
    # loads only the weights.
    "--policy.type": "tactile_pi05",
    "--policy.pretrained_path": "lerobot/pi05_base",
    "--policy.tactile_dim": str(EnvConfig().tactile.dim),
    # The recorded horizon: 16 predicted, 4 executed, at 25 Hz.
    "--policy.chunk_size": "16",
    "--policy.n_action_steps": "4",
    "--policy.dtype": "bfloat16",
    "--policy.gradient_checkpointing": "true",
    "--policy.push_to_hub": "false",
    # Without this the 8-bit optimizer is silently discarded. See the docstring.
    "--use_policy_training_preset": "false",
    "--optimizer.type": "adamw_8bit",
    # Turning the preset off drops the scheduler with it -- validate() raises
    # unless both are set -- so pi0.5's own schedule is restated verbatim from
    # `PI05Config.get_scheduler_preset()`. The warmup earns its place here
    # twice over: the 9-dim state and action are padded to 32 by freshly
    # initialized projections, and the tactile encoder is new as well, so at
    # full LR their gradients would hit the pretrained VLM on step one.
    #
    # num_decay_steps stays at 30000 rather than tracking --steps, because
    # build() scales BOTH numbers by num_training_steps/num_decay_steps
    # whenever --steps is smaller, keeping warmup a constant 3.3% of the run.
    # Pinning it to --steps would suppress that scaling.
    "--scheduler.type": "cosine_decay_with_warmup",
    "--scheduler.num_warmup_steps": "1000",
    "--scheduler.num_decay_steps": "30000",
    "--scheduler.peak_lr": "2.5e-5",
    "--scheduler.decay_lr": "2.5e-6",
    "--batch_size": "16",
    # ~160k samples, a little under one pass over the dataset, ~10 hours.
    # A checkpoint is ~17 GB and none are pruned, so save_freq trades disk
    # against how much of a failed run has to be repeated.
    "--steps": "10000",
    "--save_freq": "2500",
    "--log_freq": "100",
    "--num_workers": "4",
    # No gym env for this task -- evaluation runs in Genesis, out of band.
    "--env_eval_freq": "0",
    # disable_artifact is not optional: lerobot logs every checkpoint as one,
    # and that is pi0.5's weights plus 8-bit optimizer state, once per save.
    "--wandb.enable": "true",
    "--wandb.project": "open-drawer",
    "--wandb.disable_artifact": "true",
}


def _argv_with_defaults(user: list[str]) -> list[str]:
    """Prepend every default the user did not set. Later flags are theirs."""
    given = {arg.split("=", 1)[0] for arg in user}
    return [f"{k}={v}" for k, v in DEFAULTS.items() if k not in given] + user


def main() -> None:
    from lerobot.scripts.lerobot_train import train

    # Must precede argument parsing: the config subclass registers on import,
    # and the policy class has to be in the factory before --policy.type is
    # resolved.
    from .policy_tactile import register
    register()

    argv = _argv_with_defaults(sys.argv[1:])
    print("lerobot-train " + " ".join(argv) + "\n")
    sys.argv = [sys.argv[0], *argv]
    train()


if __name__ == "__main__":
    main()
