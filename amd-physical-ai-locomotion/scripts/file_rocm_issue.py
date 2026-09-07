#!/usr/bin/env python3
"""
ROCm bug report generator — run this on the AMD Radeon instance.

Collects environment evidence (JAX version, ROCm version, ldd output)
and prints a ready-to-post GitHub issue in markdown format.

Usage:
    python3 scripts/file_rocm_issue.py           # print issue markdown
    python3 scripts/file_rocm_issue.py --save    # save to outputs/ROCM_ISSUE.md

Dependencies: none beyond standard library + jax.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], timeout=15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"<error: {e}>"


def get_jax_info() -> dict:
    info = {}
    try:
        import jax
        info["version"] = jax.__version__
        info["devices"] = str(jax.devices())
        info["backend"] = str(jax.default_backend())
        # Try to get plugin path
        try:
            import jax._src.xla_bridge as xb
            backend = xb.get_backend()
            if hasattr(backend, 'platform'):
                info["platform"] = backend.platform
        except Exception:
            pass
    except Exception as e:
        info["error"] = str(e)
    return info


def get_plugin_ldd() -> str:
    """Find xla_rocm_plugin.so and run ldd on it."""
    import site
    for d in site.getsitepackages():
        plugin_dir = Path(d) / "jax_plugins" / "xla_rocm7"
        for so in plugin_dir.rglob("*.so"):
            if "plugin" in so.name:
                out = run(["ldd", str(so)])
                return f"# ldd {so}\n{out}"
        # also check xla_rocm60
        plugin_dir2 = Path(d) / "jax_plugins" / "xla_rocm60"
        for so in plugin_dir2.rglob("*.so"):
            if "plugin" in so.name:
                out = run(["ldd", str(so)])
                return f"# ldd {so}\n{out}"
    return "<xla_rocm_plugin.so not found in site-packages>"


def get_rocm_version() -> str:
    v = run(["cat", "/opt/rocm/.info/version"])
    if not v or v.startswith("<error"):
        v = run(["rocm-smi", "--showdriverversion"])
    return v or "<unknown>"


def get_env_grep() -> str:
    out = run(["env"], timeout=5)
    lines = [l for l in out.split("\n") if any(
        x in l.upper() for x in ["ROCPROF", "HSA_TOOL", "ROCM", "HIP"]
    )]
    return "\n".join(lines) if lines else "(none)"


def format_issue(jax_info, ldd_out, rocm_ver, env_grep) -> str:
    title = (
        "Bug: xla_rocm7 plugin statically links rocprofiler-sdk, "
        "causing non-deterministic segfault in libhsa-runtime64 on gfx1100"
    )

    body = f"""## Environment

| Component | Value |
|-----------|-------|
| GPU | AMD Radeon gfx1100 (48 GB VRAM) |
| ROCm | {rocm_ver} |
| JAX | {jax_info.get('version', '?')} |
| Devices | {jax_info.get('devices', '?')} |
| Python | {platform.python_version()} |
| OS | {platform.system()} {platform.release()} |

## Description

JAX GPU training (via `jax.jit` + `lax.scan`) crashes with `SIGNAL SEGV` in a
non-deterministic fashion inside `libhsa-runtime64.so.1` **after**
`librocprofiler-sdk.so.1` intercepts a kernel launch. The same code succeeds
some runs and crashes others — it is a **race condition** in the profiler
injection path.

## Evidence: rocgdb stack trace

```
Thread ... received signal SIGSEGV
#0  0x0000000100000001 in ?? ()
#1  libhsa-runtime64.so.1
#2  libhsa-runtime64.so.1
#3  libamdhip64.so.7
...
#9  librocprofiler-sdk.so.1              ← profiler intercepts kernel launch
#10 librocprofiler-sdk.so.1
#11 LaunchRocmKernel (xla_rocm_plugin.so)
...
#17 WhileThunk (nested training loop)
```

## Evidence: ldd output (rocprofiler-sdk is a direct NEEDED dependency)

```
{ldd_out}
```

## Evidence: env vars

```
{env_grep}
```

## Approaches tried — all ineffective

| Approach | Result |
|----------|--------|
| `unset HSA_TOOLS_LIB` / `ROCP_TOOL_LIB` / `ROCPROFILER_DISABLE=1` | ❌ Still crashes |
| `XLA_FLAGS=--xla_gpu_enable_command_buffer=` (open/close/WHILE) | ❌ Still crashes |
| `XLA_FLAGS=--xla_gpu_autotune_level=0` | ❌ Still crashes |
| `--xla_gpu_triton_gemm=false` / `--xla_gpu_latency_hiding_scheduler=false` | ❌ Still crashes |
| Reducing batch size / env count | ❌ Race condition persists |
| `patchelf --remove-needed librocprofiler-sdk.so.1` | ❌ `undefined symbol: rocprofiler_force_configure` → JAX falls back to CPU |
| Uninstalling rocprofiler-sdk system package | ❌ Irreversible — destroys JAX GPU capability entirely |

## Root cause

`xla_rocm_plugin.so` has rocprofiler-sdk as a dynamic NEEDED dependency.
At load time, rocprofiler-sdk registers via GOTCHA to intercept every HIP
kernel launch. On gfx1100, the injection into libhsa-runtime64 has a race
condition that jumps to an unmapped address.

The profiler **cannot be disabled** because it is a compile-time dependency,
not loaded via `HSA_TOOLS_LIB`.

## Suggested fix

Remove the `DT_NEEDED` dependency on `librocprofiler-sdk.so.1` from the
xla_rocm7 plugin build. If profiling support is desired, load it dynamically
at user request (e.g., via `dlopen`), not at build time.

Or: provide a jax-rocm7-plugin variant **without** rocprofiler-sdk linkage
for production workloads.

## Reproduction

```bash
# On any ROCm 7.x + JAX 0.11 + gfx1100 instance:
pip install mujoco mujoco-mjx "brax>=0.14.0" playground
git clone https://github.com/istics1998/Radeon-hackathon-2026-07
cd Radeon-hackathon-2026-07/amd-physical-ai-locomotion
export MUJOCO_GL=osmesa PYTHONPATH="$PWD"
python3 scripts/repro_hsa_segfault.py        # ~30s, may need 2-3 tries
# Or stress test:
python3 scripts/gpu_stress.py
```
"""

    return title, body


def main():
    parser = argparse.ArgumentParser(description="Generate ROCm bug report")
    parser.add_argument("--save", action="store_true",
                        help="Save to outputs/ROCM_ISSUE.md instead of printing")
    args = parser.parse_args()

    print("[file_rocm_issue] Gathering environment info ...", file=sys.stderr)

    jax_info = get_jax_info()
    ldd_out = get_plugin_ldd()
    rocm_ver = get_rocm_version()
    env_grep = get_env_grep()

    title, body = format_issue(jax_info, ldd_out, rocm_ver, env_grep)

    if args.save:
        out_dir = Path("outputs")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "ROCM_ISSUE.md"
        with open(out_path, "w") as f:
            f.write(f"# {title}\n\n")
            f.write(body)
        print(f"✅ Saved to {out_path}", file=sys.stderr)
        print(f"   Copy-paste to: https://github.com/ROCm/ROCm/issues/new", file=sys.stderr)
    else:
        print(f"=== TITLE ===\n{title}\n")
        print(f"=== BODY ===\n{body}")


if __name__ == "__main__":
    main()
