"""Optional per-action-dimension loss weighting for PI0.5 fine-tuning."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


PI05_MODE_SLICE = slice(9, 12)
PI05_STAGE_SLICE = slice(56, 62)
PI05_STAGE_LOSS_WEIGHTING_SCOPE = "flow_loss_only_before_auxiliary_losses_v1"
PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE = (
    "target_grasp_mode_flow_loss_only_before_auxiliary_losses_v1"
)


def reduce_weighted_pi05_losses(
    losses: Any,
    weights: Sequence[float],
    *,
    reduction: str,
) -> tuple[Any, dict[str, Any]]:
    """Reduce BxTxD flow-matching errors without changing average loss scale."""

    import torch

    if losses.ndim != 3:
        raise ValueError("PI0.5 losses must have shape [batch, time, action_dim]")
    if len(weights) != losses.shape[-1]:
        raise ValueError("PI0.5 action loss weight dimension mismatch")
    if any(value <= 0.0 for value in weights):
        raise ValueError("PI0.5 action loss weights must be positive")
    weight_tensor = torch.as_tensor(weights, device=losses.device, dtype=losses.dtype)
    denominator = weight_tensor.sum()
    weighted = losses * weight_tensor.view(1, 1, -1)
    per_sample = weighted.sum(dim=2).mean(dim=1) / denominator
    payload = {
        "loss_per_dim": losses.mean(dim=[0, 1]).detach().cpu().numpy().tolist(),
        "action_loss_weights": list(float(value) for value in weights),
        "weighted_loss_per_dim": weighted.mean(dim=[0, 1]).detach().cpu().numpy().tolist(),
    }
    payload["loss"] = per_sample.mean().item()
    if reduction == "none":
        return per_sample, payload
    if reduction != "mean":
        raise ValueError(f"unsupported PI0.5 loss reduction: {reduction}")
    return per_sample.mean(), payload


def apply_pi05_stage_loss_weights(
    per_sample: Any,
    state: Any,
    weights: Sequence[float],
    *,
    stage_slice: slice = PI05_STAGE_SLICE,
) -> tuple[Any, dict[str, Any]]:
    """Weight samples by the current task stage without batch-local renormalization."""

    import torch

    if per_sample.ndim != 1:
        raise ValueError("PI0.5 per-sample losses must have shape [batch]")
    if state is None or state.ndim != 2 or state.shape[0] != per_sample.shape[0]:
        raise ValueError("PI0.5 stage weighting requires BxD observation state")
    _validate_stage_slice(stage_slice)
    if state.shape[-1] < stage_slice.stop:
        raise ValueError("PI0.5 observation state does not contain six stage channels")
    values = tuple(float(value) for value in weights)
    if len(values) != 6 or any(
        not math.isfinite(value) or value <= 0.0 for value in values
    ):
        raise ValueError("PI0.5 stage loss weights must contain six positive values")
    stage_features = state[:, stage_slice]
    if not torch.isfinite(stage_features).all():
        raise ValueError("PI0.5 stage channels must be finite")
    stage_indices = stage_features.argmax(dim=-1)
    weight_tensor = torch.as_tensor(
        values, device=per_sample.device, dtype=per_sample.dtype
    )
    selected = weight_tensor[stage_indices]
    weighted = per_sample * selected
    counts = torch.bincount(stage_indices, minlength=6).detach().cpu().tolist()
    return weighted, {
        "stage_loss_weights": list(values),
        "stage_batch_counts": counts,
        "stage_selected_weight_mean": selected.mean().item(),
        "stage_unweighted_loss": per_sample.mean().item(),
        "stage_weighted_loss": weighted.mean().item(),
    }


def apply_pi05_mode_flow_loss_weights(
    per_sample: Any,
    target_actions: Any,
    weights: Sequence[float],
    *,
    population_normalizer: float,
    mode_slice: slice = PI05_MODE_SLICE,
) -> tuple[Any, dict[str, Any]]:
    """Weight continuous flow loss by target grasp mode at population scale."""

    import torch

    if per_sample.ndim != 1:
        raise ValueError("PI0.5 per-sample losses must have shape [batch]")
    if target_actions.ndim != 3 or target_actions.shape[0] != per_sample.shape[0]:
        raise ValueError("PI0.5 mode flow weighting requires BxTxD target actions")
    _validate_mode_slice(mode_slice)
    if target_actions.shape[-1] < mode_slice.stop:
        raise ValueError("PI0.5 target actions do not contain three mode channels")
    values = tuple(float(value) for value in weights)
    if len(values) != 3 or any(
        not math.isfinite(value) or value <= 0.0 for value in values
    ):
        raise ValueError("mode flow loss weights must contain three positive values")
    normalizer = float(population_normalizer)
    if not math.isfinite(normalizer) or normalizer <= 0.0:
        raise ValueError("mode flow loss population normalizer must be positive")
    token_targets = target_actions[:, :, mode_slice].argmax(dim=-1)
    targets = token_targets[:, 0]
    if not (token_targets == targets.unsqueeze(1)).all():
        raise ValueError("grasp mode must remain constant within an action chunk")
    weight_tensor = torch.as_tensor(
        values, device=per_sample.device, dtype=per_sample.dtype
    )
    selected = weight_tensor[targets] / normalizer
    weighted = per_sample * selected
    counts = torch.bincount(targets, minlength=3).detach().cpu().tolist()
    return weighted, {
        "mode_flow_loss_weights": list(values),
        "mode_flow_loss_population_normalizer": normalizer,
        "mode_flow_batch_counts": counts,
        "mode_flow_selected_weight_mean": selected.mean().item(),
        "mode_flow_input_loss": per_sample.mean().item(),
        "mode_flow_weighted_loss": weighted.mean().item(),
    }


def reduce_pi05_mode_classification(
    predicted_clean_actions: Any,
    target_actions: Any,
    *,
    mode_slice: slice = PI05_MODE_SLICE,
    reduction: str,
) -> tuple[Any, dict[str, Any]]:
    """Apply categorical supervision to denoised PI0.5 grasp-mode channels."""

    import torch
    import torch.nn.functional as F

    if predicted_clean_actions.ndim != 3 or target_actions.ndim != 3:
        raise ValueError("PI0.5 mode classification requires BxTxD actions")
    if predicted_clean_actions.shape != target_actions.shape:
        raise ValueError("predicted and target PI0.5 actions must have equal shape")
    _validate_mode_slice(mode_slice)
    if predicted_clean_actions.shape[-1] < mode_slice.stop:
        raise ValueError("PI0.5 actions do not contain three mode channels")
    logits = predicted_clean_actions[:, :, mode_slice].float()
    targets = target_actions[:, :, mode_slice].argmax(dim=-1)
    token_losses = F.cross_entropy(
        logits.reshape(-1, 3), targets.reshape(-1), reduction="none"
    ).reshape(logits.shape[:2])
    per_sample = token_losses.mean(dim=1)
    correct_logits = logits.gather(-1, targets.unsqueeze(-1)).squeeze(-1)
    wrong_logits = logits.masked_fill(
        F.one_hot(targets, num_classes=3).bool(), float("-inf")
    ).amax(dim=-1)
    payload = {
        "mode_cross_entropy": per_sample.mean().item(),
        "mode_accuracy": (logits.argmax(dim=-1) == targets).float().mean().item(),
        "mode_margin": (correct_logits - wrong_logits).mean().item(),
    }
    if reduction == "none":
        return per_sample, payload
    if reduction != "mean":
        raise ValueError(f"unsupported PI0.5 loss reduction: {reduction}")
    return per_sample.mean(), payload


def reduce_pi05_mode_head_classification(
    logits: Any,
    target_actions: Any,
    *,
    class_weights: Sequence[float] | None = None,
    mode_slice: slice = PI05_MODE_SLICE,
    reduction: str,
) -> tuple[Any, dict[str, Any]]:
    """Supervise one categorical grasp decision per action chunk."""

    import torch
    import torch.nn.functional as F

    if logits.ndim != 2 or logits.shape[-1] != 3:
        raise ValueError("PI0.5 mode-head logits must have shape Bx3")
    if target_actions.ndim != 3 or target_actions.shape[0] != logits.shape[0]:
        raise ValueError("PI0.5 mode-head targets must have shape BxTxD")
    _validate_mode_slice(mode_slice)
    if target_actions.shape[-1] < mode_slice.stop:
        raise ValueError("PI0.5 actions do not contain three mode channels")
    token_targets = target_actions[:, :, mode_slice].argmax(dim=-1)
    targets = token_targets[:, 0]
    if not (token_targets == targets.unsqueeze(1)).all():
        raise ValueError("grasp mode must remain constant within an action chunk")
    weight_tensor = None
    if class_weights is not None:
        values = tuple(float(value) for value in class_weights)
        if len(values) != 3 or any(
            not math.isfinite(value) or value <= 0.0 for value in values
        ):
            raise ValueError("mode-head class weights must contain three positive values")
        weight_tensor = torch.tensor(values, device=logits.device, dtype=torch.float32)
    per_sample = F.cross_entropy(
        logits.float(), targets, weight=weight_tensor, reduction="none"
    )
    correct_logits = logits.gather(-1, targets.unsqueeze(-1)).squeeze(-1)
    wrong_logits = logits.masked_fill(
        F.one_hot(targets, num_classes=3).bool(), float("-inf")
    ).amax(dim=-1)
    payload = {
        "mode_head_cross_entropy": per_sample.mean().item(),
        "mode_head_accuracy": (logits.argmax(dim=-1) == targets).float().mean().item(),
        "mode_head_margin": (correct_logits - wrong_logits).mean().item(),
    }
    if reduction == "none":
        return per_sample, payload
    if reduction != "mean":
        raise ValueError(f"unsupported PI0.5 loss reduction: {reduction}")
    return per_sample.mean(), payload


def pi05_flow_velocity(
    model: Any,
    images: Any,
    image_masks: Any,
    tokens: Any,
    masks: Any,
    x_t: Any,
    time: Any,
    state: Any | None = None,
    return_mode_head_logits: bool = False,
) -> Any:
    """Evaluate the PI0.5 flow field for training or endpoint diagnostics."""

    import torch

    from lerobot.policies.pi05.modeling_pi05 import (
        make_att_2d_masks,
        prepare_attention_masks_4d,
    )

    from parcel_sorter.pi05_state_token_adapter import pi05_state_token_context

    with pi05_state_token_context(model, state):
        prefix_embs, prefix_pad_masks, prefix_att_masks = model.embed_prefix(
            images, image_masks, tokens, masks
        )
    suffix_embs, suffix_pad_masks, suffix_att_masks, adarms_cond = model.embed_suffix(
        x_t, time
    )
    attention_dtype = (
        model.paligemma_with_expert.paligemma.model.language_model.layers[0]
        .self_attn.q_proj.weight.dtype
    )
    if attention_dtype == torch.bfloat16:
        prefix_embs = prefix_embs.to(dtype=attention_dtype)
        suffix_embs = suffix_embs.to(dtype=attention_dtype)
    pad_masks = torch.cat([prefix_pad_masks, suffix_pad_masks], dim=1)
    att_masks = torch.cat([prefix_att_masks, suffix_att_masks], dim=1)
    att_2d_masks = make_att_2d_masks(pad_masks, att_masks)
    position_ids = torch.cumsum(pad_masks, dim=1) - 1
    att_2d_masks_4d = prepare_attention_masks_4d(att_2d_masks)

    def expert_forward(
        prefix: Any, suffix: Any, attention: Any, positions: Any, cond: Any
    ) -> Any:
        (prefix_out, suffix_out), _ = model.paligemma_with_expert.forward(
            attention_mask=attention,
            position_ids=positions,
            past_key_values=None,
            inputs_embeds=[prefix, suffix],
            use_cache=False,
            adarms_cond=[None, cond],
        )
        return prefix_out, suffix_out

    prefix_out, suffix_out = model._apply_checkpoint(
        expert_forward,
        prefix_embs,
        suffix_embs,
        att_2d_masks_4d,
        position_ids,
        adarms_cond,
    )
    mode_logits = None
    if return_mode_head_logits:
        from parcel_sorter.pi05_mode_head_adapter import (
            PI05_MODE_HEAD_MODULE,
            PI05_MODE_HEAD_POOLING_MASKED_MEAN,
            pool_pi05_contextualized_prefix,
        )

        if not hasattr(model, PI05_MODE_HEAD_MODULE):
            raise RuntimeError("PI0.5 mode-head loss requested without a mode head")
        if prefix_out is None:
            raise RuntimeError("PI0.5 did not return contextualized prefix features")
        pooled = pool_pi05_contextualized_prefix(
            prefix_out,
            prefix_pad_masks,
            masks,
            state_token_present=bool(state is not None and hasattr(model, "state_proj")),
            pooling=getattr(
                model,
                "_parcel_mode_head_pooling",
                PI05_MODE_HEAD_POOLING_MASKED_MEAN,
            ),
        )
        mode_logits = model.mode_head(pooled.float()).float()
    suffix_out = suffix_out[:, -model.config.chunk_size :].float()
    velocity = model._apply_checkpoint(model.action_out_proj, suffix_out)
    return (velocity, mode_logits) if return_mode_head_logits else velocity


def install_pi05_action_loss_weights(
    weights: Sequence[float],
    *,
    mode_cross_entropy_weight: float = 0.0,
    mode_cross_entropy_time: float | None = None,
    mode_head_cross_entropy_weight: float = 0.0,
    mode_head_class_weights: Sequence[float] | None = None,
    mode_channel_start: int = PI05_MODE_SLICE.start,
    stage_loss_weights: Sequence[float] | None = None,
    stage_channel_start: int = PI05_STAGE_SLICE.start,
    mode_flow_loss_weights: Sequence[float] | None = None,
    mode_flow_loss_population_normalizer: float = 1.0,
) -> None:
    """Patch PI0.5 with weighted flow loss and an optional discrete-mode loss."""

    import torch

    from lerobot.policies.pi05.modeling_pi05 import (
        OBS_LANGUAGE_ATTENTION_MASK,
        OBS_LANGUAGE_TOKENS,
        PI05Policy,
    )
    from lerobot.utils.constants import ACTION

    configured_weights = tuple(float(value) for value in weights)
    mode_slice = slice(int(mode_channel_start), int(mode_channel_start) + 3)
    _validate_mode_slice(mode_slice)
    mode_ce_weight = float(mode_cross_entropy_weight)
    if mode_ce_weight < 0.0:
        raise ValueError("mode cross-entropy weight cannot be negative")
    mode_ce_time = (
        None if mode_cross_entropy_time is None else float(mode_cross_entropy_time)
    )
    if mode_ce_time is not None and not 0.0 <= mode_ce_time <= 1.0:
        raise ValueError("mode cross-entropy time must be in [0, 1]")
    mode_head_ce_weight = float(mode_head_cross_entropy_weight)
    if mode_head_ce_weight < 0.0:
        raise ValueError("mode-head cross-entropy weight cannot be negative")
    configured_mode_head_class_weights = (
        None
        if mode_head_class_weights is None
        else tuple(float(value) for value in mode_head_class_weights)
    )
    configured_stage_loss_weights = (
        None
        if stage_loss_weights is None
        else tuple(float(value) for value in stage_loss_weights)
    )
    configured_mode_flow_loss_weights = (
        None
        if mode_flow_loss_weights is None
        else tuple(float(value) for value in mode_flow_loss_weights)
    )
    configured_mode_flow_loss_population_normalizer = float(
        mode_flow_loss_population_normalizer
    )
    stage_slice = slice(int(stage_channel_start), int(stage_channel_start) + 6)
    _validate_stage_slice(stage_slice)
    if configured_stage_loss_weights is not None and (
        len(configured_stage_loss_weights) != 6
        or any(
            not math.isfinite(value) or value <= 0.0
            for value in configured_stage_loss_weights
        )
    ):
        raise ValueError("stage loss weights must contain six positive values")
    if configured_mode_flow_loss_weights is not None and (
        len(configured_mode_flow_loss_weights) != 3
        or any(
            not math.isfinite(value) or value <= 0.0
            for value in configured_mode_flow_loss_weights
        )
        or not math.isfinite(configured_mode_flow_loss_population_normalizer)
        or configured_mode_flow_loss_population_normalizer <= 0.0
    ):
        raise ValueError(
            "mode flow loss weights require three positive values and a positive normalizer"
        )

    def weighted_forward(self: Any, batch: dict[str, Any], reduction: str = "mean"):
        images, image_masks = self._preprocess_images(batch)
        tokens = batch[OBS_LANGUAGE_TOKENS]
        masks = batch[OBS_LANGUAGE_ATTENTION_MASK]
        actions = self.prepare_action(batch)
        noise = self.model.sample_noise(actions.shape, actions.device)
        time = self.model.sample_time(actions.shape[0], actions.device)
        time_expanded = time[:, None, None]
        x_t = time_expanded * noise + (1 - time_expanded) * actions
        target_velocity = noise - actions
        flow_result = pi05_flow_velocity(
            self.model,
            images,
            image_masks,
            tokens,
            masks,
            x_t,
            time,
            batch.get("observation.state"),
            return_mode_head_logits=mode_head_ce_weight > 0.0,
        )
        if mode_head_ce_weight > 0.0:
            predicted_velocity, mode_head_logits = flow_result
        else:
            predicted_velocity = flow_result
            mode_head_logits = None
        losses = (target_velocity - predicted_velocity).square()
        action_dim = self.config.output_features[ACTION].shape[0]
        losses = losses[:, :, :action_dim]
        if len(configured_weights) != action_dim:
            raise ValueError(
                f"configured {len(configured_weights)} action loss weights for {action_dim} outputs"
            )
        flow_per_sample, payload = reduce_weighted_pi05_losses(
            losses, configured_weights, reduction="none"
        )
        unweighted_flow_per_sample = flow_per_sample
        if configured_stage_loss_weights is not None:
            flow_per_sample, stage_payload = apply_pi05_stage_loss_weights(
                flow_per_sample,
                batch.get("observation.state"),
                configured_stage_loss_weights,
                stage_slice=stage_slice,
            )
            payload.update(stage_payload)
        if configured_mode_flow_loss_weights is not None:
            flow_per_sample, mode_flow_payload = apply_pi05_mode_flow_loss_weights(
                flow_per_sample,
                actions,
                configured_mode_flow_loss_weights,
                population_normalizer=(
                    configured_mode_flow_loss_population_normalizer
                ),
                mode_slice=mode_slice,
            )
            payload.update(mode_flow_payload)
        if mode_ce_weight > 0.0:
            if mode_ce_time is None:
                mode_x_t = x_t
                mode_time_expanded = time_expanded
                mode_velocity = predicted_velocity
            else:
                mode_time = torch.full_like(time, mode_ce_time)
                mode_time_expanded = mode_time[:, None, None]
                mode_x_t = mode_time_expanded * noise + (
                    1 - mode_time_expanded
                ) * actions
                mode_velocity = pi05_flow_velocity(
                    self.model,
                    images,
                    image_masks,
                    tokens,
                    masks,
                    mode_x_t,
                    mode_time,
                    batch.get("observation.state"),
                )
            predicted_clean = mode_x_t - mode_time_expanded * mode_velocity
            mode_per_sample, mode_payload = reduce_pi05_mode_classification(
                predicted_clean,
                actions,
                mode_slice=mode_slice,
                reduction="none",
            )
            total_per_sample = flow_per_sample + mode_ce_weight * mode_per_sample
            payload.update(mode_payload)
            payload["mode_cross_entropy_weight"] = mode_ce_weight
            payload["mode_cross_entropy_time"] = (
                time.mean().item() if mode_ce_time is None else mode_ce_time
            )
        else:
            total_per_sample = flow_per_sample
        if mode_head_ce_weight > 0.0:
            mode_head_per_sample, mode_head_payload = (
                reduce_pi05_mode_head_classification(
                    mode_head_logits,
                    actions,
                    class_weights=configured_mode_head_class_weights,
                    mode_slice=mode_slice,
                    reduction="none",
                )
            )
            total_per_sample = (
                total_per_sample + mode_head_ce_weight * mode_head_per_sample
            )
            payload.update(mode_head_payload)
            payload["mode_head_cross_entropy_weight"] = mode_head_ce_weight
        payload["flow_loss_unweighted"] = unweighted_flow_per_sample.mean().item()
        payload["flow_loss"] = flow_per_sample.mean().item()
        payload["stage_loss_weighting_scope"] = (
            PI05_STAGE_LOSS_WEIGHTING_SCOPE
            if configured_stage_loss_weights is not None
            else None
        )
        payload["mode_flow_loss_weighting_scope"] = (
            PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE
            if configured_mode_flow_loss_weights is not None
            else None
        )
        payload["loss"] = total_per_sample.mean().item()
        if reduction == "none":
            return total_per_sample, payload
        if reduction != "mean":
            raise ValueError(f"unsupported PI0.5 loss reduction: {reduction}")
        return total_per_sample.mean(), payload

    PI05Policy.forward = weighted_forward


def pi05_residual_action_weights(mode_weight: float) -> tuple[float, ...]:
    """Return 14-D weights with extra supervision on the three VLA mode logits."""

    if mode_weight < 1.0:
        raise ValueError("mode loss weight must be at least 1")
    values = [1.0] * 14
    values[9:12] = [float(mode_weight)] * 3
    return tuple(values)


def pi05_absolute_action_weights(mode_weight: float) -> tuple[float, ...]:
    """Return 23-D weights for absolute action, mode logits, and progress."""

    if mode_weight < 1.0:
        raise ValueError("mode loss weight must be at least 1")
    values = [1.0] * 23
    values[19:22] = [float(mode_weight)] * 3
    return tuple(values)


def pi05_incremental_action_weights(mode_weight: float) -> tuple[float, ...]:
    """Return 21-D weights for incremental SE(3), mode logits, and progress."""

    if mode_weight < 1.0:
        raise ValueError("mode loss weight must be at least 1")
    values = [1.0] * 21
    values[17:20] = [float(mode_weight)] * 3
    return tuple(values)


def _validate_mode_slice(mode_slice: slice) -> None:
    if (
        mode_slice.step not in (None, 1)
        or mode_slice.start is None
        or mode_slice.stop is None
        or mode_slice.start < 0
        or mode_slice.stop - mode_slice.start != 3
    ):
        raise ValueError("PI0.5 grasp-mode slice must select exactly three channels")


def _validate_stage_slice(stage_slice: slice) -> None:
    if (
        stage_slice.step not in (None, 1)
        or stage_slice.start is None
        or stage_slice.stop is None
        or stage_slice.start < 0
        or stage_slice.stop - stage_slice.start != 6
    ):
        raise ValueError("PI0.5 stage slice must select exactly six channels")
