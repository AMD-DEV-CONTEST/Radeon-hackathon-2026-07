"""pi0.5 with a tactile encoder wired into the action expert's conditioning.

WHY NOT observation.state. pi0.5 does not feed state to the action expert as a
vector. `Pi05PrepareStateTokenizerProcessorStep` normalizes it, digitizes it
into 256 bins and pastes it into the TEXT prompt -- "Task: open the left
drawer, State: 128 91 204 ...". A contact signal folded in there arrives 8-bit
quantized through the tokenizer, and ours is quiet for most of an episode and
then steps, so after per-dim normalization the quiet majority collapses into a
bin or two while the event saturates. Exactly the wrong channel for the one
transient the task turns on.

WHERE IT GOES INSTEAD. `PI05Pytorch.embed_suffix` builds `adarms_cond` from the
flow-matching timestep, and `PaliGemmaWithExpertModel.forward` passes it as
`adarms_cond=[None, cond]` -- index 0 is the VLM, index 1 the action expert --
where that single (B, width) vector modulates EVERY adaRMSNorm in the expert.
Adding a tactile embedding to it puts touch on a continuous path straight into
the action decoder, with no tokenizer in between. It is global FiLM-style
modulation: good at gating "am I loaded or not", carrying no spatial structure
of its own.

ZERO INIT. The second linear starts at zero, so `tactile_mlp(x) == 0` and the
model is bit-identical to pretrained pi0.5 on step one. The pathway grows from
nothing instead of injecting noise into a 4B model that already works.

UNVERIFIED OFF-INSTANCE. lerobot is not importable in the local environment, so
this is written against the source and not executed. Two things to check first:
  * `observation.tactile` survives `dataset_to_policy_features` and gets
    normalization stats -- it must reach the batch, and it must NOT be swept
    into OBS_STATE (the state tokenizer reads that key by name, so it should
    not be, but confirm rather than assume)
  * the checkpoint round-trips: `tactile_mlp.*` is a new key, so loading a
    stock pi05 checkpoint reports it missing and that is expected
"""
from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn

from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.pi05.configuration_pi05 import PI05Config
from lerobot.policies.pi05.modeling_pi05 import (
    PI05Policy,
    PI05Pytorch,
    get_gemma_config,
)
from lerobot.policies.pretrained import PreTrainedPolicy
from lerobot.utils.import_utils import require_package

OBS_TACTILE = "observation.tactile"


@PreTrainedConfig.register_subclass("tactile_pi05")
@dataclass
class TactilePI05Config(PI05Config):
    """pi0.5 plus the width of the tactile feature the dataset carries.

    `tactile_dim` must match `TactileConfig.dim` -- 2 fingers x n_probes x 3.
    """
    tactile_dim: int = 24


class TactilePI05Pytorch(PI05Pytorch):
    """PI05Pytorch with `tactile_mlp(tactile)` added to `adarms_cond`.

    The tensor arrives by attribute rather than argument because `embed_suffix`
    is called from both `forward` and `sample_actions` with a fixed signature,
    and overriding both to thread one more tensor through would duplicate the
    flow-matching loop for nothing. `TactilePI05Policy` sets it immediately
    before delegating, and clears it when the batch has no tactile.
    """

    def __init__(self, config: TactilePI05Config, rtc_processor=None):
        super().__init__(config, rtc_processor=rtc_processor)
        width = get_gemma_config(config.action_expert_variant).width
        self.tactile_mlp = nn.Sequential(
            nn.Linear(config.tactile_dim, width),
            nn.SiLU(),
            nn.Linear(width, width),
        )
        # Start as a no-op: the pretrained model is untouched on step one.
        nn.init.zeros_(self.tactile_mlp[-1].weight)
        nn.init.zeros_(self.tactile_mlp[-1].bias)
        self.tactile: Tensor | None = None
        # Logged, not learned. Non-persistent so they stay out of checkpoints.
        self.register_buffer("_cond_norm", torch.zeros(()), persistent=False)
        self.register_buffer("_base_norm", torch.zeros(()), persistent=False)

    def embed_suffix(self, noisy_actions, timestep):
        embs, pad_masks, att_masks, adarms_cond = super().embed_suffix(noisy_actions, timestep)
        if self.tactile is not None:
            cond = self.tactile_mlp(self.tactile.to(adarms_cond.dtype))
            self._cond_norm = cond.detach().float().norm(dim=-1).mean()
            self._base_norm = adarms_cond.detach().float().norm(dim=-1).mean()
            adarms_cond = adarms_cond + cond
        return embs, pad_masks, att_masks, adarms_cond


class TactilePI05Policy(PI05Policy):
    """pi0.5 that also sees touch.

    Both entry points are intercepted -- `forward` for training and
    `predict_action_chunk` for inference -- because the conditioning has to be
    in place before the flow-matching loop starts, and `select_action` reaches
    inference through `predict_action_chunk`.
    """

    config_class = TactilePI05Config
    name = "tactile_pi05"

    def __init__(self, config: TactilePI05Config, **kwargs):
        # PI05Policy.__init__ is replicated rather than called, because it builds
        # a plain PI05Pytorch and then applies gradient checkpointing, the device
        # and reset() TO THAT OBJECT. Calling it and swapping the model
        # afterwards silently drops all three: --policy.gradient_checkpointing
        # is honoured on a model that is then discarded, and the replacement
        # trains without it. That costs most of the activation memory and shows
        # up only as an OOM at a batch size that should fit.
        require_package("transformers", extra="pi")
        PreTrainedPolicy.__init__(self, config)
        config.validate_features()
        self.config = config

        self.init_rtc_processor()
        self.model = TactilePI05Pytorch(config, rtc_processor=self.rtc_processor)

        if config.gradient_checkpointing:
            self.model.gradient_checkpointing_enable()
        self.model.to(config.device)
        self.reset()

    def _set_tactile(self, batch: dict[str, Tensor]) -> None:
        t = batch.get(OBS_TACTILE)
        if t is None:
            # Explicitly cleared, not left over: a stale tensor from the last
            # batch would silently condition this one, and with a zero-init
            # encoder the symptom is a slow drift rather than a crash.
            self.model.tactile = None
            return
        self.model.tactile = t.to(next(self.parameters()).device)

    def forward(self, batch: dict[str, Tensor], reduction: str = "mean"):
        self._set_tactile(batch)
        loss, out = super().forward(batch, reduction=reduction)
        if self.model.tactile is not None:
            # The whole point of the zero init is that this starts at 0. If it
            # is still 0 late in training, touch is earning nothing and the
            # pathway is decoration -- which no loss curve would reveal.
            m = self.model
            out["tactile_cond_norm"] = m._cond_norm.item()
            out["tactile_cond_ratio"] = (
                m._cond_norm / m._base_norm.clamp_min(1e-6)).item()
        return loss, out

    @torch.no_grad()
    def predict_action_chunk(self, batch: dict[str, Tensor], **kwargs) -> Tensor:
        self._set_tactile(batch)
        return super().predict_action_chunk(batch, **kwargs)


def register() -> None:
    """Teach lerobot's factory about this policy. Call before parsing args.

    Registering the CONFIG subclass is not enough. `factory.get_policy_class`
    is a hardcoded if/elif chain over names with no registry behind it, so
    `--policy.type=tactile_pi05` resolves a config and then fails to find a
    class. This wraps that one function rather than patching lerobot -- a
    registry there would be a clean upstream PR.

    `make_pre_post_processors` needs nothing: it dispatches on
    `isinstance(policy_cfg, PI05Config)`, which a subclass satisfies, so the
    pi0.5 preprocessing -- including the state tokenizer -- is inherited.
    """
    from lerobot.policies import factory

    if getattr(factory.get_policy_class, "_tactile_patched", False):
        return
    inner = factory.get_policy_class

    def get_policy_class(name: str):
        if name == TactilePI05Policy.name:
            return TactilePI05Policy
        return inner(name)

    get_policy_class._tactile_patched = True
    factory.get_policy_class = get_policy_class
