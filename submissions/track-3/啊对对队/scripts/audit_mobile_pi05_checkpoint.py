#!/usr/bin/env python3
"""Audit a PI0.5 PEFT checkpoint without loading the base model or GPU."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from parcel_sorter.mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
)
from parcel_sorter.mobile_pi05_training_contract import (
    find_pi05_training_contract,
    validate_pi05_training_contract,
)
from parcel_sorter.pi05_mode_head_adapter import (
    PI05_MODE_HEAD_MODULE,
    pi05_mode_head_pooling_from_protocol,
)
from parcel_sorter.pi05_state_token_adapter import (
    PI05_STATE_TOKEN_MODULE,
    PI05_STATE_TOKEN_PROTOCOL,
)
from parcel_sorter.pi05_action_projection_adapter import (
    PI05_FULL_ACTION_PROJECTION_MODULES,
    PI05_FULL_ACTION_PROJECTION_PROTOCOL,
)


def audit_checkpoint(
    checkpoint: Path,
    *,
    require_state_token: bool = False,
    require_mode_head: bool = False,
    require_contract: bool = False,
    require_full_action_projections: bool = False,
    expected_lora_rank: int | None = None,
    expected_lora_alpha: int | None = None,
    expected_stage_loss_weights: tuple[float, ...] | None = None,
    expected_mode_flow_loss_weights: tuple[float, ...] | None = None,
    expected_mode_flow_loss_population_normalizer: float | None = None,
) -> dict[str, Any]:
    checkpoint = checkpoint.resolve()
    errors: list[str] = []
    required_files = (
        "adapter_config.json",
        "adapter_model.safetensors",
        "config.json",
        "train_config.json",
        "policy_preprocessor.json",
        "policy_postprocessor.json",
        "policy_preprocessor_step_3_normalizer_processor.safetensors",
        "policy_postprocessor_step_0_unnormalizer_processor.safetensors",
    )
    missing = [name for name in required_files if not (checkpoint / name).is_file()]
    errors.extend(f"missing_file:{name}" for name in missing)
    if missing:
        return _payload(checkpoint, errors, {"missing_files": missing})

    adapter = _read_json(checkpoint / "adapter_config.json")
    config = _read_json(checkpoint / "config.json")
    modules_to_save = set(adapter.get("modules_to_save") or ())
    tensor_keys, tensor_shapes = _safetensor_inventory(
        checkpoint / "adapter_model.safetensors"
    )
    audited_modules = (
        PI05_STATE_TOKEN_MODULE,
        PI05_MODE_HEAD_MODULE,
        *PI05_FULL_ACTION_PROJECTION_MODULES,
    )
    module_tensor_keys = {
        module: sorted(
            key
            for key in tensor_keys
            if f".{module}." in key and ".lora_" not in key
        )
        for module in audited_modules
    }
    detected = {
        module: module in modules_to_save and bool(module_tensor_keys[module])
        for module in module_tensor_keys
    }
    for module, required in (
        (PI05_STATE_TOKEN_MODULE, require_state_token),
        (PI05_MODE_HEAD_MODULE, require_mode_head),
    ):
        if required and module not in modules_to_save:
            errors.append(f"missing_modules_to_save:{module}")
        if required and not module_tensor_keys[module]:
            errors.append(f"missing_adapter_tensors:{module}")
        if (module in modules_to_save) != bool(module_tensor_keys[module]):
            errors.append(f"module_metadata_tensor_mismatch:{module}")
    for module in PI05_FULL_ACTION_PROJECTION_MODULES:
        if (module in modules_to_save) != bool(module_tensor_keys[module]):
            errors.append(f"module_metadata_tensor_mismatch:{module}")
    full_action_projections_detected = all(
        detected[module] for module in PI05_FULL_ACTION_PROJECTION_MODULES
    )
    if require_full_action_projections and not full_action_projections_detected:
        errors.append("missing_full_action_projections")
    if any(detected[module] for module in PI05_FULL_ACTION_PROJECTION_MODULES) and not (
        full_action_projections_detected
    ):
        errors.append("partial_full_action_projection_checkpoint")

    state_shape = config.get("input_features", {}).get("observation.state", {}).get("shape")
    action_shape = config.get("output_features", {}).get("action", {}).get("shape")
    visual_keys = sorted(
        key
        for key in config.get("input_features", {})
        if key.startswith("observation.images.")
    )
    if state_shape != [len(MOBILE_PI05_STATE_NAMES)]:
        errors.append("state_shape_mismatch")
    expected_action_names = _supported_action_names(
        config.get("action_feature_names")
    )
    if expected_action_names is None:
        errors.append("action_names_mismatch")
    elif action_shape != [len(expected_action_names)]:
        errors.append("action_shape_mismatch")
    normalization = config.get("normalization_mapping", {})
    if normalization.get("STATE") != "QUANTILES":
        errors.append("state_normalization_mismatch")
    if normalization.get("ACTION") != "QUANTILES":
        errors.append("action_normalization_mismatch")
    if config.get("use_relative_actions") is not False:
        errors.append("unexpected_lerobot_relative_action_transform")
    if config.get("type") != "pi05" or config.get("use_peft") is not True:
        errors.append("not_pi05_peft")
    if adapter.get("peft_type") != "LORA":
        errors.append("not_lora")
    _validate_adapter_hyperparameters(
        adapter,
        errors,
        expected_lora_rank=expected_lora_rank,
        expected_lora_alpha=expected_lora_alpha,
    )
    if adapter.get("base_model_name_or_path") != config.get("pretrained_path"):
        errors.append("base_model_path_mismatch")

    contract_path = find_pi05_training_contract(checkpoint)
    contract_sha256 = None
    contract_payload = None
    mode_head_protocol = None
    if contract_path is None:
        if require_contract:
            errors.append("missing_training_contract")
    else:
        try:
            contract_payload = _read_json(contract_path)
            if detected[PI05_MODE_HEAD_MODULE]:
                mode_head_protocol = str(
                    contract_payload.get("mode_head_protocol") or ""
                )
                pi05_mode_head_pooling_from_protocol(mode_head_protocol)
            contract_sha256 = validate_pi05_training_contract(
                contract_payload,
                state_dim=int(state_shape[0]) if state_shape else -1,
                action_dim=int(action_shape[0]) if action_shape else -1,
                chunk_size=int(config.get("chunk_size", -1)),
                required_state_token_protocol=(
                    PI05_STATE_TOKEN_PROTOCOL
                    if detected[PI05_STATE_TOKEN_MODULE]
                    else None
                ),
                required_mode_head_protocol=(
                    mode_head_protocol if detected[PI05_MODE_HEAD_MODULE] else None
                ),
                required_action_projection_protocol=(
                    PI05_FULL_ACTION_PROJECTION_PROTOCOL
                    if full_action_projections_detected
                    else None
                ),
                required_stage_loss_weights=expected_stage_loss_weights,
                required_mode_flow_loss_weights=expected_mode_flow_loss_weights,
                required_mode_flow_loss_population_normalizer=(
                    expected_mode_flow_loss_population_normalizer
                ),
                required_visual_keys=visual_keys,
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"invalid_training_contract:{exc}")

    metrics = {
        "base_model": adapter.get("base_model_name_or_path"),
        "base_revision": config.get("pretrained_revision"),
        "lora_rank": adapter.get("r"),
        "lora_alpha": adapter.get("lora_alpha"),
        "adapter_tensor_count": len(tensor_keys),
        "adapter_parameter_count": sum(
            _shape_elements(shape) for shape in tensor_shapes.values()
        ),
        "adapter_sha256": _sha256(checkpoint / "adapter_model.safetensors"),
        "state_dimension": state_shape,
        "action_dimension": action_shape,
        "policy_visual_keys": visual_keys,
        "chunk_size": config.get("chunk_size"),
        "n_action_steps": config.get("n_action_steps"),
        "normalization_mapping": normalization,
        "modules_to_save": sorted(modules_to_save),
        "module_tensor_counts": {
            module: len(keys) for module, keys in module_tensor_keys.items()
        },
        "state_token_detected": detected[PI05_STATE_TOKEN_MODULE],
        "mode_head_detected": detected[PI05_MODE_HEAD_MODULE],
        "full_action_projections_detected": full_action_projections_detected,
        "state_token_protocol": (
            PI05_STATE_TOKEN_PROTOCOL if detected[PI05_STATE_TOKEN_MODULE] else None
        ),
        "mode_head_protocol": (
            mode_head_protocol if detected[PI05_MODE_HEAD_MODULE] else None
        ),
        "action_projection_protocol": (
            PI05_FULL_ACTION_PROJECTION_PROTOCOL
            if full_action_projections_detected
            else None
        ),
        "mode_head_class_weights": (
            contract_payload.get("mode_head_class_weights")
            if contract_payload is not None
            else None
        ),
        "stage_loss_weights": (
            contract_payload.get("stage_loss_weights")
            if contract_payload is not None
            else None
        ),
        "stage_loss_weighting_scope": (
            contract_payload.get("stage_loss_weighting_scope")
            if contract_payload is not None
            else None
        ),
        "mode_flow_loss_weights": (
            contract_payload.get("mode_flow_loss_weights")
            if contract_payload is not None
            else None
        ),
        "mode_flow_loss_population_normalizer": (
            contract_payload.get("mode_flow_loss_population_normalizer")
            if contract_payload is not None
            else None
        ),
        "mode_flow_loss_weighting_scope": (
            contract_payload.get("mode_flow_loss_weighting_scope")
            if contract_payload is not None
            else None
        ),
        "training_contract": str(contract_path) if contract_path else None,
        "training_contract_sha256": contract_sha256,
    }
    return _payload(checkpoint, errors, metrics)


def _validate_adapter_hyperparameters(
    adapter: dict[str, Any],
    errors: list[str],
    *,
    expected_lora_rank: int | None,
    expected_lora_alpha: int | None,
) -> None:
    if expected_lora_rank is not None and adapter.get("r") != expected_lora_rank:
        errors.append("lora_rank_mismatch")
    if expected_lora_alpha is not None and adapter.get("lora_alpha") != expected_lora_alpha:
        errors.append("lora_alpha_mismatch")


def _supported_action_names(value: Any) -> tuple[str, ...] | None:
    """Resolve either audited PI0.5 action contract from saved feature names."""

    configured = tuple(value or ())
    for names in (
        MOBILE_PI05_RESIDUAL_ACTION_NAMES,
        MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    ):
        if configured == tuple(names):
            return tuple(names)
    return None


def _safetensor_inventory(path: Path) -> tuple[list[str], dict[str, tuple[int, ...]]]:
    from safetensors import safe_open

    with safe_open(path, framework="pt", device="cpu") as handle:
        keys = list(handle.keys())
        shapes = {key: tuple(handle.get_slice(key).get_shape()) for key in keys}
    return keys, shapes


def _shape_elements(shape: tuple[int, ...]) -> int:
    result = 1
    for value in shape:
        result *= int(value)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload(checkpoint: Path, errors: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol": "pi05-peft-checkpoint-audit-v1",
        "checkpoint": str(checkpoint),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "error_count": len(errors),
        "metrics": metrics,
        "claim_boundary": (
            "Static checkpoint integrity and contract audit only; this does not "
            "measure VLA routing or closed-loop success."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-state-token", action="store_true")
    parser.add_argument("--require-mode-head", action="store_true")
    parser.add_argument("--require-contract", action="store_true")
    parser.add_argument("--require-full-action-projections", action="store_true")
    parser.add_argument("--expected-lora-rank", type=int)
    parser.add_argument("--expected-lora-alpha", type=int)
    parser.add_argument(
        "--expected-stage-loss-weights",
        help="Comma-separated pregrasp, approach, lift, transport, place, release weights.",
    )
    parser.add_argument(
        "--expected-mode-flow-loss-weights",
        help="Comma-separated top, side, and cooperative-cradle flow weights.",
    )
    parser.add_argument("--expected-mode-flow-loss-population-normalizer", type=float)
    args = parser.parse_args()
    expected_stage_loss_weights = (
        tuple(float(value) for value in args.expected_stage_loss_weights.split(","))
        if args.expected_stage_loss_weights
        else None
    )
    expected_mode_flow_loss_weights = (
        tuple(float(value) for value in args.expected_mode_flow_loss_weights.split(","))
        if args.expected_mode_flow_loss_weights
        else None
    )
    payload = audit_checkpoint(
        args.checkpoint,
        require_state_token=args.require_state_token,
        require_mode_head=args.require_mode_head,
        require_contract=args.require_contract,
        require_full_action_projections=args.require_full_action_projections,
        expected_lora_rank=args.expected_lora_rank,
        expected_lora_alpha=args.expected_lora_alpha,
        expected_stage_loss_weights=expected_stage_loss_weights,
        expected_mode_flow_loss_weights=expected_mode_flow_loss_weights,
        expected_mode_flow_loss_population_normalizer=(
            args.expected_mode_flow_loss_population_normalizer
        ),
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
