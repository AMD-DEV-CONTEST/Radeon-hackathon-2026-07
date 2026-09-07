"""From-scratch single-GPU PPO for MuJoCo Playground locomotion envs.

Why this exists: brax's stock PPO trainer segfaults in ``libhsa-runtime64``
on this gfx1100 + jax-rocm7 stack — its pmap-over-scan training step hits a
ROCm runtime bug (see docs/ROCM_BUG_REPORT.md (Root Cause Analysis)). This trainer reproduces the
same PPO algorithm using ONLY ``jax.jit`` on a single device: no ``pmap``, no
cross-device collectives, no ``device_put_replicated``. That is precisely the
code path proven to run on this GPU (env reset/step/vmap are known-good), so
it side-steps the crash instead of gambling on an upstream fix.

Structure matches Playground's tuned Go1 config (verified on the instance):
an asymmetric actor-critic (policy sees ``state``, critic sees
``privileged_state``) with running observation normalization. It fits the
track's theme directly: a *lightweight, low-latency* Physical AI policy
hand-built for a single AMD Radeon GPU.

Example:
    python -m src.train_jax_ppo --env Go1JoystickFlatTerrain --seed 0
    # quick pipeline check (few iterations):
    python -m src.train_jax_ppo --num-timesteps 200000

NOTE: authored on a machine without a GPU/JAX (network-restricted), so it is
validated by byte-compile + careful review only. Run it on the Radeon instance
with SMOKE first; iterate there. See docs/ROCM_BUG_REPORT.md.
"""
from __future__ import annotations

import argparse
import functools
import json
import pickle
import time

from src import config as C

C.set_headless_render_defaults()

import jax  # noqa: E402
import jax.numpy as jnp  # noqa: E402
import optax  # noqa: E402
from mujoco_playground import registry  # noqa: E402
from mujoco_playground import wrapper as pg_wrapper  # noqa: E402

from src import nets as N  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Single-GPU jit PPO on Playground envs.")
    p.add_argument("--env", default=C.DEFAULT_ENV)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--num-timesteps", type=int, default=50_000_000,
                   help="Total env steps. Use ~200000 for a smoke test.")
    p.add_argument("--num-envs", type=int, default=2048,
                   help="Parallel MJX envs (vmap). Lower if VRAM-bound.")
    p.add_argument("--unroll-length", type=int, default=20,
                   help="Steps collected per env per PPO iteration.")
    p.add_argument("--iters-per-chunk", type=int, default=4,
                   help="PPO iters folded into ONE scan dispatch. Each chunk is "
                        "one compiled dispatch; a checkpoint is saved after every "
                        "chunk so training resumes across the ROCm HSA segfault. "
                        "Keep small enough that one dispatch stays in the stable "
                        "region for the chosen --num-envs (see docs/ROCM_BUG_REPORT.md).")
    p.add_argument("--resume", action="store_true",
                   help="Resume from the latest checkpoint for this env/seed if "
                        "present, continuing the step count and metrics log.")
    p.add_argument("--num-minibatches", type=int, default=32)
    p.add_argument("--num-epochs", type=int, default=4,
                   help="PPO update epochs per batch of rollout data.")
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--entropy-cost", type=float, default=1e-2)
    p.add_argument("--discounting", type=float, default=0.97)
    p.add_argument("--gae-lambda", type=float, default=0.95)
    p.add_argument("--clip-eps", type=float, default=0.2)
    p.add_argument("--max-grad-norm", type=float, default=1.0)
    p.add_argument("--reward-scaling", type=float, default=1.0)
    p.add_argument("--policy-hidden", type=int, nargs="+", default=[512, 256, 128])
    p.add_argument("--value-hidden", type=int, nargs="+", default=[512, 256, 128])
    p.add_argument("--allow-cpu", action="store_true",
                   help="Do not hard-fail on CPU (local dry runs only).")
    return p.parse_args()


# --- Rollout / advantage math (all pure jax, jit-able) -----------------------

def _rollout(env, model, params, norms, state, key, unroll_length, reward_scaling):
    """Collect ``unroll_length`` steps across the vmapped envs via lax.scan.

    Observations are normalized with the (frozen-this-iteration) ``norms``
    stats before hitting the network. Returns per-step tensors shaped
    (unroll_length, num_envs, ...), the trailing state (to bootstrap the value
    target), and the raw actor/critic obs (for updating the normalizer).
    """

    def step_fn(carry, _):
        state, key = carry
        key, akey = jax.random.split(key)
        actor_obs = N.get_actor_obs(state.obs)
        critic_obs = N.get_critic_obs(state.obs)
        mean, log_std, value = model.apply(
            params,
            N.norm_apply(norms["actor"], actor_obs),
            N.norm_apply(norms["critic"], critic_obs),
        )
        action, log_prob = N.sample_action(mean, log_std, akey)
        nstate = env.step(state, action)
        transition = {
            "actor_obs": actor_obs,
            "critic_obs": critic_obs,
            "action": action,
            "log_prob": log_prob,
            "value": value,
            "reward": nstate.reward * reward_scaling,
            "done": nstate.done,
        }
        return (nstate, key), transition

    (state, key), data = jax.lax.scan(
        step_fn, (state, key), None, length=unroll_length
    )
    # Bootstrap value for the final state (critic obs, normalized).
    _, _, last_value = model.apply(
        params,
        N.norm_apply(norms["actor"], N.get_actor_obs(state.obs)),
        N.norm_apply(norms["critic"], N.get_critic_obs(state.obs)),
    )
    return state, key, data, last_value


def _compute_gae(data, last_value, discounting, gae_lambda):
    """Generalized advantage estimation over the (T, num_envs) rollout."""
    rewards = data["reward"]
    values = data["value"]
    dones = data["done"]

    def scan_fn(carry, xs):
        adv, next_value = carry
        reward, value, done = xs
        nonterminal = 1.0 - done
        delta = reward + discounting * next_value * nonterminal - value
        adv = delta + discounting * gae_lambda * nonterminal * adv
        return (adv, value), adv

    init = (jnp.zeros_like(last_value), last_value)
    _, advantages = jax.lax.scan(
        scan_fn,
        init,
        (rewards, values, dones),
        reverse=True,
    )
    returns = advantages + values
    return advantages, returns


def _ppo_loss(params, model, norms, batch, clip_eps, entropy_cost):
    # Obs are already normalized (done once per iteration before minibatching).
    mean, log_std, value = model.apply(params, batch["actor_obs"], batch["critic_obs"])
    new_log_prob = N.log_prob_of(mean, log_std, batch["action"])

    ratio = jnp.exp(new_log_prob - batch["log_prob"])
    adv = batch["advantage"]
    adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    unclipped = ratio * adv
    clipped = jnp.clip(ratio, 1.0 - clip_eps, 1.0 + clip_eps) * adv
    policy_loss = -jnp.mean(jnp.minimum(unclipped, clipped))

    value_loss = 0.5 * jnp.mean((value - batch["return"]) ** 2)

    # Gaussian entropy (pre-tanh) — cheap, standard exploration bonus.
    entropy = jnp.mean(jnp.sum(log_std + 0.5 * jnp.log(2.0 * jnp.pi * jnp.e), axis=-1))

    total = policy_loss + 0.5 * value_loss - entropy_cost * entropy
    metrics = {
        "policy_loss": policy_loss,
        "value_loss": value_loss,
        "entropy": entropy,
    }
    return total, metrics


def _make_update_fn(env, model, optimizer, args):
    """Build the jit-compiled per-iteration update: rollout -> GAE -> epochs.

    Everything inside runs on the single device under jit — no pmap.
    """
    grad_fn = jax.value_and_grad(_ppo_loss, has_aux=True)

    def update(params, opt_state, norms, state, key):
        # Rollout uses the current (start-of-iter) normalizer stats.
        state, key, data, last_value = _rollout(
            env, model, params, norms, state, key,
            args.unroll_length, args.reward_scaling,
        )
        advantages, returns = _compute_gae(
            data, last_value, args.discounting, args.gae_lambda
        )

        # Update running obs normalizer from this iteration's rollout, then
        # normalize once here so the epoch loop works on standardized inputs.
        norms = {
            "actor": N.norm_update(norms["actor"], data["actor_obs"]),
            "critic": N.norm_update(norms["critic"], data["critic_obs"]),
        }

        def flat(x):
            return x.reshape((-1,) + x.shape[2:])

        flat_batch = {
            "actor_obs": N.norm_apply(norms["actor"], flat(data["actor_obs"])),
            "critic_obs": N.norm_apply(norms["critic"], flat(data["critic_obs"])),
            "action": flat(data["action"]),
            "log_prob": flat(data["log_prob"]),
            "advantage": flat(advantages),
            "return": flat(returns),
        }
        batch_size = flat_batch["action"].shape[0]
        mb_size = batch_size // args.num_minibatches

        def epoch_fn(carry, ekey):
            params, opt_state = carry
            perm = jax.random.permutation(ekey, batch_size)

            def mb_fn(carry, idx):
                params, opt_state = carry
                sl = jax.lax.dynamic_slice_in_dim(perm, idx * mb_size, mb_size)
                mb = {k: v[sl] for k, v in flat_batch.items()}
                (loss, metrics), grads = grad_fn(
                    params, model, norms, mb, args.clip_eps, args.entropy_cost
                )
                updates, opt_state = optimizer.update(grads, opt_state, params)
                params = optax.apply_updates(params, updates)
                metrics["loss"] = loss
                return (params, opt_state), metrics

            (params, opt_state), metrics = jax.lax.scan(
                mb_fn, (params, opt_state), jnp.arange(args.num_minibatches)
            )
            return (params, opt_state), metrics

        keys = jax.random.split(key, args.num_epochs + 1)
        key = keys[0]
        (params, opt_state), metrics = jax.lax.scan(
            epoch_fn, (params, opt_state), keys[1:]
        )
        # Mean over epochs/minibatches; plus rollout reward for logging.
        metrics = jax.tree_util.tree_map(jnp.mean, metrics)
        metrics["rollout_reward"] = jnp.mean(data["reward"])
        return params, opt_state, norms, state, key, metrics

    return update


def _make_train_fn(env, model, optimizer, args, iters_per_chunk):
    """Fold ONE CHUNK of training iters into a single jax.lax.scan dispatch.

    On this gfx1100 + jax-rocm7 stack, kernel launches are intercepted by a
    rocprofiler-sdk statically linked into xla_rocm_plugin, and forwarding into
    HSA hits a nondeterministic segfault whose probability grows with both the
    size of a single dispatch (total while-loop iterations) AND the number of
    dispatches (see docs/ROCM_BUG_REPORT.md). Neither a giant single scan (crashes at
    1024+ envs) nor a long Python re-dispatch loop is safe on its own.

    The chunk is the compromise: fold ``iters_per_chunk`` iters into one scan so
    a chunk is a single dispatch of bounded size, and drive chunks from a Python
    loop in main() that saves a full checkpoint after each. If a chunk segfaults,
    the outer shell restarts and --resume continues from the last checkpoint, so
    total training progress accumulates across crashes. Per-iter metrics are
    stacked as the scan's ys and returned for host-side logging.
    """
    update = _make_update_fn(env, model, optimizer, args)

    def train(params, opt_state, norms, state, key):
        def scan_step(carry, _):
            params, opt_state, norms, state, key = carry
            params, opt_state, norms, state, key, metrics = update(
                params, opt_state, norms, state, key
            )
            return (params, opt_state, norms, state, key), metrics

        (params, opt_state, norms, state, key), metrics = jax.lax.scan(
            scan_step, (params, opt_state, norms, state, key), None,
            length=iters_per_chunk,
        )
        return params, opt_state, norms, state, key, metrics

    return jax.jit(train)


def _save_checkpoint(path, payload) -> None:
    # Write to a temp file then atomically rename, so a segfault mid-write can
    # never corrupt the checkpoint we resume from.
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(payload, f)
    tmp.replace(path)


def _load_checkpoint(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def main() -> None:
    args = parse_args()
    C.ensure_dirs()
    C.assert_gpu(require=not args.allow_cpu)

    env_name = args.env
    print(f"[train_jax_ppo] env={env_name} seed={args.seed} num_envs={args.num_envs}")

    # Force the classic JAX/XLA MJX backend (Warp backend unavailable on ROCm).
    env_cfg = registry.get_default_config(env_name)
    if "impl" in env_cfg:
        with env_cfg.unlocked():
            env_cfg.impl = "jax"
    env = registry.load(env_name, config=env_cfg)
    episode_length = env._config.episode_length

    key = jax.random.PRNGKey(args.seed)
    key, init_key, reset_key, randomize_key = jax.random.split(key, 4)

    # Playground's domain randomizer has signature (model, rng); the training
    # wrapper only calls it as randomization_fn(model). Bind a per-env batch of
    # rng keys via partial first — this mirrors what brax's train.py does before
    # handing the fn to the wrapper. get_domain_randomizer may return None for
    # envs without randomization; pass it through unchanged in that case.
    domain_randomizer = registry.get_domain_randomizer(env_name)
    if domain_randomizer is not None:
        randomization_fn = functools.partial(
            domain_randomizer,
            rng=jax.random.split(randomize_key, args.num_envs),
        )
    else:
        randomization_fn = None

    # Brax-style training wrappers (episode reset / auto-reset / obs) — the
    # Playground helper, same one used by the brax path. Pure vmap, no pmap.
    env = pg_wrapper.wrap_for_brax_training(
        env,
        episode_length=episode_length,
        action_repeat=1,
        randomization_fn=randomization_fn,
    )

    model = N.ActorCritic(
        action_size=env.action_size,
        policy_hidden=tuple(args.policy_hidden),
        value_hidden=tuple(args.value_hidden),
    )
    reset_keys = jax.random.split(reset_key, args.num_envs)
    # wrap_for_brax_training already includes a VmapWrapper: reset takes a
    # BATCH of keys and vmaps internally. Do NOT add another jax.vmap here
    # (that double-vmaps and breaks shapes). This mirrors brax's own train.py.
    state = jax.jit(env.reset)(reset_keys)

    # Init network from a single (unbatched) example of each obs stream.
    actor_obs = N.get_actor_obs(state.obs)
    critic_obs = N.get_critic_obs(state.obs)
    params = model.init(init_key, actor_obs[0], critic_obs[0])
    norms = {
        "actor": N.norm_init(actor_obs.shape[-1]),
        "critic": N.norm_init(critic_obs.shape[-1]),
    }
    print(f"[train_jax_ppo] actor_obs={actor_obs.shape[-1]} "
          f"critic_obs={critic_obs.shape[-1]} action={env.action_size} "
          f"episode_length={episode_length}")

    optimizer = optax.chain(
        optax.clip_by_global_norm(args.max_grad_norm),
        optax.adam(args.learning_rate),
    )
    opt_state = optimizer.init(params)

    steps_per_iter = args.num_envs * args.unroll_length
    num_iters = max(1, args.num_timesteps // steps_per_iter)
    iters_per_chunk = min(args.iters_per_chunk, num_iters)
    num_chunks = (num_iters + iters_per_chunk - 1) // iters_per_chunk
    # scan length must be static, so build the chunk fn with the concrete count.
    train_fn = _make_train_fn(env, model, optimizer, args, iters_per_chunk)

    ckpt_path = C.CKPT_DIR / f"{env_name}_seed{args.seed}.pkl"
    metrics_path = C.LOG_DIR / f"{env_name}_seed{args.seed}_metrics.json"

    def _ckpt_payload(params, norms, opt_state, iters_done):
        # opt_state + iters_done let --resume continue training exactly; params +
        # norms + meta are what eval/render load (extra keys are ignored there).
        return {
            "params": params,
            "norms": norms,
            "opt_state": opt_state,
            "iters_done": iters_done,
            "meta": {
                "env": env_name,
                "action_size": int(env.action_size),
                "policy_hidden": list(args.policy_hidden),
                "value_hidden": list(args.value_hidden),
            },
        }

    iters_done = 0
    metrics_log: list[dict] = []
    if args.resume and ckpt_path.exists():
        ck = _load_checkpoint(ckpt_path)
        params = ck["params"]
        norms = ck["norms"]
        if ck.get("opt_state") is not None:
            opt_state = ck["opt_state"]
        iters_done = int(ck.get("iters_done", 0))
        if metrics_path.exists():
            metrics_log = json.loads(metrics_path.read_text())
        print(f"[train_jax_ppo] resumed from {ckpt_path} at iter {iters_done}")

    print(f"[train_jax_ppo] {steps_per_iter:,} steps/iter x {num_iters} iters "
          f"= {num_chunks} chunks of {iters_per_chunk} "
          f"(~{steps_per_iter * num_iters:,} env steps)")
    print("[train_jax_ppo] training: one scan dispatch per chunk, checkpoint after each")

    t0 = time.time()
    chunk_start = iters_done // iters_per_chunk
    for chunk in range(chunk_start, num_chunks):
        tc = time.time()
        # ONE dispatch for this chunk (a scan of iters_per_chunk iters). Bounded
        # size keeps it in the stable region; the outer loop re-dispatches a
        # fresh chunk each time, and --resume recovers if one segfaults.
        params, opt_state, norms, state, key, stacked = train_fn(
            params, opt_state, norms, state, key
        )
        stacked = jax.tree_util.tree_map(lambda x: x.tolist(), stacked)
        for j in range(iters_per_chunk):
            it = chunk * iters_per_chunk + j
            if it >= num_iters:
                break
            total_steps = steps_per_iter * (it + 1)
            row = {"iter": it, "steps": total_steps}
            for k, v in stacked.items():
                row[k] = float(v[j])
            metrics_log.append(row)
        iters_done = min((chunk + 1) * iters_per_chunk, num_iters)
        # Persist after every chunk so a later segfault costs at most one chunk.
        _save_checkpoint(ckpt_path, _ckpt_payload(params, norms, opt_state, iters_done))
        metrics_path.write_text(json.dumps(metrics_log, indent=2))
        last = metrics_log[-1]
        sps = (iters_per_chunk * steps_per_iter) / max(1e-9, time.time() - tc)
        print(f"[train_jax_ppo] chunk {chunk + 1}/{num_chunks} "
              f"iter={last['iter']:>5} steps={last['steps']:>12,} "
              f"reward={last.get('rollout_reward', float('nan')):8.4f} "
              f"loss={last.get('loss', float('nan')):8.4f} {sps:,.0f} steps/s")

    print(f"[train_jax_ppo] done in {time.time() - t0:.1f}s ({iters_done}/{num_iters} iters)")
    print(f"[train_jax_ppo] checkpoint -> {ckpt_path}")
    print(f"[train_jax_ppo] metrics    -> {metrics_path}")


if __name__ == "__main__":
    main()
