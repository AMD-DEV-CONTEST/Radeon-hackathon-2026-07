from __future__ import annotations

import math
from dataclasses import dataclass
from types import MethodType
from typing import Any

import torch
import torch.nn.functional as F
from lerobot.policies.smolvla.modeling_smolvla import make_att_2d_masks
from lerobot.utils.device_utils import get_safe_dtype


def install_capture_safe_embed_suffix(model, *, batch_size: int, device: torch.device) -> None:
    """Remove host-to-device tensor construction from the per-step suffix embedding."""
    hidden = model.vlm_with_expert.expert_hidden_size
    frequency_dtype = get_safe_dtype(torch.float64, device.type)
    fraction = torch.linspace(0.0, 1.0, hidden // 2, dtype=frequency_dtype, device=device)
    period = model.config.min_period * (model.config.max_period / model.config.min_period) ** fraction
    time_scale = 2 * math.pi / period
    suffix_mask = torch.ones((batch_size, model.config.chunk_size), dtype=torch.bool, device=device)
    suffix_att = torch.ones((batch_size, model.config.chunk_size), dtype=torch.float32, device=device)

    def embed_suffix(self, noisy_actions, timestep):
        if noisy_actions.shape[0] != batch_size:
            raise RuntimeError(f"runtime backend was prepared for batch {batch_size}, got {noisy_actions.shape[0]}")
        action_emb = self.action_in_proj(noisy_actions)
        sin_input = time_scale[None, :] * timestep[:, None]
        time_emb = torch.cat([torch.sin(sin_input), torch.cos(sin_input)], dim=1).to(action_emb.dtype)
        action_time_emb = torch.cat([action_emb, time_emb[:, None, :].expand_as(action_emb)], dim=2)
        action_time_emb = self.action_time_mlp_out(F.silu(self.action_time_mlp_in(action_time_emb)))
        return action_time_emb, suffix_mask, suffix_att.to(action_time_emb.dtype)

    model.embed_suffix = MethodType(embed_suffix, model)


def install_targeted_compile(
    model,
    *,
    batch_size: int,
    device: torch.device,
    mode: str = "max-autotune-no-cudagraphs",
    fullgraph: bool = False,
    matmul_precision: str = "highest",
) -> dict:
    install_capture_safe_embed_suffix(model, batch_size=batch_size, device=device)
    torch.set_float32_matmul_precision(matmul_precision)
    kwargs: dict[str, Any] = {"backend": "inductor", "fullgraph": fullgraph}
    if mode != "default":
        kwargs["mode"] = mode
    model.denoise_step = torch.compile(model.denoise_step, **kwargs)
    return {
        "backend": "compile",
        "compile_scope": "model.denoise_step called by the real model.sample_actions",
        "compile_mode": mode,
        "fullgraph": fullgraph,
        "matmul_precision": matmul_precision,
        "batch_size": batch_size,
    }


def _tree_clone(value):
    if torch.is_tensor(value):
        return value.clone()
    if isinstance(value, dict):
        return {key: _tree_clone(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_tree_clone(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_tree_clone(item) for item in value)
    return value


def _tree_copy_(target, source, path="cache") -> None:
    if torch.is_tensor(target):
        if not torch.is_tensor(source) or target.shape != source.shape or target.dtype != source.dtype:
            raise RuntimeError(f"HIP Graph tensor mismatch at {path}")
        target.copy_(source)
        return
    if isinstance(target, dict):
        if not isinstance(source, dict) or target.keys() != source.keys():
            raise RuntimeError(f"HIP Graph mapping mismatch at {path}")
        for key in target:
            _tree_copy_(target[key], source[key], f"{path}.{key}")
        return
    if isinstance(target, (list, tuple)):
        if not isinstance(source, type(target)) or len(target) != len(source):
            raise RuntimeError(f"HIP Graph sequence mismatch at {path}")
        for index, (target_item, source_item) in enumerate(zip(target, source, strict=True)):
            _tree_copy_(target_item, source_item, f"{path}[{index}]")
        return
    if target != source:
        raise RuntimeError(f"HIP Graph static value mismatch at {path}: {target!r} != {source!r}")


@dataclass
class _GraphState:
    prefix_pad_masks: torch.Tensor
    past_key_values: Any
    noise: torch.Tensor
    graph: torch.cuda.CUDAGraph
    output: torch.Tensor


class HipGraphSampleActions:
    """Drop-in callable for model.sample_actions with dynamic-input static-buffer updates."""

    def __init__(self, model, *, batch_size: int, device: torch.device, capture_warmup: int = 3):
        self.model = model
        self.batch_size = batch_size
        self.device = device
        self.capture_warmup = capture_warmup
        self.state: _GraphState | None = None
        self.capture_count = 0
        self.times = [
            torch.full(
                (batch_size,), 1.0 - step / model.config.num_steps, dtype=torch.float32, device=device
            )
            for step in range(model.config.num_steps)
        ]
        install_capture_safe_embed_suffix(model, batch_size=batch_size, device=device)

    def _prefix(self, images, img_masks, lang_tokens, lang_masks, state):
        model = self.model
        prefix_embs, prefix_pad_masks, prefix_att_masks = model.embed_prefix(
            images, img_masks, lang_tokens, lang_masks, state=state
        )
        attention = make_att_2d_masks(prefix_pad_masks, prefix_att_masks)
        positions = torch.cumsum(prefix_pad_masks, dim=1) - 1
        _, cache = model.vlm_with_expert.forward(
            attention_mask=attention,
            position_ids=positions,
            past_key_values=None,
            inputs_embeds=[prefix_embs, None],
            use_cache=model.config.use_cache,
            fill_kv_cache=True,
        )
        return prefix_pad_masks, cache

    def _denoise(self, prefix_pad_masks, cache, noise):
        value = noise
        dt = -1.0 / self.model.config.num_steps
        for time_tensor in self.times:
            velocity = self.model.denoise_step(prefix_pad_masks, cache, value, time_tensor)
            value = value + dt * velocity
        return value

    def _capture(self, prefix_pad_masks, cache, noise) -> None:
        static_prefix = prefix_pad_masks.clone()
        static_cache = _tree_clone(cache)
        static_noise = noise.clone()
        with torch.inference_mode():
            for _ in range(self.capture_warmup):
                self._denoise(static_prefix, static_cache, static_noise)
        torch.cuda.synchronize(self.device)
        graph = torch.cuda.CUDAGraph()
        with torch.inference_mode(), torch.cuda.graph(graph):
            output = self._denoise(static_prefix, static_cache, static_noise)
        self.state = _GraphState(static_prefix, static_cache, static_noise, graph, output)
        self.capture_count += 1

    def __call__(self, images, img_masks, lang_tokens, lang_masks, state, noise=None, **kwargs):
        if kwargs.get("inference_delay") is not None or self.model._rtc_enabled():
            raise RuntimeError("HIP Graph runtime backend does not support RTC")
        if state.shape[0] != self.batch_size:
            raise RuntimeError(f"HIP Graph backend was prepared for batch {self.batch_size}, got {state.shape[0]}")
        if noise is None:
            noise = self.model.sample_noise(
                (self.batch_size, self.model.config.chunk_size, self.model.config.max_action_dim), self.device
            )
        prefix_pad_masks, cache = self._prefix(images, img_masks, lang_tokens, lang_masks, state)
        if self.state is None:
            self._capture(prefix_pad_masks, cache, noise)
        assert self.state is not None
        try:
            self.state.prefix_pad_masks.copy_(prefix_pad_masks)
            _tree_copy_(self.state.past_key_values, cache)
            self.state.noise.copy_(noise)
        except RuntimeError:
            # Language length or another static shape changed. Capture a graph for
            # the new shape instead of replaying stale/incompatible storage.
            self._capture(prefix_pad_masks, cache, noise)
        self.state.graph.replay()
        # Replay mutates static storage. Return an owned tensor so callers/action
        # queues cannot observe a later replay changing a previous result.
        return self.state.output.clone()


def install_hip_graph(model, *, batch_size: int, device: torch.device, capture_warmup: int = 3) -> dict:
    runner = HipGraphSampleActions(
        model, batch_size=batch_size, device=device, capture_warmup=capture_warmup
    )
    model.sample_actions = runner
    # Keep the runner reachable for diagnostics such as capture_count.
    model._hip_graph_runner = runner
    return {
        "backend": "hip-graph",
        "capture_scope": "denoiser inside the real model.sample_actions; prefix remains eager",
        "capture_warmup": capture_warmup,
        "dynamic_inputs_copied": ["prefix_pad_masks", "past_key_values", "noise"],
        "batch_size": batch_size,
    }


def install_backend(model, backend: str, *, batch_size: int, device: torch.device, compile_mode: str, fullgraph: bool, capture_warmup: int, matmul_precision: str = "highest") -> dict:
    if backend == "eager":
        return {"backend": "eager", "batch_size": batch_size}
    if backend == "compile":
        return install_targeted_compile(
            model,
            batch_size=batch_size,
            device=device,
            mode=compile_mode,
            fullgraph=fullgraph,
            matmul_precision=matmul_precision,
        )
    if backend == "hip-graph":
        return install_hip_graph(
            model, batch_size=batch_size, device=device, capture_warmup=capture_warmup
        )
    raise ValueError(f"unknown runtime backend: {backend}")
