#!/usr/bin/env python3
"""Cache frozen SmolVLA prefix states and aligned H-step Q-VGM transitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from smolvla_qvgm_rlinf.data.chunk_transition import build_chunk_transitions
from smolvla_qvgm_rlinf.data.collected_episode_adapter import load_collected_episode
from smolvla_qvgm_rlinf.data.feature_cache import (
    episode_reference_chunks,
    next_reference_chunks,
    next_aligned_chunks,
    normalization_manifest,
    observation_indices,
    processor_manifest,
    sha256_file,
    sha256_json,
    sha256_tensor,
)
from smolvla_qvgm_rlinf.models.checkpoint import load_smolvla_checkpoint
from smolvla_qvgm_rlinf.models.prefix_features import (
    FrozenSmolVLAPrefixExtractor,
    PrefixFeatureConfig,
    load_rlt_extractor,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pickle-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("checkpoints/smolvla_libero_task0/public_recipe_20k/checkpoint-final/pretrained_model"),
    )
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--feature-dim", type=int, default=512)
    parser.add_argument("--projection-seed", type=int, default=1000)
    parser.add_argument(
        "--rlt-checkpoint",
        type=Path,
        help="Use a trained RLT autoencoder encoder instead of fixed masked-mean projection.",
    )
    parser.add_argument(
        "--prefix-token-dir",
        type=Path,
        help="Reuse prefix token files produced by cache_smolvla_prefix_tokens.py.",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def observation_batch(observations: list[dict], device: str) -> dict:
    def images(key: str) -> torch.Tensor:
        value = torch.stack([torch.as_tensor(obs[key]) for obs in observations])
        if value.shape[-1] == 3:
            value = value.permute(0, 3, 1, 2)
        value = value.contiguous().float()
        return value.div_(255.0) if value.max() > 1 else value

    return {
        "observation.state": torch.stack([torch.as_tensor(obs["states"]) for obs in observations])
        .float()
        .to(device),
        "observation.images.agentview": images("main_images").to(device),
        "observation.images.wrist": images("wrist_images").to(device),
        "task": [obs["task_descriptions"] for obs in observations],
    }


@torch.inference_mode()
def extract_episode_features(
    extractor: torch.nn.Module,
    observations: list[dict],
    *,
    batch_size: int,
    device: str,
) -> torch.Tensor:
    output = []
    dtype = next(extractor.policy.parameters()).dtype
    for start in range(0, len(observations), batch_size):
        batch = observation_batch(observations[start : start + batch_size], device)
        with torch.autocast(device_type="cuda", dtype=dtype, enabled=device.startswith("cuda")):
            output.append(extractor(batch).cpu())
    return torch.cat(output)


@torch.inference_mode()
def encode_cached_rlt_tokens(
    extractor: torch.nn.Module,
    token_payload: dict[str, torch.Tensor],
    *,
    batch_size: int,
    device: str,
) -> torch.Tensor:
    output = []
    parameter = next(extractor.rlt_module.parameters())
    hidden = token_payload["hidden"]
    mask = token_payload["mask"]
    for start in range(0, len(hidden), batch_size):
        prefix = hidden[start : start + batch_size].to(
            device=device, dtype=parameter.dtype
        )
        valid = mask[start : start + batch_size].to(device=device)
        with torch.autocast(
            device_type="cuda", dtype=torch.bfloat16, enabled=device.startswith("cuda")
        ):
            output.append(extractor.rlt_module.encode_flat(prefix, valid).float().cpu())
    return torch.cat(output)


def main() -> None:
    args = parse_args()
    if args.horizon <= 0 or args.batch_size <= 0:
        raise ValueError("horizon and batch size must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.output_dir / "feature_cache.pt"
    manifest_path = args.output_dir / "feature_cache_manifest.json"
    extractor_path = args.output_dir / "feature_extractor.pt"
    existing = [path for path in (cache_path, manifest_path, extractor_path) if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(f"feature cache already exists: {existing}")

    paths = sorted(args.pickle_dir.glob("*.pkl"))
    if not paths:
        raise FileNotFoundError(f"no pickle episodes found in {args.pickle_dir}")
    checkpoint = args.model_path.resolve()
    policy = load_smolvla_checkpoint(checkpoint, device=args.device, dtype=torch.bfloat16)
    if args.rlt_checkpoint is not None:
        extractor = load_rlt_extractor(
            policy, args.rlt_checkpoint.resolve(), device=args.device
        )
    else:
        config = PrefixFeatureConfig(
            output_dim=args.feature_dim, projection_seed=args.projection_seed
        )
        extractor = FrozenSmolVLAPrefixExtractor(policy, config).to(args.device).eval()

    batches: list[dict[str, torch.Tensor]] = []
    episode_records = []
    for path in paths:
        episode = load_collected_episode(path)
        metadata = episode.get("qvgm_metadata", {})
        transitions = build_chunk_transitions(episode, horizon=args.horizon, gamma=args.gamma)
        if args.prefix_token_dir is not None:
            if args.rlt_checkpoint is None:
                raise ValueError("prefix-token-dir requires rlt-checkpoint")
            token_path = args.prefix_token_dir / f"{path.stem}.pt"
            if not token_path.exists():
                raise FileNotFoundError(f"missing cached prefix tokens: {token_path}")
            token_payload = torch.load(token_path, map_location="cpu", weights_only=True)
            if Path(token_payload["source"]).resolve() != path.resolve():
                raise ValueError(f"prefix token source mismatch for {path.name}")
            all_features = encode_cached_rlt_tokens(
                extractor,
                token_payload,
                batch_size=args.batch_size,
                device=args.device,
            )
        else:
            all_features = extract_episode_features(
                extractor,
                episode["observations"],
                batch_size=args.batch_size,
                device=args.device,
            )
        if len(all_features) != len(episode["observations"]):
            raise ValueError(f"feature/observation count mismatch for {path.name}")
        length = len(episode["actions"])
        current_indices, next_indices = observation_indices(length, horizon=args.horizon)
        reference, reference_mask = episode_reference_chunks(episode, horizon=args.horizon)
        next_reference, next_reference_mask = next_reference_chunks(
            reference, reference_mask, horizon=args.horizon
        )
        next_action, next_action_mask = next_aligned_chunks(
            transitions.action_chunk, transitions.action_mask, horizon=args.horizon
        )
        batches.append(
            {
                "z_state": all_features[current_indices],
                "proprio": transitions.proprio,
                "ref_chunk": reference,
                "ref_chunk_mask": reference_mask,
                "action_chunk_executed": transitions.action_chunk,
                "action_mask": transitions.action_mask,
                "reward": transitions.chunk_reward,
                "next_z_state": all_features[next_indices],
                "next_proprio": transitions.next_proprio,
                "next_ref_chunk": next_reference,
                "next_ref_chunk_mask": next_reference_mask,
                "next_action_chunk_executed": next_action,
                "next_action_mask": next_action_mask,
                "done": transitions.done,
                "bootstrap_mask": transitions.bootstrap_mask,
                "discount": transitions.discount,
                "mc_return": transitions.mc_return,
                "task_id": torch.full(
                    (length,), int(metadata.get("task_id", -1)), dtype=torch.int16
                ),
                "reset_state_id": torch.full(
                    (length,),
                    int(
                        metadata.get(
                            "task_reset_state_id", metadata.get("state_id", -1)
                        )
                    ),
                    dtype=torch.int16,
                ),
            }
        )
        perturbation_infos = episode.get("infos", [])
        episode_records.append(
            {
                "file": str(path.resolve()),
                "transitions": length,
                "success": bool(episode["success"]),
                "task_id": metadata.get("task_id"),
                "task_reset_state_id": metadata.get(
                    "task_reset_state_id", metadata.get("state_id")
                ),
                "collection_key": metadata.get("collection_key"),
                "repeat_id": metadata.get("repeat_id"),
                "collection_seed": metadata.get("seed"),
                # Sigma is part of the reusable collection plan, but an episode
                # is still a pure SFT rollout when perturb_probability is zero.
                "planned_perturbation_sigma": metadata.get("sigma"),
                "perturbation_probability": metadata.get("perturb_probability"),
                "perturbed_action_steps": sum(
                    bool(info.get("perturbation_applied", False))
                    for info in perturbation_infos
                ),
            }
        )
        print(f"cached {path.name}: {length} transitions", flush=True)

    cache = {key: torch.cat([batch[key] for batch in batches]) for key in batches[0]}
    if not all(torch.isfinite(value).all() for value in cache.values() if value.is_floating_point()):
        raise RuntimeError("feature cache contains non-finite values")
    torch.save(cache, cache_path)
    if args.rlt_checkpoint is not None:
        source_payload = torch.load(args.rlt_checkpoint, map_location="cpu", weights_only=True)
        extractor_payload = {
            "kind": "rlt_autoencoder",
            "config": source_payload["config"],
            "model": source_payload["model"],
        }
        torch.save(extractor_payload, extractor_path)
        extractor_identity = {
            **extractor.config_dict,
            "checkpoint_sha256": sha256_file(args.rlt_checkpoint),
            "artifact": str(extractor_path.resolve()),
        }
    else:
        torch.save(
            {"kind": "fixed_projection", "config": extractor.config_dict,
             "projection": extractor.projection.detach().cpu()},
            extractor_path,
        )
        extractor_identity = {
            **extractor.config_dict,
            "kind": "fixed_projection",
            "projection_sha256": sha256_tensor(extractor.projection),
            "artifact": str(extractor_path.resolve()),
        }

    checkpoint_assets = {
        name: sha256_file(checkpoint / name) for name in ("config.json", "model.safetensors")
    }
    manifest = {
        "schema_version": 1,
        "checkpoint": {
            "path": str(checkpoint),
            "asset_sha256": checkpoint_assets,
            "combined_sha256": sha256_json(checkpoint_assets),
        },
        "processor": processor_manifest(policy),
        "normalization": normalization_manifest(policy),
        "feature_extractor": extractor_identity,
        "transition_config": {"horizon": args.horizon, "gamma": args.gamma},
        "episodes": episode_records,
        "transitions": int(cache["z_state"].shape[0]),
        "shapes": {key: list(value.shape) for key, value in cache.items()},
        "cache": str(cache_path.resolve()),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
