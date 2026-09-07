"""Actor-critic network, tanh-Gaussian policy, and running obs normalizer.

Shared by the from-scratch single-GPU PPO trainer (``src/train_jax_ppo.py``)
and the evaluator (``src/eval.py``), so a checkpoint saved by training reloads
for closed-loop eval / rendering with an identical network.

Matches the structure of Playground's tuned Go1 config (verified on the
instance): an **asymmetric** actor-critic — the policy sees the proprioceptive
``"state"`` obs (deployable from onboard sensing) while the critic sees the
richer ``"privileged_state"`` — plus running observation normalization. Hidden
sizes default to the reference ``(512, 256, 128)``.

Deliberately self-contained (flax + jax only): it does NOT use brax's training
networks, because brax's PPO runner is what segfaults on this gfx1100 +
jax-rocm7 stack (see docs/ROCM_BUG_REPORT.md). Everything here is pure ``jax.jit``-able
math — no ``pmap``, no multi-device collectives — the path that avoids the
HSA-layer crash.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Sequence

import jax
import jax.numpy as jnp
import flax.linen as nn

# Playground locomotion envs expose obs as a dict: "state" (actor, non-
# privileged) and "privileged_state" (critic-only). Fall back gracefully for
# envs that hand back a plain array.
ACTOR_OBS_KEY = "state"
CRITIC_OBS_KEY = "privileged_state"


def get_actor_obs(obs) -> jnp.ndarray:
    if isinstance(obs, Mapping):
        return jnp.asarray(obs[ACTOR_OBS_KEY], dtype=jnp.float32)
    return jnp.asarray(obs, dtype=jnp.float32)


def get_critic_obs(obs) -> jnp.ndarray:
    if isinstance(obs, Mapping):
        key = CRITIC_OBS_KEY if CRITIC_OBS_KEY in obs else ACTOR_OBS_KEY
        return jnp.asarray(obs[key], dtype=jnp.float32)
    return jnp.asarray(obs, dtype=jnp.float32)


# --- Running observation normalizer (Welford batch update) -------------------
# Plain pytree state (count, mean, m2) — jit-friendly, saved in the checkpoint.

def norm_init(dim: int) -> dict:
    return {
        "count": jnp.zeros((), jnp.float32),
        "mean": jnp.zeros((dim,), jnp.float32),
        "m2": jnp.zeros((dim,), jnp.float32),
    }


def norm_update(state: dict, batch: jnp.ndarray) -> dict:
    """Update running stats with a batch of obs, shape (N, dim)."""
    batch = batch.reshape((-1, batch.shape[-1]))
    b_count = batch.shape[0]
    b_mean = jnp.mean(batch, axis=0)
    b_m2 = jnp.sum((batch - b_mean) ** 2, axis=0)
    delta = b_mean - state["mean"]
    new_count = state["count"] + b_count
    new_mean = state["mean"] + delta * (b_count / new_count)
    new_m2 = state["m2"] + b_m2 + delta**2 * (state["count"] * b_count / new_count)
    return {"count": new_count, "mean": new_mean, "m2": new_m2}


def norm_apply(state: dict, x: jnp.ndarray) -> jnp.ndarray:
    var = state["m2"] / jnp.maximum(state["count"], 1.0)
    std = jnp.sqrt(var + 1e-6)
    return jnp.clip((x - state["mean"]) / std, -10.0, 10.0)


class ActorCritic(nn.Module):
    """Asymmetric MLP actor-critic.

    Policy head emits (mean, log_std) per action dim from the actor obs; value
    head reads the (privileged) critic obs. Inputs are expected already
    normalized. Lightweight by design — the track rewards low-latency policies.
    """

    action_size: int
    policy_hidden: Sequence[int] = (512, 256, 128)
    value_hidden: Sequence[int] = (512, 256, 128)
    log_std_min: float = -5.0
    log_std_max: float = 2.0

    @nn.compact
    def __call__(self, actor_x, critic_x):
        init = nn.initializers.lecun_uniform()

        p = actor_x
        for h in self.policy_hidden:
            p = nn.tanh(nn.Dense(h, kernel_init=init)(p))
        policy_out = nn.Dense(2 * self.action_size, kernel_init=init)(p)
        mean, log_std = jnp.split(policy_out, 2, axis=-1)
        log_std = jnp.clip(log_std, self.log_std_min, self.log_std_max)

        v = critic_x
        for h in self.value_hidden:
            v = nn.tanh(nn.Dense(h, kernel_init=init)(v))
        value = nn.Dense(1, kernel_init=init)(v)

        return mean, log_std, jnp.squeeze(value, axis=-1)


# --- tanh-Gaussian policy math ----------------------------------------------
# Actions are tanh-squashed to (-1, 1). We store the sample-time log-prob and
# recompute the new-policy log-prob from the stored (squashed) action via the
# inverse tanh — the standard PPO-with-tanh approach.

_LOG2 = jnp.log(2.0)


def _gaussian_logprob(raw, mean, log_std):
    std = jnp.exp(log_std)
    pre = -0.5 * (((raw - mean) / std) ** 2) - log_std - 0.5 * jnp.log(2.0 * jnp.pi)
    return jnp.sum(pre, axis=-1)


def _tanh_correction(raw):
    # log|d tanh/d raw| = log(1 - tanh(raw)^2); numerically stable form.
    return jnp.sum(2.0 * (_LOG2 - raw - jax.nn.softplus(-2.0 * raw)), axis=-1)


def sample_action(mean, log_std, key):
    """Sample a squashed action; return (action, log_prob)."""
    std = jnp.exp(log_std)
    eps = jax.random.normal(key, mean.shape)
    raw = mean + std * eps
    action = jnp.tanh(raw)
    log_prob = _gaussian_logprob(raw, mean, log_std) - _tanh_correction(raw)
    return action, log_prob


def log_prob_of(mean, log_std, action):
    """Log-prob of a previously taken (squashed) action under (mean, log_std)."""
    raw = jnp.arctanh(jnp.clip(action, -1.0 + 1e-6, 1.0 - 1e-6))
    return _gaussian_logprob(raw, mean, log_std) - _tanh_correction(raw)


def make_inference_fn(model: ActorCritic):
    """Return ``policy(params, norms, obs, key, deterministic) -> action``.

    ``norms`` is ``{"actor": <norm state>, "critic": <norm state>}``.
    """

    def policy(params, norms, obs, key, deterministic: bool = True):
        a = norm_apply(norms["actor"], get_actor_obs(obs))
        c = norm_apply(norms["critic"], get_critic_obs(obs))
        mean, log_std, _ = model.apply(params, a, c)
        if deterministic:
            return jnp.tanh(mean)
        action, _ = sample_action(mean, log_std, key)
        return action

    return policy
