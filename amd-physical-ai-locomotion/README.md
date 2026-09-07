# AMD Physical AI — Quadruped Locomotion RL on Radeon (ROCm)
# AMD 物理 AI — 基于 Radeon (ROCm) 的四足机器狗运动控制强化学习

Track 3 (Physical AI) submission for the AMD AI DevMaster Hackathon.
赛道 3（物理 AI）— AMD AI DevMaster 黑客松参赛作品。

![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![ROCm](https://img.shields.io/badge/ROCm-7.2.1-red)
![JAX](https://img.shields.io/badge/JAX-0.11-blue)
![Python](https://img.shields.io/badge/Python-3.12-green)
![Platform](https://img.shields.io/badge/Platform-AMD%20Radeon%20gfx1100-orange)

🎥 [Demo Video on Bilibili / B 站演示视频](https://b23.tv/18MX3yY) · [ROCm Bug Report / Bug 报告](docs/ROCM_BUG_REPORT.md) · [技术博客 / Blog (知乎)](https://zhuanlan.zhihu.com/p/2063361463343912837)

Contents / 目录: [1. Overview / 项目简介](#1-overview--项目简介) · [2. Development / 开发过程](#2-development-process--challenges--开发过程与遇到的困难) · [3. Code Origin / 代码来源](#3-code-origin--contributions--代码来源与贡献) · [4. Team / 团队分工](#4-team--团队分工) · [5. Setup & Run / 安装与运行](#5-setup--run--安装与运行) · [6. Results / 运行结果](#6-results--运行结果) · [7. Demo / 演示视频](#7-demo-video--演示视频)

---

## 1. Overview / 项目简介

What this submission delivers: a **fully trained** Unitree Go1 joystick-locomotion policy — the demo video shows the real PPO policy walking, turning, and side-stepping under velocity commands, not a scripted or random rollout. Training reward climbed from ~0.001 to **23.9** over 62.26M environment steps. Plus a working GPU physics-simulation and rendering pipeline and a from-scratch single-GPU jit PPO implementation. The honest caveat: GPU training is blocked by a ROCm profiler-race runtime bug (details in section 2), so training was run **on CPU** through the same JAX/MJX stack — slower, but it converged.

本作品实际交付的是：一个**完整训练出来的**宇树 Go1 摇杆运动策略——演示视频展示的是真实 PPO 策略在按速度指令行走、转身、横移，而非脚本或随机 rollout。训练 reward 从约 0.001 上升到 **23.9**，历时 62.26M 环境步。此外还有一套可用的 GPU 物理仿真+渲染管线,以及从零实现的单卡 jit PPO。诚实说明：GPU 训练被一个 ROCm profiler 竞态运行时 bug 阻塞（详见第 2 节），因此训练是通过同一套 JAX/MJX 栈**在 CPU 上**完成的——更慢,但确实收敛了。

The intended goal was to train a Unitree Go1 quadruped to walk under joystick velocity commands (`Go1JoystickFlatTerrain`) using reinforcement learning (PPO) on an AMD Radeon GPU, with the whole pipeline on the GPU: physics simulated by the JAX backend of MuJoCo Playground (MJX) for GPU-parallel rollouts, and training by PPO. The GPU path was blocked by the ROCm profiler race below, so we fell back to running the identical JAX/MJX stack on CPU. What we verified: `scripts/00_verify_rocm.sh` passes 6/6 and the GPU is live (`RocmDevice`); the Go1 environment loads and the PPO trainer compiles and dispatches kernels on the GPU. What the GPU could not do: sustain a full training run — it segfaults inside the first `lax.scan` chunk (section 2). What we achieved on CPU instead: a complete 62.26M-step training run (275.7 min) with reward rising 0.001 → 13.4 (9.8M steps) → 23.9 (62.26M steps); 20 checkpoints saved; the final policy walks under command (demo in section 7).

项目原定目标是用强化学习（PPO）在 AMD Radeon GPU 上训练宇树 Go1 四足机器狗按摇杆速度指令行走（`Go1JoystickFlatTerrain`），全程 GPU：仿真用 MuJoCo Playground (MJX) 的 JAX 后端做 GPU 并行物理仿真。GPU 路径被下述 ROCm profiler 竞态阻塞，于是退回到用同一套 JAX/MJX 栈在 CPU 上跑。我们验证过的：`scripts/00_verify_rocm.sh` 通过 6/6、GPU 点亮（`RocmDevice`）；Go1 环境能加载，PPO 训练器能编译并在 GPU 上发射 kernel。GPU 做不到的：撑住一次完整训练——它在第一个 `lax.scan` chunk 里段错误（第 2 节）。我们改在 CPU 上达成的：一次完整的 62.26M 步训练（275.7 分钟），reward 从 0.001 → 13.4（9.8M 步）→ 23.9（62.26M 步）；保存 20 个 checkpoint；最终策略能按指令行走（演示见第 7 节）。

Problem, approach, metrics, stack / 问题、方法、指标、技术栈:

- Problem / 问题: velocity-command quadruped locomotion, a core Physical AI task. / 速度指令下的四足运动控制，Physical AI 的核心任务。
- Approach / 方法: GPU-parallel MJX simulation with a from-scratch single-GPU jit PPO. / GPU 并行 MJX 仿真 + 从零实现的单卡 jit PPO。
- Metric / 指标: mean episode reward under commanded velocity (equivalent to velocity-tracking error). Achieved **23.9** (up from ~0.001) over 62.26M environment steps. / 指令速度下的平均回合奖励（等价于速度跟踪误差）。62.26M 环境步达到 **23.9**（从约 0.001 起步）。
- Measured signals / 实测信号: GPU setup verified (`scripts/00_verify_rocm.sh` passes 6/6, `RocmDevice` detected); training completed on CPU (ROCm profiler bug blocked GPU training, see section 2); 20 checkpoints saved; reward curve recorded in `train.log`; final policy executes all commanded gaits (demo in section 7). / GPU 环境验证通过（`scripts/00_verify_rocm.sh` 6/6，`RocmDevice` 识别）；训练在 CPU 上完成（ROCm profiler bug 阻塞 GPU 训练，见第 2 节）；保存 20 个 checkpoint；reward 曲线记录于 `train.log`；最终策略执行所有指令步态（演示见第 7 节）。
- Stack / 技术栈: AMD Radeon gfx1100, ROCm 7.2.1, JAX 0.11, MuJoCo Playground (MJX), Flax, Optax, Python 3.12.

Why AMD: MJX runs through the XLA compiler via JAX, which supports AMD GPUs natively with no CUDA-only dependency. This project shows end-to-end GPU-parallel physics simulation and RL training on a single AMD Radeon GPU via ROCm, following the path in the [ROCm + JAX + MuJoCo blog](https://rocm.blogs.amd.com/artificial-intelligence/rocm-jax-mujoco/README.html).

为什么用 AMD：MJX 通过 JAX 的 XLA 编译器运行，原生支持 AMD GPU，无 CUDA 独占依赖。本项目在单张 AMD Radeon GPU 上通过 ROCm 演示了端到端的 GPU 并行物理仿真+强化学习训练，遵循 [ROCm + JAX + MuJoCo 官方博客](https://rocm.blogs.amd.com/artificial-intelligence/rocm-jax-mujoco/README.html)的路径。

---

## 2. Development Process & Challenges / 开发过程与遇到的困难

Key decisions / 关键决策. We chose JAX + MJX because it is the only mature path to GPU-parallel physics that runs on AMD via XLA without CUDA. We wrote PPO from scratch (`jax.jit` + `lax.scan`, no `pmap`) rather than using brax's trainer, because the brax `pmap` / `device_put_replicated` path triggered a ROCm segfault early on.

关键决策：选择 JAX + MJX，因为这是唯一成熟、能通过 XLA 在 AMD 上跑 GPU 并行物理且不依赖 CUDA 的路径。PPO 从零实现（`jax.jit` + `lax.scan`，不用 `pmap`），而非直接用 brax 训练器，因为 brax 的 `pmap` / `device_put_replicated` 路径早期就触发了 ROCm 段错误。

Ablation — trainer choice on ROCm / 消融对比：ROCm 上的训练器选型. Both trainers run the same PPO objective on the same MJX environment; the only difference is the execution path. This is what drove us off the brax trainer and onto a from-scratch single-GPU design. 两个训练器在同一 MJX 环境上跑相同的 PPO 目标，唯一区别是执行路径。这正是我们放弃 brax 训练器、转向自写单卡设计的原因。

| Trainer / 训练器 | Execution path / 执行路径 | Result on gfx1100 / 在 gfx1100 上的结果 |
|---|---|---|
| Brax PPO (`src/train.py`) | `pmap` + `device_put_replicated` (multi-device replication) | Segfaults early in `libhsa-runtime64.so.1` — the replication path hits the profiler race almost immediately / 很快在 `libhsa-runtime64.so.1` 段错误，复制路径几乎立即触发 profiler 竞态 |
| From-scratch jit PPO (`src/train_jax_ppo.py`) | `jax.jit` + `lax.scan`, single device, no `pmap` | Compiles and dispatches on the GPU; still segfaults in `libhsa-runtime64` (observed `EXIT=139` on our runs), but reaches further into execution than the `pmap` path before crashing / 能在 GPU 上编译并发射；仍会在 `libhsa-runtime64` 段错误（实测 `EXIT=139`），但比 `pmap` 路径崩得更晚 |

The single-device `lax.scan` path avoids the `pmap` replication that triggers the crash fastest, which is why we default to it. It does not fully escape the underlying ROCm profiler bug — that is a runtime-layer issue, not a trainer-design one (section 2, "the difficulty we hit"). 单设备 `lax.scan` 路径避开了最快触发崩溃的 `pmap` 复制，因此设为默认；但它并未完全绕开底层 ROCm profiler bug——那是运行时层问题，非训练器设计问题（见本节"遇到的困难"）。

The difficulty we hit / 遇到的困难. On a gfx1100 + ROCm 7.2.1 + JAX 0.11.0 stack, every training run segfaults inside `libhsa-runtime64.so.1`. The root cause, confirmed via `rocgdb` and `ldd`: `jax-rocm7-plugin` (`xla_rocm_plugin.so`) has `librocprofiler-sdk.so.1` as a static NEEDED dependency. This profiler intercepts every HIP kernel launch via GOTCHA hooks, and on gfx1100 that injection into HSA has a non-deterministic race condition causing random segfaults.

遇到的困难：在 gfx1100 + ROCm 7.2.1 + JAX 0.11.0 环境下，每次训练都会在 `libhsa-runtime64.so.1` 内段错误。经 `rocgdb` 和 `ldd` 确认的根因：`jax-rocm7-plugin`（`xla_rocm_plugin.so`）静态链接了 `librocprofiler-sdk.so.1`。该分析器通过 GOTCHA 钩子拦截每次 GPU kernel 发射，在 gfx1100 上导致 HSA 层非确定性竞态段错误。

We could not disable it: environment variables (`HSA_TOOLS_LIB=`, `ROCP_TOOL_LIB=`, `ROCPROFILER_DISABLE=1`) had no effect; XLA flags (`command_buffer`, `autotune_level=0`, …) had no effect; `patchelf --remove-needed` fails because the plugin needs the `rocprofiler_force_configure` symbol; and uninstalling `rocprofiler-sdk` destroys JAX GPU support irreversibly. Full reproduction steps, the rocgdb stack, and ldd evidence are in [docs/ROCM_BUG_REPORT.md](docs/ROCM_BUG_REPORT.md).

无法关闭它：环境变量（`HSA_TOOLS_LIB=`、`ROCP_TOOL_LIB=`、`ROCPROFILER_DISABLE=1`）无效；XLA flags（`command_buffer`、`autotune_level=0` 等）无效；`patchelf --remove-needed` 因插件需要 `rocprofiler_force_configure` 符号而失败；卸载 `rocprofiler-sdk` 会不可逆地破坏 JAX GPU 能力。完整复现步骤、rocgdb 栈和 ldd 证据见 [docs/ROCM_BUG_REPORT.md](docs/ROCM_BUG_REPORT.md)。

What is confirmed working, isolated from the crash: `env.reset()` / `env.step()` / a single `jax.vmap` step run on the GPU without crashing, and `scripts/00_verify_rocm.sh` passes 6/6. Simple, low-dispatch GPU operations are fine. The segfault appears once training dispatches many kernels through nested `lax.scan` — the full PPO loop hits it inside the first chunk.

与崩溃隔离来看正常的部分：`env.reset()` / `env.step()` / 单次 `jax.vmap` 能在 GPU 上不崩地跑，`scripts/00_verify_rocm.sh` 通过 6/6。简单、低 dispatch 的 GPU 操作没问题。一旦训练通过嵌套 `lax.scan` 发射大量 kernel，段错误就出现——完整 PPO 循环在第一个 chunk 内就撞上。

Observed on this instance / 实例实测. Running `SMOKE=1 bash scripts/01_train.sh` twice: the GPU is detected (`RocmDevice`), the env and trainer initialize and print the training plan, then both runs segfault in the first `lax.scan` chunk with `EXIT=139` (`Segmentation fault (core dumped)`) and no checkpoint is written. This matches the ROCm profiler race described above — it is a runtime-layer crash, not a logic error in our code.

实例实测：连跑两次 `SMOKE=1 bash scripts/01_train.sh`——GPU 被识别（`RocmDevice`），环境与训练器初始化并打印训练计划，随后两次都在第一个 `lax.scan` chunk 段错误、`EXIT=139`（`Segmentation fault (core dumped)`）、未写出任何 checkpoint。这与上述 ROCm profiler 竞态吻合，是运行时层崩溃,非我方代码逻辑错误。

If we kept optimizing / 如果继续优化. File the upstream ROCm/JAX bug (a draft is ready in [docs/ROCM_BUG_REPORT.md](docs/ROCM_BUG_REPORT.md)); once the profiler race is fixed or a patched plugin ships, run full training to convergence, add domain randomization, and attempt sim-to-real transfer.

如果继续优化：向上游 ROCm/JAX 提交 bug（草稿已备好，见 [docs/ROCM_BUG_REPORT.md](docs/ROCM_BUG_REPORT.md)）；待 profiler 竞态修复或发布修补版插件后，跑完整训练至收敛，加入域随机化，并尝试 sim-to-real 迁移。

---

## 3. Code Origin & Contributions / 代码来源与贡献

The from-scratch PPO in `src/train_jax_ppo.py` and the networks in `src/nets.py` are fully original work by the team. The architecture references standard PPO (Schulman et al., 2017) and the MJX-Locomotion config from MuJoCo Playground. For MJX integration we use `mujoco_playground.registry` to create the environment and `mujoco_playground.wrapper.wrap_for_brax_training` for the Brax-compatible wrapper. The Brax PPO path in `src/train.py` is adapted from `brax.training.ppo.train` and kept only as a reference/comparison baseline. The render script is adapted from MuJoCo's rendering examples, and the Dockerfile is based on the `rocm/jax-community` community images.

`src/train_jax_ppo.py` 里的 PPO 与 `src/nets.py` 里的网络为团队完全原创。架构参考标准 PPO（Schulman 等，2017）与 MuJoCo Playground 的 MJX-Locomotion 配置。MJX 集成用 `mujoco_playground.registry` 创建环境、`mujoco_playground.wrapper.wrap_for_brax_training` 做 Brax 兼容封装。`src/train.py` 的 Brax PPO 路径改编自 `brax.training.ppo.train`，仅作对照基线保留。渲染脚本改编自 MuJoCo 官方示例，Dockerfile 基于 `rocm/jax-community` 社区镜像。

Third-party dependencies / 第三方依赖:

| Library | License | Usage / 用途 |
|---------|---------|-------|
| JAX | Apache-2.0 | GPU compute / autograd |
| MuJoCo / mujoco-mjx | Apache-2.0 | Physics simulation / 物理仿真 |
| Brax | Apache-2.0 | PPO reference, env wrapper / PPO 参考、环境封装 |
| MuJoCo Playground | Apache-2.0 | Locomotion environments / 运动环境 |
| Flax | Apache-2.0 | Neural network definition / 网络定义 |
| Optax | Apache-2.0 | Optimizer (Adam) / 优化器 |
| MediaPy | Apache-2.0 | Video writing / 视频写出 |

Upstream contribution / 上游贡献. We identified and documented a ROCm runtime bug: the profiler-sdk is statically linked into the XLA plugin, causing non-deterministic segfaults on gfx1100. A detailed report with reproduction steps, rocgdb stack trace, and ldd evidence is ready to file as a GitHub issue in [docs/ROCM_BUG_REPORT.md](docs/ROCM_BUG_REPORT.md). The key insight — rocprofiler-sdk should be dynamically loaded, not statically linked — is directly actionable and would unblock JAX GPU training on affected configs.

上游贡献：我们定位并整理了一个 ROCm 运行时 bug——profiler-sdk 被静态链接进 XLA 插件，在 gfx1100 上导致非确定性段错误。含复现步骤、rocgdb 栈、ldd 证据的完整报告已备好，可直接提交为 issue，见 [docs/ROCM_BUG_REPORT.md](docs/ROCM_BUG_REPORT.md)。核心结论——rocprofiler-sdk 应动态加载而非静态链接——对 ROCm 团队直接可执行，可解锁受影响配置上的 JAX GPU 训练。

---

## 4. Team / 团队分工

This project was built solo by istics1998, who did the PPO implementation, MJX integration, ROCm debugging, and all documentation. All decisions, code, debugging, and docs are the work of the sole member.

本项目由 istics1998 独立完成，负责 PPO 实现、MJX 集成、ROCm 调试与全部文档。所有决策、代码、调试与文档均由该成员一人完成。

---

## 5. Setup & Run / 安装与运行

Requirements / 环境要求: an AMD Radeon GPU instance with ROCm 7.x. Follow the [Radeon Cloud User Guide](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/Radeon-Cloud-User%20Guide/README.md). / 一台装有 ROCm 7.x 的 AMD Radeon GPU 实例，参考上方 Radeon 云用户指南。

Option A — Docker (recommended) / 方式 A — Docker（推荐）:

```bash
docker build --build-arg BASE_TAG=<rocm-version-tag> -t amd-locomotion .
docker run -it --rm \
  --device=/dev/kfd --device=/dev/dri \
  --group-add video --security-opt seccomp=unconfined \
  -v "$PWD/outputs:/app/outputs" \
  amd-locomotion bash scripts/00_verify_rocm.sh
```

Option B — native pip / 方式 B — 原生 pip:

```bash
# 1. Install JAX ROCm build / 安装 JAX 的 ROCm 版本
pip install "jax[rocm7-local]" -f https://storage.googleapis.com/jax-releases/jax_rocm_releases.html

# 2. Install dependencies / 安装依赖 (use official PyPI for mujoco_playground)
pip install --break-system-packages -i https://pypi.org/simple playground
pip install --break-system-packages mujoco mujoco-mjx "brax>=0.14.0" flax optax ml_collections etils mediapy tensorboardX tqdm

# 3. Verify / 验证
bash scripts/00_verify_rocm.sh
```

Choosing the right ROCm / JAX version / 选择正确的版本. Check the instance ROCm version with `cat /opt/rocm/.info/version`. 用 `cat /opt/rocm/.info/version` 查看实例 ROCm 版本。

| ROCm | JAX extra | Notes / 说明 |
|------|-----------|-------|
| 7.2.x | `jax[rocm7-local]` | Tested on gfx1100 / 已在 gfx1100 测试 |
| 6.x | `jax[rocm6-local]` | Not tested for this project / 本项目未测试 |

Run commands / 运行命令:

```bash
# 0. Verify AMD GPU (must print RocmDevice) / 验证 AMD GPU（须打印 RocmDevice）
bash scripts/00_verify_rocm.sh

# 1. Smoke test — starts training, then hits the ROCm segfault / 冒烟测试（会触发段错误）
SMOKE=1 bash scripts/01_train.sh

# 2a. GPU training — hits the ROCm profiler race (section 2) / GPU 训练（触发 ROCm 竞态）
bash scripts/01_train.sh

# 2b. CPU training — the fallback that actually converged (62.26M steps ~4.6h) / CPU 训练（真正收敛的退路）
MUJOCO_GL=egl python3 scripts/train_go1.py    # writes checkpoints/ + train.log

# 3. Render the demo from the trained policy / 用训练策略渲染演示
MUJOCO_GL=egl python3 scripts/render_policy_video.py   # needs checkpoints/latest.pkl
```

How to verify / 验证方式. Step 0 is the reliable, reproducible check: it prints `RocmDevice` and passes 6/6, confirming the GPU and JAX ROCm stack are live. Step 2a launches PPO training on the GPU and hits the ROCm profiler segfault on gfx1100 (section 2) — the expected, documented failure. Step 2b runs the same training on CPU and converges (reward → 23.9; `train.log` records the curve, 20 checkpoints land in `checkpoints/`). Step 3 loads `checkpoints/latest.pkl` and renders the trained policy (`assets/demo_policy.mp4`).

验证方式：第 0 步是稳定可复现的检查——打印 `RocmDevice` 并通过 6/6，确认 GPU 与 JAX ROCm 栈可用。第 2a 步在 GPU 上启动 PPO 训练，会在 gfx1100 上触发 ROCm profiler 段错误（第 2 节）——预期内、已记录的失败。第 2b 步在 CPU 上跑同样的训练并收敛（reward → 23.9；`train.log` 记录曲线，`checkpoints/` 落 20 个 checkpoint）。第 3 步加载 `checkpoints/latest.pkl` 渲染训练策略（`assets/demo_policy.mp4`）。

Note: `scripts/02_eval.sh` (closed-loop eval) and `scripts/03_record_video.sh` (MuJoCo-renderer video) also consume a trained checkpoint; with `checkpoints/final.pkl` present they now run. The scripted-gait demo (`scripts/make_demo_video_full.py`, no checkpoint needed) is kept as a rendering-pipeline reference.

说明：`scripts/02_eval.sh`（闭环评估）与 `scripts/03_record_video.sh`（MuJoCo 渲染器出视频）同样需要训练好的 checkpoint；现在有了 `checkpoints/final.pkl` 即可运行。脚本步态演示（`scripts/make_demo_video_full.py`，无需 checkpoint）作为渲染管线参考保留。

---

## 6. Results / 运行结果

Repository layout / 仓库结构:

```
scripts/00_verify_rocm.sh        # Verify environment / 验证环境 (run first / 先跑这个)
scripts/01_train.sh              # GPU train — hits ROCm race / GPU 训练（触发 ROCm 竞态）
scripts/train_go1.py             # CPU training that converged (reward→23.9) / CPU 训练（已收敛 reward→23.9）
scripts/render_policy_video.py   # Render the TRAINED policy demo / 渲染训练策略演示 (needs checkpoint / 需 checkpoint)
scripts/make_demo_video_full.py  # Scripted-gait demo, real physics, 3D render / 脚本步态演示+真物理+3D
scripts/repro_hsa_segfault.py    # Minimal crash reproduction / 最小崩溃复现脚本
scripts/02_eval.sh               # Closed-loop eval (needs a trained checkpoint) / 闭环评估（需 checkpoint）
scripts/03_record_video.sh       # MuJoCo-renderer video (needs a checkpoint) / MuJoCo 渲染器视频（需 checkpoint）
src/config.py                    # Paths + GPU assert + headless render / 路径+GPU断言+无头渲染
src/nets.py                      # Actor-Critic network (Flax) / 网络定义
src/train_jax_ppo.py             # From-scratch single-GPU jit PPO / 自写单卡 PPO (default / 默认)
src/train.py                     # Brax PPO (reference / 对照用)
src/eval.py                      # Load checkpoint + evaluate (inference) / 加载 checkpoint 评估（推理）
src/render.py                    # Render rollout to mp4 / 渲染 rollout 视频
docs/ROCM_BUG_REPORT.md          # ROCm bug report (upstream issue material) / bug 报告素材
```

There is no `data/` directory or dataset generation script: the environments come directly from MuJoCo Playground's registry, so there is no custom dataset to build or download. Inference is implemented in `scripts/render_policy_video.py` (loads `checkpoints/latest.pkl` and rolls out the trained policy under joystick commands) — it consumes the checkpoint produced by the CPU training run. One inference-time detail worth noting: training used `normalize_observations=True`, so the network must be rebuilt with the same `preprocess_observations_fn=running_statistics.normalize` at render time, otherwise the policy sees raw-scale observations and topples; the render script does this.

没有 `data/` 目录或数据生成脚本：环境直接来自 MuJoCo Playground 的 registry，因此没有自制数据集需要构建或下载。推理逻辑在 `scripts/render_policy_video.py`（加载 `checkpoints/latest.pkl`，在摇杆指令下 rollout 训练策略）——它消费 CPU 训练产出的 checkpoint。一个值得记录的推理细节：训练用了 `normalize_observations=True`，因此渲染时网络必须用同样的 `preprocess_observations_fn=running_statistics.normalize` 重建，否则策略会看到未归一化尺度的观测而摔倒；渲染脚本已做此处理。

Actual results / 实际结果. `00_verify_rocm.sh` passes 6/6 and prints `RocmDevice`. The Go1 env loads and the PPO trainer compiles and dispatches on the GPU, then segfaults in the first `lax.scan` chunk (`EXIT=139`, observed twice; see section 2) — so GPU training is not possible on this stack. We therefore ran the identical JAX/MJX + PPO training on **CPU**, which converged: a full 62.26M-step run (275.7 min, `CpuDevice`, 1024 parallel envs) with `eval/episode_reward` rising **0.001 → 2.7 (6.5M) → 13.4 (9.8M) → 19.0 (29.5M) → 23.9 (62.26M)**. 20 checkpoints were saved; the final policy walks/turns/side-steps under joystick command (demo in section 7). The trained checkpoint is `checkpoints/final.pkl`; the reward log is `train.log`.

实际结果：`00_verify_rocm.sh` 通过 6/6 并打印 `RocmDevice`。Go1 环境能加载、PPO 训练器能在 GPU 上编译并发射，随后在第一个 `lax.scan` chunk 段错误（`EXIT=139`，实测两次；见第 2 节）——因此这套栈上无法用 GPU 训练。于是我们用同一套 JAX/MJX + PPO 在 **CPU** 上训练，并且收敛了：一次完整的 62.26M 步训练（275.7 分钟，`CpuDevice`，1024 并行环境），`eval/episode_reward` 从 **0.001 → 2.7（6.5M）→ 13.4（9.8M）→ 19.0（29.5M）→ 23.9（62.26M）**。保存 20 个 checkpoint；最终策略能按摇杆指令行走/转身/横移（演示见第 7 节）。训练好的 checkpoint 为 `checkpoints/final.pkl`，reward 日志为 `train.log`。

Note on the GPU goal / 关于 GPU 目标的说明: the original aim was GPU-accelerated training. That specific path stays blocked by the ROCm profiler race (section 2); once a patched `jax-rocm7-plugin` ships, the same script trains on GPU at a large speedup. The policy itself is real and trained today — just on CPU. / 原定目标是 GPU 加速训练。这条具体路径仍被 ROCm profiler 竞态阻塞（第 2 节）；一旦修复版 `jax-rocm7-plugin` 发布，同一脚本即可在 GPU 上训练并大幅提速。策略本身是真实且已训练完成的——只是跑在 CPU 上。

---

## 7. Demo Video / 演示视频

Watch on Bilibili: [https://b23.tv/18MX3yY](https://b23.tv/18MX3yY). Local: [assets/demo_policy.mp4](assets/demo_policy.mp4).

B 站观看：[https://b23.tv/18MX3yY](https://b23.tv/18MX3yY)。本地：[assets/demo_policy.mp4](assets/demo_policy.mp4)。

The demo is the **trained PPO policy** (`checkpoints/final.pkl`) rolled out on the real Go1 model with real MuJoCo physics, rendered in 3D via `mujoco.Renderer`. Each segment feeds a different joystick velocity command — stand, walk forward/backward, side-step left/right, turn in place left/right, and a walk+turn arc — and the *same* network produces every motion; the gait is learned, not hand-authored. All 8 segments hold the trunk upright the whole rollout (min trunk height 0.288 m). Rendering runs on CPU MuJoCo, matching the CPU training backend.

演示视频是**训练出的 PPO 策略**（`checkpoints/final.pkl`）在真实 Go1 模型上的 rollout，用真实 MuJoCo 物理驱动，经 `mujoco.Renderer` 做 3D 渲染。每段喂入不同的摇杆速度指令——站立、前进/后退、左右横移、原地左右转、以及边走边转的弧线——全部动作由**同一个**网络产生；步态是学出来的，不是手写的。8 段全程保持躯干直立（最低躯干高度 0.288 m）。渲染跑在 CPU MuJoCo 上，与 CPU 训练后端一致。

Regenerate / 重新生成: `MUJOCO_GL=egl python3 scripts/render_policy_video.py` (writes `assets/demo_policy.mp4`, needs `checkpoints/latest.pkl`).

---

## License / 许可证

MIT License — see [LICENSE](LICENSE). / MIT 许可证，详见 [LICENSE](LICENSE)。

