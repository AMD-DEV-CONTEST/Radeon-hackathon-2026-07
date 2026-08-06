"""Reusable DM0.5 policy loader shared by evaluation and HTTP serving."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from dm05_lerobot import DM05Exp
from opendm.constants.robot import ActionMode
from PIL import Image


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
        self.reuse_kv_workspace = reuse_kv_workspace
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
        if reuse_kv_workspace:
            self.exp.inference_config.model.model.action_expert.set_kv_workspace_enabled(
                True
            )

    def infer(self, observation: dict, prompt: str | None = None) -> np.ndarray:
        data = {
            "images_1": Image.fromarray(observation["camera_top"]),
            "images_2": Image.fromarray(observation["camera_wrist_left"]),
            "images_3": Image.fromarray(observation["camera_wrist_right"]),
            "state": observation["state"],
            "prompt": prompt if prompt is not None else self.prompt,
            "meta_data": {},
        }
        with torch.inference_mode():
            return np.asarray(
                self.exp.inference_config._predict(data), dtype=np.float32
            )
