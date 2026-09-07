"""GPU kernel-launch stress probe — the fast, dependency-light reproducer for
the rocprofiler HSA-layer race (see docs/ROCM_BUG_REPORT.md, rocgdb Stack Trace).

Why this exists (separate from scripts/repro_hsa_segfault.py):
  * repro_hsa_segfault.py needs brax + mujoco_playground and runs a real PPO
    step — great as a final confirmation, slow to iterate.
  * This file is pure JAX. It hammers the SAME layer that crashes — the
    per-kernel-launch path that rocprofiler-sdk intercepts — using a deep
    ``lax.scan`` (nested WhileThunk, the shape rocgdb caught) PLUS a long loop
    of separate dispatches. That maximises both "single-dispatch while-body
    volume" and "number of dispatches", the two knobs §9.4 says drive the race.

It prints a single sentinel line ``STRESS_OK <token>`` iff it survives every
round. A segfault in libhsa-runtime64 kills the process before that line, so
the WRAPPER (scripts/pathA_profiler_free.sh) decides pass/fail by exit code +
sentinel, NOT by anything this script returns — a segfaulting process cannot
report its own death.

Tunables (env vars):
  STRESS_ROUNDS   how many independent dispatch rounds        (default 8)
  STRESS_SCAN     lax.scan length per round (while-body depth) (default 4096)
  STRESS_N        square matmul dimension                      (default 512)
  STRESS_TOKEN    sentinel token echoed on success             (default "ok")

Run directly on the instance:
    PYTHONPATH="$PWD" python3 scripts/gpu_stress.py
"""
from __future__ import annotations

import os
import sys

from src import config as C

C.set_headless_render_defaults()

import jax  # noqa: E402
import jax.numpy as jnp  # noqa: E402
from jax import lax  # noqa: E402


def _report_plugin_linkage() -> None:
    """Print which xla_rocm plugin is active and whether rocprofiler is loaded.

    This is the whole point of path A: after a fix, the ``ldd`` + /proc/maps
    lines below must show NO librocprofiler-sdk. We print it from inside the
    live process so it reflects what actually got mapped, not just static deps.
    """
    try:
        import importlib

        plug = None
        for name in ("jax_plugins.xla_rocm7", "jax_plugins.xla_rocm60"):
            try:
                plug = importlib.import_module(name)
                break
            except Exception:
                continue
        if plug is not None:
            print(f"[stress] plugin package: {os.path.dirname(plug.__file__)}")
    except Exception as e:  # pragma: no cover - diagnostic only
        print(f"[stress] plugin package lookup failed: {e}")

    # What rocprofiler libs are mapped into THIS live process?
    try:
        with open("/proc/self/maps") as fh:
            mapped = fh.read()
        hits = sorted(
            {
                line.split()[-1]
                for line in mapped.splitlines()
                if "rocprof" in line.lower() and line.split()[-1].startswith("/")
            }
        )
        if hits:
            print("[stress] rocprofiler libs MAPPED in live process:")
            for h in hits:
                print(f"           {h}")
        else:
            print("[stress] NO rocprofiler libs mapped in live process  <-- path A goal")
    except Exception as e:  # pragma: no cover - diagnostic only
        print(f"[stress] /proc/self/maps read failed: {e}")


def main() -> None:
    rounds = int(os.environ.get("STRESS_ROUNDS", "8"))
    scan_len = int(os.environ.get("STRESS_SCAN", "4096"))
    n = int(os.environ.get("STRESS_N", "512"))
    token = os.environ.get("STRESS_TOKEN", "ok")

    C.assert_gpu(require=True)
    print(f"[stress] jax {jax.__version__} devices={jax.devices()}")
    print(f"[stress] rounds={rounds} scan_len={scan_len} matmul_n={n}")
    _report_plugin_linkage()

    key = jax.random.PRNGKey(0)
    a = jax.random.normal(key, (n, n), dtype=jnp.float32)

    @jax.jit
    def deep_scan(mat: jnp.ndarray) -> jnp.ndarray:
        # A long lax.scan folds into a nested WhileThunk — the exact dispatch
        # shape rocgdb caught crashing (see docs/ROCM_BUG_REPORT.md). Each step launches
        # several kernels (matmul + elementwise), so the profiler intercepts
        # scan_len * k launches inside one dispatch.
        def body(carry, _):
            carry = jnp.tanh(carry @ mat) * 1.0001
            return carry, None

        out, _ = lax.scan(body, mat, xs=None, length=scan_len)
        return out.sum()

    # Warm up / compile once (compilation itself launches kernels).
    r = float(deep_scan(a).block_until_ready())
    print(f"[stress] warmup dispatch ok (checksum={r:.3f})")

    for i in range(rounds):
        # Fresh input each round so XLA cannot cache the result away; forces a
        # real GPU dispatch (many kernel launches) every iteration.
        a = jax.random.normal(jax.random.fold_in(key, i), (n, n), dtype=jnp.float32)
        r = float(deep_scan(a).block_until_ready())
        # Also a burst of small separate dispatches: maximises launch count.
        acc = a
        for _ in range(64):
            acc = (acc + 1.0) * 0.999
            acc.block_until_ready()
        print(f"[stress] round {i + 1}/{rounds} survived (checksum={r:.3f})", flush=True)

    # Reaching here means every kernel launch made it through the profiler
    # interception without a segfault.
    print(f"STRESS_OK {token}", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
