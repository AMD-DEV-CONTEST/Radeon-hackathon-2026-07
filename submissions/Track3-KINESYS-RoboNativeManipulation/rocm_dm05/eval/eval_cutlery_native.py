#!/usr/bin/env python3
"""Evaluate DM05 on BiGym DishwasherUnloadCutleryLong with safe AMD optimizations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

OPENDM_ROOT = Path(os.environ.get("OPENDM_ROOT", Path.cwd())).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "train"))
sys.path.insert(0, str(OPENDM_ROOT / "d"))
sys.path.insert(0, str(OPENDM_ROOT / "tools"))

import eval_common as common  # noqa: E402
from demonstrations.demo import Demo  # noqa: E402
from dm05_lerobot import DM05Exp  # noqa: E402
from opendm.constants.robot import ActionMode  # noqa: E402


TASK = "DishwasherUnloadCutleryLong"
PROMPT = "Unload cutlery from dishwasher to drawer task."


def controlled_state(env, observation: dict[str, np.ndarray]) -> np.ndarray:
    """Match the 16D cumulative-pelvis state stored by Bigym Plus."""
    arm_positions = []
    for actuator in env.robot.limb_actuators:
        if actuator.joint is None:
            raise RuntimeError("Tendon limb actuators are not supported")
        qpos = np.asarray(env._mojo.physics.bind(actuator.joint).qpos).reshape(-1)
        arm_positions.append(float(qpos[0]))
    return np.concatenate(
        [
            observation["proprioception_floating_base"],
            np.asarray(arm_positions, dtype=np.float32),
            observation["proprioception_grippers"],
        ]
    ).astype(np.float32)


# The shared rollout resolves this symbol from its own module at runtime.
common.controlled_state = controlled_state


class OpenDMPolicy:
    def __init__(
        self,
        model_path: Path,
        chunk_size: int,
        prompt: str,
        diffusion_steps: int,
        model_max_length: int,
        use_lora_wrapper: bool | None = None,
        reuse_kv_workspace: bool = True,
    ):
        self.prompt = prompt
        self.exp = DM05Exp()
        self.exp.task = "inference"
        self.exp.model_config.model_name_or_path = str(model_path)
        self.exp.model_config.chunk_size = chunk_size
        self.exp.inference_config.output_action_dim = 16
        self.exp.inference_config.diffusion_steps = diffusion_steps
        self.exp.trainer_config.model_max_length = model_max_length

        if use_lora_wrapper is None:
            use_lora_wrapper = (model_path / "adapter_config.json").is_file()
        self.use_lora_wrapper = use_lora_wrapper
        model = self.exp.model_config.build_model(use_lora=use_lora_wrapper)
        norm_stats_path = model_path / "norm_stats.json"
        if not norm_stats_path.is_file():
            raise FileNotFoundError(norm_stats_path)
        self.exp.inference_config._initialize(
            model=model,
            model_name_or_path=str(model_path),
            norm_stats_path=str(norm_stats_path),
            n_bins=self.exp.data_config.n_bins,
            model_max_length=model_max_length,
            use_absolute_action=(
                self.exp.data_config.action_mode == ActionMode.RELATIVE
            ),
            add_state=self.exp.data_config.add_state,
        )
        self.reuse_kv_workspace = reuse_kv_workspace
        if reuse_kv_workspace:
            self.exp.inference_config.model.model.action_expert.set_kv_workspace_enabled(
                True
            )

    def infer(self, observation: dict) -> np.ndarray:
        data = {
            "images_1": Image.fromarray(observation["camera_top"]),
            "images_2": Image.fromarray(observation["camera_wrist_left"]),
            "images_3": Image.fromarray(observation["camera_wrist_right"]),
            "state": observation["state"],
            "prompt": self.prompt,
            "meta_data": {},
        }
        with torch.inference_mode():
            return np.asarray(
                self.exp.inference_config._predict(data), dtype=np.float32
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--demo", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", required=True, type=int)
    parser.add_argument("--control-frequency", type=int, default=20)
    parser.add_argument("--policy-frequency", type=int, default=20)
    parser.add_argument("--chunk-size", type=int, default=16)
    parser.add_argument("--diffusion-steps", type=int, default=10)
    parser.add_argument("--execute-actions", type=int, default=8)
    parser.add_argument("--max-policy-steps", type=int, default=800)
    parser.add_argument("--model-max-length", type=int, default=896)
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument(
        "--reuse-kv-workspace",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reuse prefix/suffix KV buffers across diffusion steps.",
    )
    lora_group = parser.add_mutually_exclusive_group()
    lora_group.add_argument(
        "--use-lora-wrapper",
        dest="use_lora_wrapper",
        action="store_true",
        help="Force PEFT LoRA wrapping (normally only needed for adapter checkpoints).",
    )
    lora_group.add_argument(
        "--no-lora-wrapper",
        dest="use_lora_wrapper",
        action="store_false",
        help="Load a merged/full checkpoint without adding a new LoRA wrapper.",
    )
    parser.set_defaults(use_lora_wrapper=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.resolution = 128
    args.task_name = TASK
    args.floating_base_dims = 4
    args.floating_base_interval_scale = 1.0
    args.camera_resolutions = {
        "head": (480, 848),
        "left_wrist": (480, 640),
        "right_wrist": (480, 640),
    }
    if args.control_frequency != args.policy_frequency:
        raise ValueError("This evaluation requires native 20 Hz control and policy")
    policy = OpenDMPolicy(
        args.model_path,
        args.chunk_size,
        args.prompt,
        args.diffusion_steps,
        args.model_max_length,
        args.use_lora_wrapper,
        args.reuse_kv_workspace,
    )
    source = Demo.from_safetensors(args.demo.resolve())
    results = []
    for index, seed in enumerate(args.seeds, start=1):
        result = common.rollout(
            policy,
            source,
            f"seed_{seed}",
            seed,
            args.output_dir,
            args,
        )
        results.append(result)
        print(
            f"rollout={index}/{len(args.seeds)} " + json.dumps(result, sort_keys=True),
            flush=True,
        )

    summary = {
        "model_path": str(args.model_path),
        "task": TASK,
        "prompt": args.prompt,
        "control_frequency": args.control_frequency,
        "policy_frequency": args.policy_frequency,
        "chunk_size": args.chunk_size,
        "diffusion_steps": args.diffusion_steps,
        "execute_actions": args.execute_actions,
        "max_policy_steps": args.max_policy_steps,
        "model_max_length": args.model_max_length,
        "use_lora_wrapper": policy.use_lora_wrapper,
        "reuse_kv_workspace": policy.reuse_kv_workspace,
        "state_definition": "cumulative_floating_base+arm_qpos+grippers",
        "episodes": results,
        "successes": sum(item["success"] for item in results),
        "success_rate": sum(item["success"] for item in results) / len(results),
        "mean_inference_ms": 1000.0
        * sum(item["inference_seconds"] for item in results)
        / max(sum(item["inference_calls"] for item in results), 1),
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(summary_path)


if __name__ == "__main__":
    main()
