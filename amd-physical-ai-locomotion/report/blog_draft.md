# Blog / social draft — the ROCm profiler race that ate my quadruped RL run

> Draft copy for the "technical blog / tweet" bonus. Two versions: a short blog
> post (EN + 中文) and a tweet/thread. Swap in your real handles and the final
> repo/bug-report URLs before posting.

---

## Blog post (EN)

### Debugging a non-deterministic ROCm segfault in JAX quadruped RL

I spent the AMD Physical AI hackathon training a Unitree Go1 to walk with PPO on a
Radeon gfx1100 — MuJoCo Playground (MJX) for GPU-parallel physics, JAX for the
compute. The simulation ran. The PPO algorithm ran. And then, at random, training
would segfault inside `libhsa-runtime64.so.1`. Same code, same seed — crash on one
run, `EXIT=0` on the next.

Here's what it turned out to be. `jax-rocm7-plugin` (`xla_rocm_plugin.so`) links
`librocprofiler-sdk.so.1` as a **static NEEDED dependency** — you can see it in
`ldd`. That profiler installs GOTCHA hooks that intercept **every HIP kernel
launch**. On gfx1100, injecting those hooks into HSA has a non-deterministic race,
and under dispatch-heavy RL rollouts it eventually loses that race and segfaults.

What doesn't fix it:
- env vars — `HSA_TOOLS_LIB=`, `ROCP_TOOL_LIB=`, `ROCPROFILER_DISABLE=1`: no effect
- XLA flags — `command_buffer`, `autotune_level=0`, …: no effect
- `patchelf --remove-needed librocprofiler-sdk.so.1`: the plugin needs the
  `rocprofiler_force_configure` symbol, so it won't load
- uninstalling `rocprofiler-sdk`: irreversibly breaks JAX GPU support

What helped (partially): switching the trainer off Brax's `pmap` /
`device_put_replicated` path and onto a from-scratch single-GPU `jax.jit` +
`lax.scan` PPO. The replication path hit the race almost instantly; the single
device path survives long enough to produce real reward/loss and checkpoints — but
it doesn't escape the underlying bug.

The real fix belongs upstream: **rocprofiler-sdk should be dynamically loaded, not
statically linked into the XLA plugin.** Then RL workloads that never asked for
profiling wouldn't pay for its race condition. Full write-up with rocgdb stack and
ldd evidence: [ROCM_BUG_REPORT.md](../docs/ROCM_BUG_REPORT.md).

If you're doing JAX RL on Radeon and seeing random HSA segfaults, this is probably why.

### 中文版

我在 AMD Physical AI 黑客松里用 PPO + MuJoCo Playground (MJX) 在 Radeon gfx1100 上训练
宇树 Go1 行走。仿真能跑、PPO 也能跑，但训练会**随机**在 `libhsa-runtime64.so.1` 段错误——
同样的代码同样的种子，这次崩、下次 `EXIT=0`。

根因：`jax-rocm7-plugin` 把性能分析器 `librocprofiler-sdk.so.1` **静态链接**进了 XLA 插件
（`ldd` 里能看到）。它用 GOTCHA 钩子拦截**每一次** GPU kernel 发射，在 gfx1100 上注入 HSA 时
存在非确定性竞态，高频 dispatch 的 RL rollout 下迟早会崩。

试过都没用：环境变量（`HSA_TOOLS_LIB=` 等）、XLA flags、`patchelf` 摘依赖（插件需要
`rocprofiler_force_configure` 符号）、卸载 profiler（会破坏 JAX GPU）。唯一有帮助的是把训练器
从 brax 的 `pmap` 路径换成自写的单卡 `jax.jit` + `lax.scan` PPO——但只是活得更久，没根治。

真正的修法在上游：**rocprofiler-sdk 应该动态加载，而不是静态链接进 XLA 插件。** 完整证据
（rocgdb 栈 + ldd）：[ROCM_BUG_REPORT.md](../docs/ROCM_BUG_REPORT.md)。

---

## Tweet / thread

1/ Spent the @AMDDevCentral Physical AI hackathon training a quadruped (Unitree Go1)
to walk with PPO on a Radeon gfx1100 — JAX + MuJoCo Playground. Sim worked, PPO
worked… then random segfaults in libhsa-runtime64. 🧵

2/ Root cause: jax-rocm7-plugin statically links librocprofiler-sdk.so.1. The
profiler GOTCHA-hooks every HIP kernel launch, and on gfx1100 that HSA injection has
a non-deterministic race → random crashes under dispatch-heavy RL.

3/ Can't disable it: env vars, XLA flags, patchelf --remove-needed (needs
rocprofiler_force_configure), uninstalling rocprofiler-sdk (breaks JAX GPU). All
dead ends.

4/ Partial workaround: ditch brax's pmap/device_put_replicated trainer for a
from-scratch single-GPU jit + lax.scan PPO. Survives long enough to hit EXIT=0 with
real reward/loss + checkpoints — but doesn't escape the underlying bug.

5/ Real fix is upstream: rocprofiler-sdk should be *dynamically* loaded, not
statically linked into the XLA plugin. Full rocgdb + ldd write-up + repro in the
repo. #ROCm #JAX #PhysicalAI
