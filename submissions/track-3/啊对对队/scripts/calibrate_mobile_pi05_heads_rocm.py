#!/usr/bin/env python3
"""Calibrate PI0.5 decision heads on frozen observable prefix features.

The expensive PI0.5 visual-language trunk is evaluated once per selected frame.
Only checkpoint-resident direct-action and structured-decision heads are updated;
the base model, LoRA trunk, dataset, sampler cells, seeds, and action thresholds
remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence


ACTION_WEIGHTS = (8, 8, 8, *([1] * 17), 32)
HEAD_MODULE_NAMES = (
    "direct_action_head",
    "direct_action_state_residual",
    "mode_head",
    "mode_head_state_residual",
)
MODE_ONLY_MODULE_NAMES = (
    "mode_head",
    "mode_head_state_residual",
)
CALIBRATION_SCOPES = {
    "all_heads": HEAD_MODULE_NAMES,
    "mode_only": MODE_ONLY_MODULE_NAMES,
}
DIRECT_ACTION_PROTOCOL_PROMOTION = "parcel-pi05-direct-action-v3-to-v4-promotion-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def promote_v3_checkpoint_to_linear_v4(source: Path, output: Path) -> dict[str, Any]:
    """Copy a compatible V3 checkpoint and bind V4 semantics without mutation."""

    from parcel_sorter.pi05_direct_action_head_adapter import (
        PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3,
        PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4,
        PI05_DIRECT_ACTION_STATE_RESIDUAL_MODULE,
    )
    from parcel_sorter.pi05_mode_head_adapter import (
        PI05_MODE_HEAD_STATE_RESIDUAL_MODULE,
        PI05_STRUCTURED_DECISION_HEAD_STATE_RESIDUAL_PROTOCOL,
    )
    from parcel_sorter.mobile_pi05_training_contract import _payload_sha256
    from parcel_sorter.pi05_weighted_loss import pi05_direct_action_target_protocol

    source = source.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"protocol-promotion output already exists: {output}")
    contract_path = source / "PI05_TRAINING_CONTRACT.json"
    adapter_path = source / "adapter_config.json"
    contract = _load_json(contract_path)
    adapter = _load_json(adapter_path)
    if contract.get("direct_action_head_protocol") != PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3:
        raise ValueError("direct-action protocol promotion requires a V3 source checkpoint")
    if (
        contract.get("mode_head_protocol")
        != PI05_STRUCTURED_DECISION_HEAD_STATE_RESIDUAL_PROTOCOL
    ):
        raise ValueError("direct-action protocol promotion requires the paired state residual")
    saved_modules = set(adapter.get("modules_to_save") or ())
    required_modules = {
        PI05_DIRECT_ACTION_STATE_RESIDUAL_MODULE,
        PI05_MODE_HEAD_STATE_RESIDUAL_MODULE,
    }
    if not required_modules.issubset(saved_modules):
        raise ValueError("direct-action protocol promotion source lacks residual modules")

    provenance = {
        "protocol": DIRECT_ACTION_PROTOCOL_PROMOTION,
        "source_checkpoint": str(source),
        "source_training_contract_sha256": _sha256(contract_path),
        "source_adapter_sha256": _sha256(source / "adapter_model.safetensors"),
        "source_direct_action_head_protocol": PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3,
        "promoted_direct_action_head_protocol": PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4,
    }
    shutil.copytree(source, output)
    promoted = dict(contract)
    promoted["direct_action_head_protocol"] = PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4
    promoted["direct_action_target_protocol"] = pi05_direct_action_target_protocol(
        PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4
    )
    promoted["direct_action_protocol_promotion"] = provenance
    promoted.pop("contract_sha256", None)
    promoted["contract_sha256"] = _payload_sha256(promoted)
    (output / "PI05_TRAINING_CONTRACT.json").write_text(
        json.dumps(promoted, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return provenance


def prepare_calibration_direct_action_target(
    action: Any, *, direct_action_head_protocol: str
) -> Any:
    """Apply the same protocol-specific target transform as direct-head training."""

    from parcel_sorter.pi05_weighted_loss import (
        prepare_pi05_direct_action_head_target,
    )

    return prepare_pi05_direct_action_head_target(
        action,
        direct_action_head_protocol=direct_action_head_protocol,
    )


def create_protocol_promotion_temp_directory(output: Path) -> tempfile.TemporaryDirectory:
    """Create promotion scratch space beside, but not at, the final output path."""

    parent = output.resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="pi05-direct-v4-", dir=parent)


def select_competition_indices(
    manifest: Mapping[str, Any], *, samples_per_cell: int
) -> list[int]:
    if manifest.get("protocol") != "parcel-competition-mode-stage-progress-sampler-v1":
        raise ValueError("head calibration requires the frozen competition sampler")
    pools = manifest.get("indices_by_cell")
    if not isinstance(pools, Mapping) or len(pools) != 60:
        raise ValueError("competition sampler must contain 60 mode-stage-progress cells")
    if samples_per_cell < 1:
        raise ValueError("samples_per_cell must be positive")
    selected: list[int] = []
    for cell in sorted(pools):
        values = pools[cell]
        if not isinstance(values, list) or len(values) < samples_per_cell:
            raise ValueError(f"sampler cell is underfilled: {cell}")
        selected.extend(int(value) for value in values[:samples_per_cell])
    if len(selected) != len(set(selected)):
        raise ValueError("selected calibration frames are not unique")
    return selected


def _unwrap_policy(policy: Any) -> Any:
    candidate = policy
    get_base_model = getattr(candidate, "get_base_model", None)
    if callable(get_base_model):
        candidate = get_base_model()
    if not hasattr(candidate, "_preprocess_images") or not hasattr(candidate, "model"):
        raise RuntimeError("unable to unwrap PI0.5 policy")
    return candidate


def _pooled_prefix(policy: Any, batch: Mapping[str, Any]) -> Any:
    import torch
    from lerobot.policies.pi05.modeling_pi05 import (
        OBS_LANGUAGE_ATTENTION_MASK,
        OBS_LANGUAGE_TOKENS,
        make_att_2d_masks,
        prepare_attention_masks_4d,
    )
    from parcel_sorter.pi05_mode_head_adapter import (
        PI05_MODE_HEAD_POOLING_STATE_TOKEN,
        pool_pi05_contextualized_prefix,
    )
    from parcel_sorter.pi05_state_token_adapter import pi05_state_token_context

    base = _unwrap_policy(policy)
    state = batch["observation.state"]
    images, image_masks = base._preprocess_images(batch)
    tokens = batch[OBS_LANGUAGE_TOKENS]
    masks = batch[OBS_LANGUAGE_ATTENTION_MASK]
    with pi05_state_token_context(base.model, state):
        prefix, pad_masks, att_masks = base.model.embed_prefix(
            images, image_masks, tokens, masks
        )
    attention_dtype = (
        base.model.paligemma_with_expert.paligemma.model.language_model.layers[0]
        .self_attn.q_proj.weight.dtype
    )
    if attention_dtype == torch.bfloat16:
        prefix = prefix.to(dtype=attention_dtype)
    attention_2d = make_att_2d_masks(pad_masks, att_masks)
    positions = torch.cumsum(pad_masks, dim=1) - 1
    attention_4d = prepare_attention_masks_4d(attention_2d)
    base.model.paligemma_with_expert.paligemma.model.language_model.config._attn_implementation = (
        "eager"
    )
    (contextualized, _), _ = base.model.paligemma_with_expert.forward(
        attention_mask=attention_4d,
        position_ids=positions,
        past_key_values=None,
        inputs_embeds=[prefix, None],
        use_cache=False,
    )
    if contextualized is None:
        raise RuntimeError("PI0.5 did not return contextualized prefix features")
    return pool_pi05_contextualized_prefix(
        contextualized,
        pad_masks,
        masks,
        state_token_present=True,
        pooling=PI05_MODE_HEAD_POOLING_STATE_TOKEN,
    )


def _collate_frames(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from torch.utils.data._utils.collate import default_collate

    return default_collate(list(frames))


def _extract_features(
    *,
    controller: Any,
    dataset: Any,
    indices: Sequence[int],
    batch_size: int,
    direct_action_head_protocol: str,
    task_overrides: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    import torch

    pooled_rows = []
    state_rows = []
    target_rows = []
    raw_action_rows = []
    for start in range(0, len(indices), batch_size):
        batch_indices = indices[start : start + batch_size]
        frames = [dict(dataset[index]) for index in batch_indices]
        if task_overrides is not None:
            for index, frame in zip(batch_indices, frames, strict=True):
                frame["task"] = task_overrides[index]
        raw_action = torch.stack(
            [frame["action"].float() for frame in frames], dim=0
        )
        batch = _collate_frames(frames)
        processed = controller._preprocessor(batch)
        with torch.inference_mode():
            pooled = _pooled_prefix(controller._policy, processed)
        action = processed["action"]
        if action.ndim == 3:
            action = action[:, 0]
        if action.shape != (len(frames), 21):
            raise RuntimeError(f"unexpected normalized action shape: {tuple(action.shape)}")
        pooled_rows.append(pooled.detach().float().cpu())
        state_rows.append(processed["observation.state"].detach().float().cpu())
        target_rows.append(
            prepare_calibration_direct_action_target(
                action.detach().float(),
                direct_action_head_protocol=direct_action_head_protocol,
            ).cpu()
        )
        raw_action_rows.append(raw_action.cpu())
    return {
        "pooled": torch.cat(pooled_rows, dim=0),
        "state": torch.cat(state_rows, dim=0),
        "target": torch.cat(target_rows, dim=0),
        "raw_action": torch.cat(raw_action_rows, dim=0),
    }


def _panel_task_overrides(
    *, panel: Mapping[str, Any], dataset: Any, task_language_policy: str
) -> tuple[list[int], dict[int, str]]:
    from parcel_sorter.mobile_vla_controller import select_vla_policy_task

    observations = panel.get("observations")
    if not isinstance(observations, list) or len(observations) != 12:
        raise ValueError("frozen contract panel must contain 12 observations")
    indices: list[int] = []
    overrides: dict[int, str] = {}
    for item in observations:
        index = int(item["dataset_index"])
        stage = str(item["stage"])
        task = str(dataset[index]["task"])
        indices.append(index)
        overrides[index] = select_vla_policy_task(
            task,
            stage,
            uses_progress_channel=True,
            uses_residual_contract=True,
            task_language_policy=task_language_policy,
        )
    if len(indices) != len(set(indices)):
        raise ValueError("frozen panel contains duplicate dataset indices")
    return indices, overrides


def _enable_saved_heads(
    policy: Any, *, module_names: Sequence[str] = HEAD_MODULE_NAMES
) -> list[tuple[str, Any]]:
    requested = tuple(module_names)
    if not requested or any(module not in HEAD_MODULE_NAMES for module in requested):
        raise ValueError("invalid saved-head calibration module selection")
    for parameter in policy.parameters():
        parameter.requires_grad_(False)
    trainable: list[tuple[str, Any]] = []
    for name, parameter in policy.named_parameters():
        if (
            "modules_to_save.default" in name
            and any(module in name for module in requested)
        ):
            parameter.requires_grad_(True)
            trainable.append((name, parameter))
    found = {module: False for module in requested}
    for name, _ in trainable:
        for module in found:
            found[module] = found[module] or module in name
    if not all(found.values()):
        raise RuntimeError(f"checkpoint lacks trainable saved head modules: {found}")
    return trainable


def _head_metrics(
    model: Any,
    data: Mapping[str, Any],
    *,
    device: str,
    action_weights: Sequence[float] = ACTION_WEIGHTS,
) -> dict[str, float]:
    import torch
    import torch.nn.functional as F
    from parcel_sorter.pi05_direct_action_head_adapter import (
        apply_pi05_direct_action_head,
    )
    from parcel_sorter.pi05_mode_head_adapter import apply_pi05_mode_head

    with torch.inference_mode():
        pooled = data["pooled"].to(device)
        state = data["state"].to(device)
        target = data["target"].to(device)
        raw = data["raw_action"].to(device)
        direct = apply_pi05_direct_action_head(model, pooled, state)
        structured = apply_pi05_mode_head(model, pooled, state)
        weights = torch.tensor(action_weights, device=device, dtype=torch.float32)
        direct_mse = ((direct - target).square() * weights).sum(-1).div(weights.sum())
        mode_target = raw[:, 17:20].argmax(dim=-1)
        tool_target = (raw[:, [9, 16]] > 0.0).float()
        return {
            "direct_weighted_mse": float(direct_mse.mean().item()),
            "progress_mae_normalized": float((direct[:, 20] - target[:, 20]).abs().mean().item()),
            "mode_accuracy": float((structured[:, :3].argmax(-1) == mode_target).float().mean().item()),
            "tool_accuracy": float(((structured[:, 3:5] > 0.0) == tool_target.bool()).float().mean().item()),
            "mode_cross_entropy": float(F.cross_entropy(structured[:, :3], mode_target).item()),
            "tool_binary_cross_entropy": float(F.binary_cross_entropy_with_logits(structured[:, 3:5], tool_target).item()),
        }


def _calibrate(
    *,
    policy: Any,
    train_data: Mapping[str, Any],
    panel_data: Mapping[str, Any],
    epochs: int,
    batch_size: int,
    learning_rate: float,
    panel_repeat: int,
    seed: int,
    device: str,
    action_weights: Sequence[float] = ACTION_WEIGHTS,
    calibration_scope: str = "all_heads",
) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F
    from parcel_sorter.pi05_direct_action_head_adapter import (
        apply_pi05_direct_action_head,
    )
    from parcel_sorter.pi05_mode_head_adapter import apply_pi05_mode_head

    if calibration_scope not in CALIBRATION_SCOPES:
        raise ValueError(f"unsupported calibration scope: {calibration_scope}")
    trainable_modules = CALIBRATION_SCOPES[calibration_scope]
    trainable = _enable_saved_heads(policy, module_names=trainable_modules)
    base = _unwrap_policy(policy)
    model = base.model
    before = _head_metrics(
        model, panel_data, device=device, action_weights=action_weights
    )
    repeats = max(1, int(panel_repeat))
    data = {
        key: torch.cat((train_data[key], panel_data[key].repeat((repeats,) + (1,) * (panel_data[key].ndim - 1))), dim=0)
        for key in train_data
    }
    optimizer = torch.optim.AdamW(
        [parameter for _, parameter in trainable],
        lr=learning_rate,
        weight_decay=1e-4,
    )
    weights = torch.tensor(action_weights, device=device, dtype=torch.float32)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    history = []
    policy.train()
    for epoch in range(epochs):
        order = torch.randperm(data["pooled"].shape[0], generator=generator)
        losses = []
        for start in range(0, order.numel(), batch_size):
            take = order[start : start + batch_size]
            pooled = data["pooled"][take].to(device)
            state = data["state"][take].to(device)
            target = data["target"][take].to(device)
            raw = data["raw_action"][take].to(device)
            optimizer.zero_grad(set_to_none=True)
            direct = apply_pi05_direct_action_head(model, pooled, state)
            structured = apply_pi05_mode_head(model, pooled, state)
            direct_loss = ((direct - target).square() * weights).sum(-1).div(weights.sum()).mean()
            mode_target = raw[:, 17:20].argmax(dim=-1)
            tool_target = (raw[:, [9, 16]] > 0.0).float()
            mode_loss = F.cross_entropy(structured[:, :3], mode_target)
            tool_loss = F.binary_cross_entropy_with_logits(structured[:, 3:5], tool_target)
            direct_weight = 4.0 if calibration_scope == "all_heads" else 0.0
            loss = direct_weight * direct_loss + 12.0 * mode_loss + 12.0 * tool_loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [parameter for _, parameter in trainable], max_norm=10.0
            )
            optimizer.step()
            losses.append(float(loss.detach().item()))
        history.append({"epoch": epoch + 1, "mean_loss": sum(losses) / len(losses)})
    policy.eval()
    after = _head_metrics(
        model, panel_data, device=device, action_weights=action_weights
    )
    return {
        "trainable_parameter_count": sum(p.numel() for _, p in trainable),
        "trainable_parameter_names": [name for name, _ in trainable],
        "calibration_scope": calibration_scope,
        "direct_action_optimization_weight": (
            4.0 if calibration_scope == "all_heads" else 0.0
        ),
        "before_panel_metrics": before,
        "after_panel_metrics": after,
        "history": history,
    }


def _copy_runtime_files(source: Path, output: Path) -> None:
    excluded = {"adapter_model.safetensors", "adapter_model.bin", "adapter_config.json"}
    for path in source.iterdir():
        if path.name in excluded or not path.is_file():
            continue
        shutil.copy2(path, output / path.name)


def bind_calibrated_action_contract(
    checkpoint: Path, *, action_weights: Sequence[float]
) -> dict[str, Any]:
    """Bind the training contract to the loss that produced calibrated heads."""

    from parcel_sorter.mobile_pi05_training_contract import _payload_sha256
    from parcel_sorter.pi05_weighted_loss import pi05_direct_action_target_protocol

    if len(action_weights) != 21 or any(float(value) <= 0.0 for value in action_weights):
        raise ValueError("calibrated action contract requires 21 positive weights")
    contract_path = checkpoint / "PI05_TRAINING_CONTRACT.json"
    contract = _load_json(contract_path)
    protocol = str(contract.get("direct_action_head_protocol") or "")
    contract["action_loss_weights"] = [float(value) for value in action_weights]
    contract["direct_action_target_protocol"] = pi05_direct_action_target_protocol(
        protocol
    )
    contract.pop("contract_sha256", None)
    contract["contract_sha256"] = _payload_sha256(contract)
    contract_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("training_dataset", type=Path)
    parser.add_argument("sampling_manifest", type=Path)
    parser.add_argument("panel_dataset", type=Path)
    parser.add_argument("panel", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--samples-per-cell", type=int, default=10)
    parser.add_argument("--feature-batch-size", type=int, default=4)
    parser.add_argument("--head-batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--panel-repeat", type=int, default=10)
    parser.add_argument("--learning-rate", type=float, default=2.5e-4)
    parser.add_argument(
        "--action-weights",
        default=",".join(str(value) for value in ACTION_WEIGHTS),
        help="comma-separated positive weights for the 21 normalized action dimensions",
    )
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument(
        "--calibration-scope",
        choices=tuple(CALIBRATION_SCOPES),
        default="all_heads",
        help="all_heads updates action and routing heads; mode_only preserves the source direct-action/progress function",
    )
    parser.add_argument(
        "--promote-v3-to-linear-v4",
        action="store_true",
        help="copy and contract-promote a compatible V3 source before calibration",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    if args.seed != 11:
        parser.error("competition head calibration requires seed 11")
    if args.epochs < 1 or args.feature_batch_size < 1 or args.head_batch_size < 1:
        parser.error("batch sizes and epochs must be positive")
    try:
        action_weights = tuple(float(value) for value in args.action_weights.split(","))
    except ValueError:
        parser.error("action weights must be comma-separated numbers")
    if len(action_weights) != 21 or any(value <= 0 for value in action_weights):
        parser.error("action weights must contain 21 positive values")
    random.seed(args.seed)

    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from parcel_sorter.mobile_vla_controller import MobileVLAHarnessController
    from parcel_sorter.pi05_weighted_loss import pi05_direct_action_target_protocol

    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    manifest = _load_json(args.sampling_manifest)
    selected = select_competition_indices(
        manifest, samples_per_cell=args.samples_per_cell
    )
    panel = _load_json(args.panel)
    training_dataset = LeRobotDataset(
        "local/mobile-bimanual-parcel-expert",
        root=args.training_dataset,
        video_backend="pyav",
    )
    panel_dataset = LeRobotDataset(
        "local/mobile-bimanual-parcel-expert",
        root=args.panel_dataset,
        video_backend="pyav",
    )
    if max(selected) >= len(training_dataset):
        raise ValueError("sampling manifest index exceeds training dataset")
    promoted_temp = None
    checkpoint_for_load = args.checkpoint
    promotion = None
    if args.promote_v3_to_linear_v4:
        promoted_temp = create_protocol_promotion_temp_directory(args.output)
        checkpoint_for_load = Path(promoted_temp.name) / "checkpoint"
        promotion = promote_v3_checkpoint_to_linear_v4(
            args.checkpoint, checkpoint_for_load
        )
    controller = MobileVLAHarnessController(checkpoint_for_load, seed=2026080206)
    if not (
        controller.uses_direct_action_head
        and controller.uses_structured_decision_head
        and controller.uses_direct_action_state_residual
        and controller.uses_mode_head_state_residual
    ):
        raise RuntimeError("head calibration requires the complete v11 residual-head protocol")
    train_features = _extract_features(
        controller=controller,
        dataset=training_dataset,
        indices=selected,
        batch_size=args.feature_batch_size,
        direct_action_head_protocol=str(controller.direct_action_head_protocol),
    )
    panel_indices, task_overrides = _panel_task_overrides(
        panel=panel,
        dataset=panel_dataset,
        task_language_policy=str(controller.task_language_policy),
    )
    panel_features = _extract_features(
        controller=controller,
        dataset=panel_dataset,
        indices=panel_indices,
        batch_size=args.feature_batch_size,
        direct_action_head_protocol=str(controller.direct_action_head_protocol),
        task_overrides=task_overrides,
    )
    result = _calibrate(
        policy=controller._policy,
        train_data=train_features,
        panel_data=panel_features,
        epochs=args.epochs,
        batch_size=args.head_batch_size,
        learning_rate=args.learning_rate,
        panel_repeat=args.panel_repeat,
        seed=args.seed,
        device="cuda",
        action_weights=action_weights,
        calibration_scope=args.calibration_scope,
    )
    args.output.mkdir(parents=True)
    _copy_runtime_files(checkpoint_for_load, args.output)
    controller._policy.save_pretrained(args.output, safe_serialization=True)
    bind_calibrated_action_contract(args.output, action_weights=action_weights)
    selected_digest = hashlib.sha256(
        json.dumps(selected, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    contract = {
        "schema_version": 1,
        "protocol": "parcel-pi05-frozen-prefix-head-calibration-v1",
        "status": "completed",
        "source_checkpoint": str(args.checkpoint.resolve()),
        "source_adapter_sha256": _sha256(args.checkpoint / "adapter_model.safetensors"),
        "loaded_checkpoint": str(checkpoint_for_load.resolve()),
        "direct_action_head_protocol": controller.direct_action_head_protocol,
        "direct_action_target_protocol": pi05_direct_action_target_protocol(
            controller.direct_action_head_protocol
        ),
        "direct_action_protocol_promotion": promotion,
        "training_dataset": str(args.training_dataset.resolve()),
        "sampling_manifest": str(args.sampling_manifest.resolve()),
        "sampling_manifest_file_sha256": _sha256(args.sampling_manifest),
        "selected_frame_count": len(selected),
        "selected_indices_sha256": selected_digest,
        "samples_per_cell": args.samples_per_cell,
        "panel_dataset": str(args.panel_dataset.resolve()),
        "panel": str(args.panel.resolve()),
        "panel_file_sha256": _sha256(args.panel),
        "panel_replay_count": len(panel_indices),
        "panel_repeat": args.panel_repeat,
        "seed": args.seed,
        "runtime_seed": 2026080206,
        "epochs": args.epochs,
        "feature_batch_size": args.feature_batch_size,
        "head_batch_size": args.head_batch_size,
        "learning_rate": args.learning_rate,
        "loss_weights": {
            "direct_action_mse": (
                4.0 if args.calibration_scope == "all_heads" else 0.0
            ),
            "mode_cross_entropy": 12.0,
            "tool_binary_cross_entropy": 12.0,
            "action_dimensions": list(action_weights),
        },
        "calibration_scope": args.calibration_scope,
        "frozen_components": (
            "base PI0.5, vision encoder, LoRA trunk, direct-action/progress heads, "
            "dataset, sampler cells, panel, thresholds"
            if args.calibration_scope == "mode_only"
            else "base PI0.5, vision encoder, LoRA trunk, dataset, sampler cells, panel, thresholds"
        ),
        "trainable_components": list(CALIBRATION_SCOPES[args.calibration_scope]),
        "expert_reference_count": 0,
        "expert_fallback_count": 0,
        "result": result,
        "claim_boundary": (
            "Head calibration is offline learned-policy training only. It authorizes "
            "closed loop only after the unchanged checkpoint audit and frozen panel pass."
        ),
    }
    (args.output / "PI05_HEAD_CALIBRATION_CONTRACT.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(contract, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
