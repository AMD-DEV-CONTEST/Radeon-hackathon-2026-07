"""Opt-in native state token for LeRobot PI0.5."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from typing import Any, Iterator

from .mobile_pi05_contract import MOBILE_PI05_STATE_NAMES


PI05_STATE_TOKEN_MODULE = "state_proj"
PI05_STATE_TOKEN_PROTOCOL = "parcel-pi05-state-token-v1"
PI05_HIDDEN_MODE_STATE_SLICE = slice(52, 55)
PI05_MODE_DEPENDENT_ANCHOR_SLICE = slice(74, 80)


def prepare_pi05_state_token_input(state: Any, *, max_state_dim: int) -> Any:
    """Zero hidden mode channels and pad a normalized Bx80 state tensor."""

    import torch
    import torch.nn.functional as F

    if not isinstance(state, torch.Tensor) or state.ndim != 2:
        raise ValueError("PI0.5 state token requires a BxD tensor")
    if state.shape[1] != len(MOBILE_PI05_STATE_NAMES):
        raise ValueError(
            f"PI0.5 state token requires {len(MOBILE_PI05_STATE_NAMES)} inputs"
        )
    if max_state_dim < state.shape[1]:
        raise ValueError("PI0.5 max_state_dim cannot truncate observable state")
    if not torch.isfinite(state).all():
        raise ValueError("PI0.5 state token contains non-finite values")
    prepared = state.clone()
    prepared[:, PI05_HIDDEN_MODE_STATE_SLICE] = 0.0
    prepared[:, PI05_MODE_DEPENDENT_ANCHOR_SLICE] = 0.0
    return F.pad(prepared, (0, max_state_dim - prepared.shape[1]))


def checkpoint_uses_pi05_state_token(peft_config: Any) -> bool:
    """Detect the adapter from PEFT's fully saved state projection metadata."""

    modules = (
        peft_config.get("modules_to_save")
        if isinstance(peft_config, Mapping)
        else getattr(peft_config, "modules_to_save", None)
    )
    return bool(modules and PI05_STATE_TOKEN_MODULE in set(modules))


def configure_pi05_state_token_peft_defaults(
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Save the new projection fully instead of LoRA-wrapping a random base."""

    result = dict(defaults)
    target_modules = result.get("target_modules")
    if isinstance(target_modules, str):
        result["target_modules"] = target_modules.replace("state_proj|", "")
    modules_to_save = list(result.get("modules_to_save") or ())
    if PI05_STATE_TOKEN_MODULE not in modules_to_save:
        modules_to_save.append(PI05_STATE_TOKEN_MODULE)
    result["modules_to_save"] = modules_to_save
    return result


@contextmanager
def pi05_state_token_context(model: Any, state: Any | None) -> Iterator[None]:
    """Expose one normalized state tensor to the patched prefix embedder."""

    if not hasattr(model, PI05_STATE_TOKEN_MODULE):
        yield
        return
    if state is None:
        raise ValueError("state-token PI0.5 checkpoint requires observation.state")
    attribute = "_parcel_state_token_input"
    sentinel = object()
    previous = getattr(model, attribute, sentinel)
    setattr(model, attribute, state)
    try:
        yield
    finally:
        if previous is sentinel:
            delattr(model, attribute)
        else:
            setattr(model, attribute, previous)


def install_pi05_state_token_adapter() -> None:
    """Patch LeRobot PI0.5 with an opt-in, checkpoint-compatible state token."""

    import torch
    from lerobot.policies.pi05.modeling_pi05 import PI05Policy, PI05Pytorch

    if getattr(PI05Pytorch, "_parcel_state_token_installed", False):
        return

    original_model_init = PI05Pytorch.__init__
    original_embed_prefix = PI05Pytorch.embed_prefix
    original_policy_forward = PI05Policy.forward
    original_predict_action_chunk = PI05Policy.predict_action_chunk
    original_fix_state_dict = PI05Policy._fix_pytorch_state_dict_keys
    original_peft_defaults = PI05Policy._get_default_peft_targets

    def model_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_model_init(self, *args, **kwargs)
        embedding = (
            self.paligemma_with_expert.paligemma.model.language_model.embed_tokens
        )
        prefix_width = int(embedding.weight.shape[1])
        self.state_proj = torch.nn.Linear(self.config.max_state_dim, prefix_width)
        torch.nn.init.zeros_(self.state_proj.weight)
        torch.nn.init.zeros_(self.state_proj.bias)

    def embed_prefix(
        self: Any,
        images: Any,
        img_masks: Any,
        tokens: Any,
        masks: Any,
    ) -> tuple[Any, Any, Any]:
        prefix, pad_masks, att_masks = original_embed_prefix(
            self, images, img_masks, tokens, masks
        )
        state = getattr(self, "_parcel_state_token_input", None)
        if state is None:
            raise ValueError("state-token PI0.5 prefix is missing observation.state")
        prepared = prepare_pi05_state_token_input(
            state, max_state_dim=int(self.config.max_state_dim)
        )
        state_token = self.state_proj(
            prepared.to(device=self.state_proj.weight.device, dtype=self.state_proj.weight.dtype)
        ).to(dtype=prefix.dtype)
        state_token = state_token.unsqueeze(1)
        batch_size = prefix.shape[0]
        prefix = torch.cat([prefix, state_token], dim=1)
        pad_masks = torch.cat(
            [
                pad_masks,
                torch.ones(
                    (batch_size, 1), dtype=pad_masks.dtype, device=pad_masks.device
                ),
            ],
            dim=1,
        )
        att_masks = torch.cat(
            [
                att_masks,
                torch.zeros(
                    (batch_size, 1), dtype=att_masks.dtype, device=att_masks.device
                ),
            ],
            dim=1,
        )
        return prefix, pad_masks, att_masks

    def policy_forward(
        self: Any, batch: dict[str, Any], reduction: str = "mean"
    ) -> Any:
        with pi05_state_token_context(self.model, batch.get("observation.state")):
            return original_policy_forward(self, batch, reduction=reduction)

    def predict_action_chunk(self: Any, batch: dict[str, Any], **kwargs: Any) -> Any:
        with pi05_state_token_context(self.model, batch.get("observation.state")):
            return original_predict_action_chunk(self, batch, **kwargs)

    def fix_state_dict(
        self: Any, state_dict: dict[str, Any], model_config: Any
    ) -> dict[str, Any]:
        fixed = original_fix_state_dict(self, state_dict, model_config)
        for key, value in self.model.state_proj.state_dict().items():
            fixed.setdefault(f"state_proj.{key}", value.detach().clone())
        return fixed

    def peft_defaults(self: Any) -> dict[str, Any]:
        defaults = original_peft_defaults(self)
        if defaults is None:
            raise RuntimeError("PI0.5 does not expose PEFT target defaults")
        return configure_pi05_state_token_peft_defaults(defaults)

    PI05Pytorch.__init__ = model_init
    PI05Pytorch.embed_prefix = embed_prefix
    PI05Pytorch._parcel_state_token_installed = True
    PI05Policy.forward = policy_forward
    PI05Policy.predict_action_chunk = predict_action_chunk
    PI05Policy._fix_pytorch_state_dict_keys = fix_state_dict
    PI05Policy._get_default_peft_targets = peft_defaults
