"""RLinf BasePolicy adapter for LeRobot SmolVLA."""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
from lerobot.common.constants import ACTION
from torch import nn

from rlinf.models.embodiment.base_policy import BasePolicy, ForwardType

from .checkpoint import load_smolvla_checkpoint


def _cfg_get(cfg: Any, name: str, default: Any) -> Any:
    value = cfg.get(name, default) if hasattr(cfg, "get") else getattr(cfg, name, default)
    return default if value is None else value


def _detach_to_cpu(value: Any) -> Any:
    """Recursively move rollout tensors to CPU without private torch APIs."""
    if torch.is_tensor(value):
        return value.detach().cpu()
    if isinstance(value, dict):
        return {key: _detach_to_cpu(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_detach_to_cpu(item) for item in value)
    if isinstance(value, list):
        return [_detach_to_cpu(item) for item in value]
    return value


class SmolVLARLinfPolicy(nn.Module, BasePolicy):
    """Adapt RLinf rollout observations to a LeRobot SmolVLA policy.

    Phase 4 provides deterministic flow inference and SFT forwarding. SmolVLA
    has no tractable rollout log probability or value head, so placeholder
    zero tensors are returned for the RLinf rollout record; PPO-style training
    is deliberately not claimed by this adapter.
    """

    def __init__(
        self,
        policy: nn.Module,
        *,
        action_dim: int = 7,
        num_action_chunks: int = 5,
        clip_actions: bool = True,
        binarize_gripper: bool = False,
    ):
        super().__init__()
        self.policy = policy
        self.action_dim = int(action_dim)
        self.num_action_chunks = int(num_action_chunks)
        self.clip_actions = bool(clip_actions)
        self.binarize_gripper = bool(binarize_gripper)
        if not 1 <= self.num_action_chunks <= self.policy.config.chunk_size:
            raise ValueError(
                f"num_action_chunks must be in [1, {self.policy.config.chunk_size}]"
            )

    @classmethod
    def from_config(cls, cfg: Any, torch_dtype=None) -> "SmolVLARLinfPolicy":
        dtype = torch_dtype or torch.bfloat16
        action_dim = int(_cfg_get(cfg, "action_dim", 7))
        state_dim = int(_cfg_get(cfg, "state_dim", 8))
        policy = load_smolvla_checkpoint(
            _cfg_get(cfg, "model_path", None),
            device=str(_cfg_get(cfg, "device", "cuda")),
            dtype=dtype,
            state_dim=state_dim,
            action_dim=action_dim,
            num_steps=int(_cfg_get(cfg, "num_steps", 10)),
        )
        return cls(
            policy,
            action_dim=action_dim,
            num_action_chunks=int(_cfg_get(cfg, "num_action_chunks", 5)),
            clip_actions=bool(_cfg_get(cfg, "clip_actions", True)),
            binarize_gripper=bool(_cfg_get(cfg, "binarize_gripper", False)),
        )

    @property
    def config(self):
        return self.policy.config

    @staticmethod
    def _last_rgb_view(value: Any, *, name: str) -> torch.Tensor:
        tensor = torch.as_tensor(value)
        # RLinf may provide [B,H,W,C] or [B,T,H,W,C]. Wrist observations may
        # also use T as the number of cameras; Phase 4 selects its last view.
        if tensor.ndim == 5:
            tensor = tensor[:, -1]
        if tensor.ndim != 4:
            raise ValueError(f"{name} must be [B,H,W,C] or [B,T,H,W,C], got {tuple(tensor.shape)}")
        if tensor.shape[-1] == 3:
            tensor = tensor.permute(0, 3, 1, 2)
        elif tensor.shape[1] != 3:
            raise ValueError(f"{name} has no RGB channel dimension: {tuple(tensor.shape)}")
        tensor = tensor.contiguous()
        if tensor.dtype == torch.uint8:
            tensor = tensor.float().div_(255.0)
        else:
            tensor = tensor.float()
            if tensor.numel() and tensor.max() > 1.0:
                tensor = tensor / 255.0
        return tensor

    def _prepare_rollout_batch(self, env_obs: dict[str, Any]) -> dict[str, Any]:
        required = {"main_images", "states", "task_descriptions"}
        missing = required - env_obs.keys()
        if missing:
            raise KeyError(f"Missing RLinf observation keys: {sorted(missing)}")
        main = self._last_rgb_view(env_obs["main_images"], name="main_images")
        wrist_source = env_obs.get("wrist_images", env_obs["main_images"])
        wrist = self._last_rgb_view(wrist_source, name="wrist_images")
        states = torch.as_tensor(env_obs["states"], dtype=torch.float32)
        if states.ndim != 2:
            raise ValueError(f"states must be [B,D], got {tuple(states.shape)}")
        tasks = env_obs["task_descriptions"]
        if isinstance(tasks, str):
            tasks = [tasks] * states.shape[0]
        if len(tasks) != states.shape[0]:
            raise ValueError("task_descriptions batch size does not match states")
        device = next(self.parameters()).device
        return {
            "observation.state": states.to(device),
            "observation.images.agentview": main.to(device),
            "observation.images.wrist": wrist.to(device),
            "task": list(tasks),
        }

    def predict_action_batch(
        self,
        env_obs: dict[str, Any],
        mode: str = "eval",
        noise: torch.Tensor | None = None,
        **_: Any,
    ) -> tuple[torch.Tensor, dict[str, Any]]:
        batch = self._prepare_rollout_batch(env_obs)
        self.policy.eval()
        dtype = next(self.policy.parameters()).dtype
        with torch.no_grad(), torch.autocast("cuda", dtype=dtype, enabled=batch["observation.state"].is_cuda):
            predicted_action_chunk = self.sample_predicted_action_chunk(batch, noise=noise)
            model_action = predicted_action_chunk[:, : self.num_action_chunks, : self.action_dim]

        action = model_action.float()
        if self.clip_actions:
            action = action.clamp(-1.0, 1.0)
        if self.binarize_gripper:
            action[..., -1] = torch.where(action[..., -1] >= 0, 1.0, -1.0)

        batch_size = action.shape[0]
        flat = action.reshape(batch_size, -1)
        result = {
            "prev_logprobs": torch.zeros_like(flat),
            "prev_values": torch.zeros((batch_size, 1), device=action.device),
            "forward_inputs": {
                **batch,
                "action": flat,
                "model_action": model_action[:, : self.num_action_chunks].float(),
                "predicted_action_chunk": predicted_action_chunk.float(),
                "sampled_noise": noise,
            },
        }
        # RLinf transfers rollout payloads through CPU channels.
        return action.cpu(), _detach_to_cpu(result)

    def sample_predicted_action_chunk(
        self, prepared_batch: dict[str, Any], noise: torch.Tensor | None = None
    ) -> torch.Tensor:
        """Sample one full LeRobot action chunk for every prepared batch row."""
        self.policy.eval()
        self.policy.reset()
        first_action = self.policy.select_action(dict(prepared_batch), noise=noise)
        remaining_actions = list(self.policy._queues[ACTION])
        chunk = first_action.unsqueeze(1)
        if remaining_actions:
            chunk = torch.cat(
                [chunk, torch.stack(remaining_actions, dim=1)], dim=1
            )
        return chunk

    def default_forward(self, forward_inputs: dict[str, Any] | None = None, **kwargs):
        data = forward_inputs or kwargs.get("data")
        if data is None or "action" not in data:
            raise ValueError("default_forward requires a training batch containing action")
        return self.policy(data)

    def sft_forward(self, data: dict[str, Any] | None = None, **kwargs):
        batch = data or kwargs.get("data")
        if batch is None:
            raise ValueError("sft_forward requires data")
        loss, details = self.policy(batch)
        return {"loss": loss, "loss_details": details}

    def forward(self, forward_type=ForwardType.DEFAULT, **kwargs):
        if forward_type == ForwardType.DEFAULT:
            return self.default_forward(**kwargs)
        if forward_type == ForwardType.SFT:
            return self.sft_forward(**kwargs)
        raise NotImplementedError(f"SmolVLA does not implement {forward_type}")
