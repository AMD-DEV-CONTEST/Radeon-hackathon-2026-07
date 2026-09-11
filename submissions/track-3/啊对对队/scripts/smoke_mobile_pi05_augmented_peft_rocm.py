#!/usr/bin/env python3
"""Round-trip an augmented PI0.5 PEFT checkpoint through a real base model."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from parcel_sorter.mobile_pi05_contract import MOBILE_PI05_STATE_NAMES
from parcel_sorter.mobile_pi05_training_contract import (
    PI05_TRAINING_CONTRACT_FILENAME,
    find_pi05_training_contract,
    with_pi05_architecture_protocols,
)
from parcel_sorter.pi05_mode_head_adapter import (
    PI05_MODE_HEAD_MODULE,
    PI05_MODE_HEAD_POOLING_MASKED_MEAN,
    install_pi05_mode_head_adapter,
    normalize_pi05_mode_head_pooling,
    pi05_mode_head_protocol,
    pi05_mode_head_logits,
)
from parcel_sorter.pi05_state_token_adapter import (
    PI05_STATE_TOKEN_MODULE,
    PI05_STATE_TOKEN_PROTOCOL,
    install_pi05_state_token_adapter,
    pi05_state_token_context,
    prepare_pi05_state_token_input,
)
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_MODULES,
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
    install_pi05_full_action_projection_adapter,
)


COPIED_CHECKPOINT_ARTIFACTS = (
    "train_config.json",
    "policy_preprocessor.json",
    "policy_postprocessor.json",
    "policy_preprocessor_step_3_normalizer_processor.safetensors",
    "policy_postprocessor_step_0_unnormalizer_processor.safetensors",
)


def _unwrap_policy(policy: Any) -> Any:
    candidate = policy
    get_base_model = getattr(candidate, "get_base_model", None)
    if callable(get_base_model):
        candidate = get_base_model()
    if not hasattr(candidate, "model") or not hasattr(candidate, "_preprocess_images"):
        raise RuntimeError("unable to unwrap PI0.5 policy")
    return candidate


def _fixed_batch(policy: Any, *, device: str) -> dict[str, Any]:
    import torch
    from lerobot.policies.pi05.modeling_pi05 import (
        OBS_LANGUAGE_ATTENTION_MASK,
        OBS_LANGUAGE_TOKENS,
    )

    height, width = (int(value) for value in policy.config.image_resolution)
    image_key = next(iter(policy.config.image_features))
    state = torch.linspace(
        -0.75,
        0.75,
        len(MOBILE_PI05_STATE_NAMES),
        device=device,
        dtype=torch.float32,
    ).unsqueeze(0)
    return {
        image_key: torch.linspace(
            0.0,
            1.0,
            3 * height * width,
            device=device,
            dtype=torch.float32,
        ).reshape(1, 3, height, width),
        OBS_LANGUAGE_TOKENS: torch.tensor(
            [[2, 17, 31, 43, 59, 71, 83, 97]],
            device=device,
            dtype=torch.long,
        ),
        OBS_LANGUAGE_ATTENTION_MASK: torch.ones(
            (1, 8), device=device, dtype=torch.bool
        ),
        "observation.state": state,
    }


def _fixed_outputs(
    policy: Any,
    batch: dict[str, Any],
    noise: Any,
    *,
    num_steps: int,
) -> dict[str, Any]:
    import torch
    from lerobot.policies.pi05.modeling_pi05 import (
        OBS_LANGUAGE_ATTENTION_MASK,
        OBS_LANGUAGE_TOKENS,
    )
    from parcel_sorter.pi05_weighted_loss import pi05_flow_velocity

    base = _unwrap_policy(policy)
    images, image_masks = base._preprocess_images(batch)
    tokens = batch[OBS_LANGUAGE_TOKENS]
    masks = batch[OBS_LANGUAGE_ATTENTION_MASK]
    state = batch["observation.state"]
    with torch.inference_mode():
        mode_logits = pi05_mode_head_logits(
            base.model, images, image_masks, tokens, masks, state
        )
        _, joint_mode_logits = pi05_flow_velocity(
            base.model,
            images,
            image_masks,
            tokens,
            masks,
            noise,
            torch.ones((noise.shape[0],), device=noise.device),
            state,
            return_mode_head_logits=True,
        )
        with pi05_state_token_context(base.model, state):
            actions = base.model.sample_actions(
                images,
                image_masks,
                tokens,
                masks,
                noise=noise,
                num_steps=num_steps,
            )
        prepared = prepare_pi05_state_token_input(
            state, max_state_dim=int(base.model.config.max_state_dim)
        )
        state_embedding = base.model.state_proj(
            prepared.to(
                device=base.model.state_proj.weight.device,
                dtype=base.model.state_proj.weight.dtype,
            )
        )
    return {
        "mode_logits": mode_logits.float().cpu(),
        "joint_mode_logits": joint_mode_logits.float().cpu(),
        "actions": actions.float().cpu(),
        "state_embedding": state_embedding.float().cpu(),
    }


def _seed_augmented_modules(policy: Any, *, full_action_projections: bool) -> None:
    """Give both fully saved modules non-trivial deterministic parameters."""

    import torch

    state_proj = policy.model.state_proj
    mode_head = policy.model.mode_head
    with torch.no_grad():
        state_proj.weight.zero_()
        state_proj.bias.zero_()
        state_proj.weight[:4, :4] = torch.tensor(
            [
                [0.010, 0.020, 0.030, 0.040],
                [-0.015, 0.025, -0.035, 0.045],
                [0.050, -0.040, 0.030, -0.020],
                [-0.012, -0.024, 0.036, 0.048],
            ],
            device=state_proj.weight.device,
            dtype=state_proj.weight.dtype,
        )
        mode_head[-1].bias.copy_(
            torch.tensor(
                [0.125, -0.250, 0.375],
                device=mode_head[-1].bias.device,
                dtype=mode_head[-1].bias.dtype,
            )
        )
        if full_action_projections:
            policy.model.action_in_proj.weight[0, 0].add_(0.03125)
            policy.model.action_out_proj.weight[0, 0].sub_(0.015625)


def _copy_runtime_artifacts(
    template: Path,
    output: Path,
    *,
    mode_head_protocol: str,
    action_projection_protocol: str | None,
) -> list[str]:
    copied: list[str] = []
    for name in COPIED_CHECKPOINT_ARTIFACTS:
        source = template / name
        if source.is_file():
            shutil.copy2(source, output / name)
            copied.append(name)
    contract = find_pi05_training_contract(template)
    if contract is None:
        raise RuntimeError("template checkpoint is missing PI05_TRAINING_CONTRACT.json")
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload = with_pi05_architecture_protocols(
        payload,
        state_token_protocol=PI05_STATE_TOKEN_PROTOCOL,
        mode_head_protocol=mode_head_protocol,
        action_projection_protocol=action_projection_protocol,
    )
    (output / PI05_TRAINING_CONTRACT_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    copied.append(PI05_TRAINING_CONTRACT_FILENAME)
    return copied


def _max_abs_difference(left: Any, right: Any) -> float:
    return float((left - right).abs().max().item())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=32)
    parser.add_argument("--num-steps", type=int, default=2)
    parser.add_argument("--atol", type=float, default=1e-5)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--full-action-projections", action="store_true")
    parser.add_argument(
        "--mode-head-pooling", default=PI05_MODE_HEAD_POOLING_MASKED_MEAN
    )
    args = parser.parse_args()
    mode_head_pooling = normalize_pi05_mode_head_pooling(args.mode_head_pooling)
    mode_head_protocol = pi05_mode_head_protocol(mode_head_pooling)

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RuntimeError("output directory must be absent or empty")
    if args.rank <= 0 or args.alpha <= 0 or args.num_steps <= 0:
        raise ValueError("rank, alpha, and num-steps must be positive")

    import torch
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.factory import get_policy_class
    from peft import PeftConfig, PeftModel

    torch.manual_seed(args.seed)
    measure_cuda_memory = args.device.startswith("cuda") and torch.cuda.is_available()
    if measure_cuda_memory:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    template = args.template_checkpoint.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = PreTrainedConfig.from_pretrained(template, local_files_only=True)
    if config.type != "pi05" or not config.use_peft:
        raise RuntimeError("template must be a PI0.5 PEFT checkpoint")
    template_peft = PeftConfig.from_pretrained(template)
    base_checkpoint = str(template_peft.base_model_name_or_path or "")
    if not base_checkpoint:
        raise RuntimeError("template PEFT checkpoint does not identify its base")

    if args.full_action_projections:
        install_pi05_full_action_projection_adapter()
    install_pi05_state_token_adapter()
    install_pi05_mode_head_adapter(pooling=mode_head_pooling)
    config.device = args.device
    policy_class = get_policy_class(config.type)
    base_policy = policy_class.from_pretrained(
        base_checkpoint,
        config=config,
        local_files_only=True,
    ).to(args.device)
    _seed_augmented_modules(
        base_policy, full_action_projections=args.full_action_projections
    )
    policy = base_policy.wrap_with_peft(
        peft_cli_overrides={
            "method_type": "LORA",
            "r": args.rank,
            "lora_alpha": args.alpha,
            "lora_dropout": 0.0,
        }
    ).eval()

    active_peft = policy.peft_config["default"]
    modules_to_save = set(active_peft.modules_to_save or ())
    required_modules = {PI05_STATE_TOKEN_MODULE, PI05_MODE_HEAD_MODULE}
    if args.full_action_projections:
        required_modules.update(PI05_FULL_ACTION_PROJECTION_MODULES)
    if not required_modules <= modules_to_save:
        raise RuntimeError(
            f"augmented modules missing from PEFT config: {required_modules - modules_to_save}"
        )

    fixed_batch = _fixed_batch(_unwrap_policy(policy), device=args.device)
    max_action_dim = int(_unwrap_policy(policy).model.config.max_action_dim)
    chunk_size = int(_unwrap_policy(policy).model.config.chunk_size)
    generator = torch.Generator(device=args.device).manual_seed(args.seed + 1)
    noise = torch.randn(
        (1, chunk_size, max_action_dim),
        generator=generator,
        device=args.device,
        dtype=torch.float32,
    )
    before = _fixed_outputs(
        policy, fixed_batch, noise, num_steps=args.num_steps
    )

    policy.save_pretrained(output)
    config.save_pretrained(output)
    copied = _copy_runtime_artifacts(
        template,
        output,
        mode_head_protocol=mode_head_protocol,
        action_projection_protocol=(
            PI05_FULL_ACTION_PROJECTION_PROTOCOL
            if args.full_action_projections
            else None
        ),
    )
    del policy, base_policy
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    reload_config = PreTrainedConfig.from_pretrained(output, local_files_only=True)
    reload_config.device = args.device
    reload_peft = PeftConfig.from_pretrained(output)
    reload_base = policy_class.from_pretrained(
        reload_peft.base_model_name_or_path,
        config=reload_config,
        local_files_only=True,
    ).to(args.device)
    reloaded = PeftModel.from_pretrained(
        reload_base,
        output,
        config=reload_peft,
        is_trainable=False,
    ).eval()
    after = _fixed_outputs(
        reloaded, fixed_batch, noise, num_steps=args.num_steps
    )

    memory_metrics: dict[str, float | str | None] = {
        "device_name": None,
        "total_memory_gb": None,
        "peak_allocated_gb": None,
        "peak_reserved_gb": None,
    }
    if measure_cuda_memory:
        gib = float(1024**3)
        properties = torch.cuda.get_device_properties(torch.cuda.current_device())
        memory_metrics = {
            "device_name": properties.name,
            "total_memory_gb": float(properties.total_memory / gib),
            "peak_allocated_gb": float(torch.cuda.max_memory_allocated() / gib),
            "peak_reserved_gb": float(torch.cuda.max_memory_reserved() / gib),
        }

    differences = {
        name: _max_abs_difference(before[name], after[name]) for name in before
    }
    mode_path_differences = {
        "before_save": _max_abs_difference(
            before["mode_logits"], before["joint_mode_logits"]
        ),
        "after_reload": _max_abs_difference(
            after["mode_logits"], after["joint_mode_logits"]
        ),
    }
    status = (
        "passed"
        if all(value <= args.atol for value in differences.values())
        and all(value <= args.atol for value in mode_path_differences.values())
        else "failed"
    )
    report = {
        "schema_version": 1,
        "protocol": "pi05-augmented-peft-roundtrip-v1",
        "status": status,
        "template_checkpoint": str(template),
        "base_checkpoint": str(reload_peft.base_model_name_or_path),
        "output_checkpoint": str(output),
        "device": args.device,
        "seed": args.seed,
        "rank": args.rank,
        "alpha": args.alpha,
        "diffusion_steps": args.num_steps,
        "absolute_tolerance": args.atol,
        "modules_to_save": sorted(reload_peft.modules_to_save or ()),
        "full_action_projections": args.full_action_projections,
        "action_projection_protocol": (
            PI05_FULL_ACTION_PROJECTION_PROTOCOL
            if args.full_action_projections
            else None
        ),
        "state_token_protocol": PI05_STATE_TOKEN_PROTOCOL,
        "mode_head_protocol": mode_head_protocol,
        "mode_head_pooling": mode_head_pooling,
        "max_abs_differences": differences,
        "training_inference_mode_path_max_abs_differences": mode_path_differences,
        "copied_runtime_artifacts": copied,
        "output_shapes": {name: list(value.shape) for name, value in after.items()},
        "memory_metrics": memory_metrics,
        "claim_boundary": (
            "This verifies augmented PI0.5 PEFT construction and deterministic "
            "save/reload equivalence and inference memory only; it is not a full "
            "training-memory benchmark, routing evidence, or closed-loop evidence."
        ),
    }
    report_path = output / "PI05_AUGMENTED_PEFT_SMOKE.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
