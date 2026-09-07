# ROCm Bug Report: Non-deterministic segfault in `libhsa-runtime64` caused by `rocprofiler-sdk` static linkage in `xla_rocm7` plugin

> **Summary**: The `jax-rocm7-plugin` (`xla_rocm_plugin.so`) statically links
> `librocprofiler-sdk.so.1` via NEEDED entry. The profiler intercepts **every**
> HIP kernel launch via GOTCHA hooks, forwarding into `libhsa-runtime64` where it
> causes a **non-deterministic segfault** on gfx1100. The crash cannot be
> disabled via environment variables (since it is a compile-time dependency), nor
> can it be removed via `patchelf` (hard symbol dependency on
> `rocprofiler_force_configure`). This blocks all serious JAX-based GPU workloads
> on affected stacks.

---

## Environment

| Component | Version |
|-----------|---------|
| GPU | AMD Radeon gfx1100 (48 GB VRAM) |
| ROCm | 7.2.1 |
| JAX | 0.11.0 |
| jax-rocm7-plugin | 0.11.0 |
| jax-rocm7-pjrt | 0.11.0 |
| Python | 3.12.3 |
| OS | Ubuntu 22.04 (container) |

## Bug Description

JAX GPU training (via `jax.jit` + `lax.scan`) crashes with `SIGNAL SEGV` in a
non-deterministic fashion. The crash occurs inside `libhsa-runtime64.so.1`
**after** `librocprofiler-sdk.so.1` intercepts a kernel launch. The same code
succeeds some runs and crashes others — it is a **race condition** in the
profiler injection path, not a deterministic logic error.

### rocgdb Stack Trace (captured live)

```
Thread ... received signal SIGSEGV
#0  0x0000000100000001 in ?? ()                          ← jumps to invalid address
#1  libhsa-runtime64.so.1
#2  libhsa-runtime64.so.1
#3  libamdhip64.so.7
#4  libamdhip64.so.7
#5  libamdhip64.so.7
#6  libamdhip64.so.7
#7  libamdhip64.so.7
#8  libamdhip64.so.7
#9  librocprofiler-sdk.so.1                              ← profiler intercepts launch
#10 librocprofiler-sdk.so.1
#11 LaunchRocmKernel (xla_rocm_plugin.so)
#12 RocmStream::Launch (xla_rocm_plugin.so)
#13 RocmKernel::Launch (xla_rocm_plugin.so)
#14 CustomKernelThunk::ExecuteOnStream (xla_rocm_plugin.so)
#15 ThunkExecutor::ExecuteOnStream
#16 ExecutionStreamAssignmentConcat
#17 WhileThunk (nested training loop inside lax.scan)
#18 WhileThunk
#19 ForThunk
#20 WhileThunk
#21 GpuExecutable::ExecuteThunks
```

A clean path would descend directly `LaunchRocmKernel → libamdhip64.so.7`
without frames #9-#10.

### Evidence: `ldd` shows rocprofiler-sdk is a direct dependency

```bash
$ ldd /usr/local/lib/python3.12/dist-packages/jax_plugins/xla_rocm7/xla_rocm_plugin.so | grep rocprof
librocprofiler-sdk.so.1 => /opt/rocm/lib/librocprofiler-sdk.so.1
librocprofiler-register.so.0 => /opt/rocm/lib/librocprofiler-register.so.0
```

The GOTCHA-based intercept mechanism is present at:
```
/opt/rocm/lib/rocprofiler-sdk/libgotcha.so
```

### Tools -> Causes Segfault

| Approach | Result |
|----------|--------|
| `unset HSA_TOOLS_LIB` | ❌ Still crashes (profiler loaded via NEEDED, not env var) |
| `unset ROCP_TOOL_LIB` | ❌ Still crashes |
| `ROCPROFILER_REGISTER_FORCE_LOAD=0` | ❌ Still crashes |
| `ROCPROFILER_DISABLE=1` | ❌ Still crashes |
| `XLA_FLAGS=--xla_gpu_enable_command_buffer=` | ❌ Still crashes |
| `XLA_FLAGS=--xla_gpu_enable_command_buffer=...,WHILE` | ❌ Still crashes |
| `XLA_FLAGS=--xla_gpu_autotune_level=0` | ❌ Still crashes |
| `XLA_FLAGS=--xla_gpu_triton_gemm=false` | ❌ Still crashes |
| `--xla_gpu_latency_hiding_scheduler=false` | ❌ Still crashes |
| Reducing batch size / env count | ❌ Race condition persists |
| `patchelf --remove-needed librocprofiler-sdk.so.1` | ❌ Undefined symbol `rocprofiler_force_configure` → JAX falls back to CPU |
| Uninstalling `rocprofiler-sdk` package | ❌ Irreversible — destroys JAX GPU capability entirely |

## Root Cause Analysis

1. **`xla_rocm_plugin.so`** has `librocprofiler-sdk.so.1` as a dynamic NEEDED
   dependency (visible in `ldd` output). This is not a soft/optional link — the
   plugin calls `rocprofiler_force_configure` and other symbols from
   rocprofiler-sdk.

2. **rocprofiler-sdk** registers itself via GOTCHA to intercept every HIP kernel
   launch. This is by design: it injects before `libamdhip64` to profile GPU
   activity.

3. **On gfx1100**, the profiler injection path into `libhsa-runtime64` has a
   **race condition** that sometimes jumps to an unmapped address (`0x0000000100000001`).
   This address pattern suggests a corrupted function pointer or vtable.

4. The crash is **non-deterministic**: same binary, same input, same configuration
   — one run crashes, the next succeeds. This rules out a simple buffer overflow
   or memory exhaustion and confirms a **timing-dependent race** in the profiler
   initialization or dispatch path.

5. The crash probability correlates with:
   - **Number of dispatched kernels** (more kernel launches = more chances to hit the race)
   - **Nesting depth of `lax.scan` while loops** (deeper nesting = more state transitions in HSA)
   - But **never zero**: even a single chunk of 256 envs × 20 unroll steps can crash.

## Impact

- **Any JAX-based GPU training is blocked** when the workload involves repeated
  kernel launches via `lax.scan`, `jax.jit` loops, or similar patterns.
- Single-shot inference (one forward pass) generally succeeds, but any iterative
  GPU compute that dispatches many kernels is at risk.
- Environment variable workarounds are ineffective because the profiler is loaded
  via `DT_NEEDED`, not via `HSA_TOOLS_LIB`.
- The crash is **not specific to RL or PPO**: it affects any JAX program that
  dispatches many kernels on the GPU (e.g., training loops, batched inference).
- Simple operations (matrix multiply, env.step alone) work fine.

## Steps to Reproduce

```bash
# 1. Set up environment (assumes ROCm 7.2.1 + JAX 0.11.0 + jax-rocm7-plugin 0.11.0)
export MUJOCO_GL=osmesa

# 2. Install dependencies
pip install mujoco mujoco-mjx "brax>=0.14.0" playground mediapy

# 3. Run the reproduction script (30-60 seconds; may need 2-3 attempts to hit the race)
python3 scripts/repro_hsa_segfault.py

# 4. Or use the stress test (runs many kernel launches in a loop)
python3 scripts/gpu_stress.py

# 5. Capture backtrace on crash:
rocgdb -q -batch -ex run -ex bt -ex quit --args python3 scripts/gpu_stress.py 2>&1 | tail -60
```

## Expected vs Actual Behavior

**Expected**: JAX GPU training runs to completion without crashes.

**Actual**: Non-deterministic segfault in `libhsa-runtime64` after rocprofiler
intercepts kernel launch. Same code sometimes succeeds, sometimes crashes.

## Suggested Fix

1. Remove the `DT_NEEDED` dependency on `librocprofiler-sdk.so.1` from
   `xla_rocm_plugin.so` in the jax-rocm7-plugin build. If profiling support is
   desired, it should be **dynamically loaded at user request** (e.g., via
   `dlopen`), not linked at build time.

2. Alternatively, debug the race condition in GOTCHA → HSA path on gfx1100 so
   that profiler injection is thread-safe.

3. Short-term: provide a `jax-rocm7-plugin` variant **without** rocprofiler-sdk
   linkage for production workloads that don't need profiling.

## Attachments

- Full rocgdb transcript: see the "rocgdb Stack Trace" section above
- Minimal reproducer: [`scripts/repro_hsa_segfault.py`](../scripts/repro_hsa_segfault.py)
- GPU stress test: [`scripts/gpu_stress.py`](../scripts/gpu_stress.py)
