"""Opt-in state-token direct first-step action head for LeRobot PI0.5."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .pi05_mode_head_adapter import (
    PI05_MODE_HEAD_ATTENTION_IMPLEMENTATIONS,
    PI05_MODE_HEAD_POOLING_STATE_TOKEN,
    pool_pi05_contextualized_prefix,
)
from .pi05_state_token_adapter import (
    PI05_STATE_TOKEN_MODULE,
    install_pi05_state_token_adapter,
    pi05_state_token_context,
)


PI05_DIRECT_ACTION_HEAD_MODULE = "direct_action_head"
PI05_DIRECT_ACTION_STATE_MLP_MODULE = "direct_action_state_mlp"
PI05_DIRECT_ACTION_STATE_RESIDUAL_MODULE = "direct_action_state_residual"
PI05_DIRECT_ACTION_DIM = 21
PI05_DIRECT_ACTION_STATE_DIM = 68
PI05_DIRECT_ACTION_HEAD_PROTOCOL_V1 = (
    "parcel-pi05-state-token-direct-first-step-action-head-21d-v1"
)
PI05_DIRECT_ACTION_HEAD_PROTOCOL_V2 = (
    "parcel-pi05-state-fusion-direct-first-step-action-head-21d-v2"
)
PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3 = (
    "parcel-pi05-observable-state-residual-direct-first-step-action-head-21d-v3"
)
PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4 = (
    "parcel-pi05-observable-state-residual-linear-normalized-direct-first-step-"
    "action-head-21d-v4"
)
PI05_DIRECT_ACTION_HEAD_PROTOCOL = PI05_DIRECT_ACTION_HEAD_PROTOCOL_V1
PI05_DIRECT_ACTION_HEAD_PROTOCOLS = {
    PI05_DIRECT_ACTION_HEAD_PROTOCOL_V1,
    PI05_DIRECT_ACTION_HEAD_PROTOCOL_V2,
    PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3,
    PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4,
}
PI05_DIRECT_ACTION_STATE_RESIDUAL_PROTOCOLS = {
    PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3,
    PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4,
}


def _validate_direct_action_head_protocol(protocol: str) -> str:
    normalized = str(protocol).strip()
    if normalized not in PI05_DIRECT_ACTION_HEAD_PROTOCOLS:
        raise ValueError(f"unsupported PI0.5 direct action head protocol: {protocol!r}")
    return normalized


def pi05_direct_action_head_uses_state_residual(protocol: str) -> bool:
    """Return whether the protocol stores an observable-state residual branch."""

    return _validate_direct_action_head_protocol(
        protocol
    ) in PI05_DIRECT_ACTION_STATE_RESIDUAL_PROTOCOLS


def pi05_direct_action_head_uses_unbounded_normalized_output(protocol: str) -> bool:
    """Return whether normalized direct actions may exceed the fitted quantiles."""

    return _validate_direct_action_head_protocol(
        protocol
    ) == PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4


def checkpoint_uses_pi05_direct_action_head(peft_config: Any) -> bool:
    """Detect a checkpoint that fully stores the direct action head."""

    modules = (
        peft_config.get("modules_to_save")
        if isinstance(peft_config, Mapping)
        else getattr(peft_config, "modules_to_save", None)
    )
    return bool(modules and PI05_DIRECT_ACTION_HEAD_MODULE in set(modules))


def configure_pi05_direct_action_head_peft_defaults(
    defaults: dict[str, Any],
    *,
    protocol: str = PI05_DIRECT_ACTION_HEAD_PROTOCOL,
) -> dict[str, Any]:
    """Persist the randomly initialized direct head fully in PEFT checkpoints."""

    protocol = _validate_direct_action_head_protocol(protocol)
    result = dict(defaults)
    modules_to_save = list(result.get("modules_to_save") or ())
    if PI05_DIRECT_ACTION_HEAD_MODULE not in modules_to_save:
        modules_to_save.append(PI05_DIRECT_ACTION_HEAD_MODULE)
    if (
        protocol == PI05_DIRECT_ACTION_HEAD_PROTOCOL_V2
        and PI05_DIRECT_ACTION_STATE_MLP_MODULE not in modules_to_save
    ):
        modules_to_save.append(PI05_DIRECT_ACTION_STATE_MLP_MODULE)
    if (
        pi05_direct_action_head_uses_state_residual(protocol)
        and PI05_DIRECT_ACTION_STATE_RESIDUAL_MODULE not in modules_to_save
    ):
        modules_to_save.append(PI05_DIRECT_ACTION_STATE_RESIDUAL_MODULE)
    result["modules_to_save"] = modules_to_save
    return result


def apply_pi05_direct_action_head(model: Any, pooled: Any, state: Any = None) -> Any:
    """Apply the installed protocol-specific head to normalized prefix/state data."""

    import torch

    if not hasattr(model, PI05_DIRECT_ACTION_HEAD_MODULE):
        raise RuntimeError("PI0.5 checkpoint does not contain a direct action head")
    protocol = _validate_direct_action_head_protocol(
        getattr(
            model,
            "_parcel_direct_action_head_protocol",
            PI05_DIRECT_ACTION_HEAD_PROTOCOL_V1,
        )
    )
    head = getattr(model, PI05_DIRECT_ACTION_HEAD_MODULE)
    head_device = next(head.parameters()).device
    context = pooled.to(device=head_device, dtype=torch.float32)
    if context.ndim != 2:
        raise ValueError("PI0.5 direct action context must be a BxD tensor")
    features = context
    if protocol in {
        PI05_DIRECT_ACTION_HEAD_PROTOCOL_V2,
        *PI05_DIRECT_ACTION_STATE_RESIDUAL_PROTOCOLS,
    }:
        required_module = (
            PI05_DIRECT_ACTION_STATE_MLP_MODULE
            if protocol == PI05_DIRECT_ACTION_HEAD_PROTOCOL_V2
            else PI05_DIRECT_ACTION_STATE_RESIDUAL_MODULE
        )
        if not hasattr(model, required_module):
            raise RuntimeError(
                f"PI0.5 {protocol} requires {required_module}"
            )
        if state is None:
            raise ValueError("PI0.5 state-aware direct action head requires observation.state")
        if state.ndim != 2 or state.shape[0] != context.shape[0] or state.shape[1] != (
            PI05_DIRECT_ACTION_STATE_DIM
        ):
            raise ValueError(
                "PI0.5 state-aware direct action state must be a normalized Bx68 tensor"
            )
        normalized_state = state.to(device=head_device, dtype=torch.float32)
        if not torch.isfinite(normalized_state).all():
            raise ValueError("PI0.5 state-aware direct action state contains non-finite values")
        state_module = getattr(model, required_module)
        state_output = state_module(normalized_state).float()
        if protocol == PI05_DIRECT_ACTION_HEAD_PROTOCOL_V2:
            features = torch.cat((context, state_output), dim=-1)
        elif state_output.shape != (context.shape[0], PI05_DIRECT_ACTION_DIM):
            raise RuntimeError("PI0.5 direct action state residual must return Bx21")
    context_output = head(features).float()
    if protocol == PI05_DIRECT_ACTION_HEAD_PROTOCOL_V3:
        prediction = torch.tanh(context_output + state_output)
    elif protocol == PI05_DIRECT_ACTION_HEAD_PROTOCOL_V4:
        prediction = context_output + state_output
    else:
        prediction = context_output
    if prediction.ndim != 2 or prediction.shape[-1] != PI05_DIRECT_ACTION_DIM:
        raise RuntimeError("PI0.5 direct action head must return a Bx21 tensor")
    if not torch.isfinite(prediction).all():
        raise RuntimeError("PI0.5 direct action head returned non-finite values")
    if (
        not pi05_direct_action_head_uses_unbounded_normalized_output(protocol)
        and ((prediction < -1.0).any() or (prediction > 1.0).any())
    ):
        raise RuntimeError("PI0.5 direct action head returned an unnormalized action")
    return prediction


def pi05_direct_action_head_prediction(
    model: Any,
    images: Any,
    image_masks: Any,
    tokens: Any,
    masks: Any,
    state: Any,
) -> Any:
    """Predict one normalized 21D action from the contextualized state token."""

    import torch
    from lerobot.policies.pi05.modeling_pi05 import (
        make_att_2d_masks,
        prepare_attention_masks_4d,
    )

    if not hasattr(model, PI05_DIRECT_ACTION_HEAD_MODULE):
        raise RuntimeError("PI0.5 checkpoint does not contain a direct action head")
    if not hasattr(model, PI05_STATE_TOKEN_MODULE):
        raise RuntimeError("PI0.5 direct action head requires the state-token adapter")
    if state is None:
        raise ValueError("PI0.5 direct action head requires observation.state")

    with pi05_state_token_context(model, state):
        prefix, pad_masks, att_masks = model.embed_prefix(
            images, image_masks, tokens, masks
        )
    attention_dtype = (
        model.paligemma_with_expert.paligemma.model.language_model.layers[0]
        .self_attn.q_proj.weight.dtype
    )
    if attention_dtype == torch.bfloat16:
        prefix = prefix.to(dtype=attention_dtype)
    attention_2d = make_att_2d_masks(pad_masks, att_masks)
    positions = torch.cumsum(pad_masks, dim=1) - 1
    attention_4d = prepare_attention_masks_4d(attention_2d)
    attention_implementation = getattr(
        model, "_parcel_direct_action_head_attention_implementation", "eager"
    )
    if attention_implementation not in PI05_MODE_HEAD_ATTENTION_IMPLEMENTATIONS:
        raise RuntimeError(
            "unsupported PI0.5 direct-action-head attention implementation: "
            f"{attention_implementation!r}"
        )
    model.paligemma_with_expert.paligemma.model.language_model.config._attn_implementation = (
        attention_implementation
    )
    (contextualized, _), _ = model.paligemma_with_expert.forward(
        attention_mask=attention_4d,
        position_ids=positions,
        past_key_values=None,
        inputs_embeds=[prefix, None],
        use_cache=False,
    )
    if contextualized is None:
        raise RuntimeError("PI0.5 did not return contextualized prefix features")
    pooled = pool_pi05_contextualized_prefix(
        contextualized,
        pad_masks,
        masks,
        state_token_present=True,
        pooling=PI05_MODE_HEAD_POOLING_STATE_TOKEN,
    )
    return apply_pi05_direct_action_head(model, pooled, state)


def _unwrap_pi05_policy(policy: Any) -> Any:
    candidate = policy
    get_base_model = getattr(candidate, "get_base_model", None)
    if callable(get_base_model):
        candidate = get_base_model()
    if not hasattr(candidate, "_preprocess_images") or not hasattr(candidate, "model"):
        raise RuntimeError("unable to unwrap PI0.5 policy for direct action inference")
    return candidate


def configure_pi05_direct_action_head_runtime(
    policy: Any,
    *,
    attention_implementation: str,
) -> None:
    """Bind the attention implementation used by the direct-head prefix pass."""

    if attention_implementation not in PI05_MODE_HEAD_ATTENTION_IMPLEMENTATIONS:
        raise ValueError(
            "attention_implementation must be one of "
            f"{sorted(PI05_MODE_HEAD_ATTENTION_IMPLEMENTATIONS)}"
        )
    base_policy = _unwrap_pi05_policy(policy)
    setattr(
        base_policy.model,
        "_parcel_direct_action_head_attention_implementation",
        attention_implementation,
    )


def predict_pi05_direct_action_head(policy: Any, batch: dict[str, Any]) -> Any:
    """Predict a normalized first-step action from a preprocessed PI0.5 batch."""

    from lerobot.policies.pi05.modeling_pi05 import (
        OBS_LANGUAGE_ATTENTION_MASK,
        OBS_LANGUAGE_TOKENS,
    )

    base_policy = _unwrap_pi05_policy(policy)
    images, image_masks = base_policy._preprocess_images(batch)
    return pi05_direct_action_head_prediction(
        base_policy.model,
        images,
        image_masks,
        batch[OBS_LANGUAGE_TOKENS],
        batch[OBS_LANGUAGE_ATTENTION_MASK],
        batch.get("observation.state"),
    )


def install_pi05_direct_action_head_adapter(
    *,
    hidden_dim: int = 128,
    protocol: str = PI05_DIRECT_ACTION_HEAD_PROTOCOL,
) -> None:
    """Patch LeRobot PI0.5 with an opt-in normalized 21D direct action head."""

    if hidden_dim <= 0:
        raise ValueError("PI0.5 direct action head hidden dimension must be positive")
    protocol = _validate_direct_action_head_protocol(protocol)

    install_pi05_state_token_adapter()

    import torch
    from lerobot.policies.pi05.modeling_pi05 import PI05Policy, PI05Pytorch

    if getattr(PI05Pytorch, "_parcel_direct_action_head_installed", False):
        installed_hidden_dim = int(
            getattr(PI05Pytorch, "_parcel_direct_action_head_hidden_dim", 128)
        )
        if installed_hidden_dim != int(hidden_dim):
            raise RuntimeError(
                "PI0.5 direct action head is already installed with hidden dimension "
                f"{installed_hidden_dim}, not {hidden_dim}"
            )
        installed_protocol = str(
            getattr(
                PI05Pytorch,
                "_parcel_direct_action_head_protocol",
                PI05_DIRECT_ACTION_HEAD_PROTOCOL_V1,
            )
        )
        if installed_protocol != protocol:
            raise RuntimeError(
                "PI0.5 direct action head is already installed with protocol "
                f"{installed_protocol!r}, not {protocol!r}"
            )
        return

    original_model_init = PI05Pytorch.__init__
    original_fix_state_dict = PI05Policy._fix_pytorch_state_dict_keys
    original_peft_defaults = PI05Policy._get_default_peft_targets

    def model_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_model_init(self, *args, **kwargs)
        embedding = (
            self.paligemma_with_expert.paligemma.model.language_model.embed_tokens
        )
        prefix_width = int(embedding.weight.shape[1])
        direct_head_input_dim = prefix_width
        if protocol == PI05_DIRECT_ACTION_HEAD_PROTOCOL_V2:
            self.direct_action_state_mlp = torch.nn.Sequential(
                torch.nn.LayerNorm(PI05_DIRECT_ACTION_STATE_DIM, dtype=torch.float32),
                torch.nn.Linear(
                    PI05_DIRECT_ACTION_STATE_DIM, hidden_dim, dtype=torch.float32
                ),
                torch.nn.GELU(),
            )
            torch.nn.init.xavier_uniform_(self.direct_action_state_mlp[1].weight)
            torch.nn.init.zeros_(self.direct_action_state_mlp[1].bias)
            direct_head_input_dim += hidden_dim
        direct_head_layers: list[torch.nn.Module] = [
            torch.nn.LayerNorm(direct_head_input_dim, dtype=torch.float32),
            torch.nn.Linear(direct_head_input_dim, hidden_dim, dtype=torch.float32),
            torch.nn.GELU(),
            torch.nn.Linear(
                hidden_dim, PI05_DIRECT_ACTION_DIM, dtype=torch.float32
            ),
        ]
        if not pi05_direct_action_head_uses_state_residual(protocol):
            direct_head_layers.append(torch.nn.Tanh())
        self.direct_action_head = torch.nn.Sequential(*direct_head_layers)
        if pi05_direct_action_head_uses_state_residual(protocol):
            self.direct_action_state_residual = torch.nn.Sequential(
                torch.nn.LayerNorm(PI05_DIRECT_ACTION_STATE_DIM, dtype=torch.float32),
                torch.nn.Linear(
                    PI05_DIRECT_ACTION_STATE_DIM, hidden_dim, dtype=torch.float32
                ),
                torch.nn.GELU(),
                torch.nn.Linear(
                    hidden_dim, PI05_DIRECT_ACTION_DIM, dtype=torch.float32
                ),
            )
            torch.nn.init.xavier_uniform_(self.direct_action_state_residual[1].weight)
            torch.nn.init.zeros_(self.direct_action_state_residual[1].bias)
            torch.nn.init.zeros_(self.direct_action_state_residual[3].weight)
            torch.nn.init.zeros_(self.direct_action_state_residual[3].bias)
        torch.nn.init.xavier_uniform_(self.direct_action_head[1].weight)
        torch.nn.init.zeros_(self.direct_action_head[1].bias)
        torch.nn.init.zeros_(self.direct_action_head[3].weight)
        torch.nn.init.zeros_(self.direct_action_head[3].bias)

    def fix_state_dict(
        self: Any, state_dict: dict[str, Any], model_config: Any
    ) -> dict[str, Any]:
        fixed = original_fix_state_dict(self, state_dict, model_config)
        for key, value in self.model.direct_action_head.state_dict().items():
            fixed.setdefault(f"direct_action_head.{key}", value.detach().clone())
        if protocol == PI05_DIRECT_ACTION_HEAD_PROTOCOL_V2:
            for key, value in self.model.direct_action_state_mlp.state_dict().items():
                fixed.setdefault(
                    f"direct_action_state_mlp.{key}", value.detach().clone()
                )
        if pi05_direct_action_head_uses_state_residual(protocol):
            for key, value in self.model.direct_action_state_residual.state_dict().items():
                fixed.setdefault(
                    f"direct_action_state_residual.{key}", value.detach().clone()
                )
        return fixed

    def peft_defaults(self: Any) -> dict[str, Any]:
        defaults = original_peft_defaults(self)
        if defaults is None:
            raise RuntimeError("PI0.5 does not expose PEFT target defaults")
        return configure_pi05_direct_action_head_peft_defaults(
            defaults, protocol=protocol
        )

    PI05Pytorch.__init__ = model_init
    PI05Pytorch._parcel_direct_action_head_installed = True
    PI05Pytorch._parcel_direct_action_head_hidden_dim = int(hidden_dim)
    PI05Pytorch._parcel_direct_action_head_protocol = protocol
    PI05Policy._fix_pytorch_state_dict_keys = fix_state_dict
    PI05Policy._get_default_peft_targets = peft_defaults
