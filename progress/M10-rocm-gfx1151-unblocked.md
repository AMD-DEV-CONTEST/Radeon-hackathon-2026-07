# M10 — ROCm gfx1151 + PyTorch 2.10 本地推理环境打通

- **日期**：2026-04-21
- **目标阶段**：Plan A v2 · 阶段 1（ROCm 环境打通，为阶段 2–5 做准备）

---

## 完成了什么

让 AMD Strix Halo APU（Radeon 8060S，gfx1151，64 GB 统一内存）能在 BotverseX 的 `apps/realtime/.venv` 里直接跑 PyTorch GPU，为后续本地训练（MLP / Vision MLP / SmolVLA）和本地推理铺好底座。

- 升级 `apps/realtime/.venv`：`torch 2.7.1+rocm6.3` → **`torch 2.10.0+rocm7.0`**，配套 `torchvision 0.25.0+rocm7.0`、`pytorch-triton-rocm 3.5.1`。
- 新增 `apps/realtime/rocm_env.sh`：一行 `source` 就能把 ROCm 环境变量 + `.venv` 激活到位。
- 新建 `progress/` 目录，约定今后每个里程碑都配一份 `.md` 并跟 Git commit 对齐。

---

## 解决了什么问题

**核心 bug**：即便系统自带 ROCm 7.2.2、`rocminfo` 能看到 `gfx1151`、`torch.cuda.is_available()` 能返回 `True`，一旦真正 launch 一个 HIP kernel 就 **SIGSEGV**。

### Root cause 链

1. **预装的 ROCm 版本是 7.2.2，不是 6.3.4**：尝试再装 6.3.4 触发 deb 包依赖冲突。
2. **旧的 torch 2.7.1+rocm6.3 wheel**：跟 7.2.2 userland 的 HIP ABI 不兼容，`is_available()` 直接 `False`。
3. **升级到 torch 2.10.0+rocm7.0 后，wheel 能看到 GPU 但发 kernel 时 segfault**：`AMD_LOG_LEVEL=4` 日志显示
   ```
   Found bundleEntryId=hipfatbin-hipv4-amdgcn-amd-amdhsa--gfx1151.o
   agent_triple_target_ids[0]=amdgcn-amd-amdhsa--gfx1151 ... Size=204288, num_code_objs=0
   Using Code Object V5.
   [SIGSEGV]
   ```
   wheel **自带** gfx1151 的 kernel 二进制（Code Object V5），但 wheel 里捆绑的 `libhsa-runtime64.so` 是较旧版本的 HSA runtime，不认 V5 code object 于是加载阶段崩溃。
4. **HSA_OVERRIDE_GFX_VERSION=11.0.0 不能救场**：wheel 里没有 gfx1100 kernel（新版 PyTorch 精简了预编译矩阵），一设就 import 阶段直接崩。

### 最终修法

强制 `LD_PRELOAD=/opt/rocm/lib/libhsa-runtime64.so.1`，让 PyTorch 使用系统 ROCm 7.2.2 的新版 HSA runtime，而不是 wheel 自带的旧版。

> 副产物：发现 Cursor sandbox 默认以 root 身份执行 shell，但 `/dev/kfd` 仅对 `render` 组开放，root 不在 render 里，所以沙盒内 `torch.cuda.is_available()` 永远 False。后续凡涉及 GPU 的命令都通过 `sudo -u amd` 或要求用户自己跑。

---

## 关键命令 / 配置

### 1. 升级 torch 到 rocm7.0

```bash
cd /home/amd/Downloads/botversex/apps/realtime
./.venv/bin/pip install --upgrade \
  --index-url https://download.pytorch.org/whl/rocm7.0 \
  --extra-index-url https://pypi.org/simple \
  'torch==2.10.0+rocm7.0' \
  'torchvision==0.25.0+rocm7.0' \
  'pytorch-triton-rocm'
```

### 2. 启动脚本 `apps/realtime/rocm_env.sh`

```bash
export ROCM_PATH=/opt/rocm
export PATH=/opt/rocm/bin:${PATH}
export LD_PRELOAD=/opt/rocm/lib/libhsa-runtime64.so.1   # ⬅ 关键
unset HSA_OVERRIDE_GFX_VERSION                          # gfx1151 原生支持，不要 override
source .venv/bin/activate                               # 自动切到 rocm7 venv
```

### 3. Smoke test

```bash
cd /home/amd/Downloads/botversex/apps/realtime
source rocm_env.sh
python /tmp/rocm_smoke.py
```

> 注意：如果你在 base conda 环境里直接 `python /tmp/rocm_smoke.py`，拿到的是 `torch 2.7.1+cu126`（CUDA wheel），那是 conda env 带来的、跟 BotverseX 无关。必须先 `source apps/realtime/rocm_env.sh`。

---

## 最终结果

```
torch    : 2.10.0+rocm7.0
hip      : 7.0.51831
available: True
devices  : 1
name     : AMD Radeon Graphics
gcnArch  : gfx1151
memory   : 64.0 GB
matmul 2048^2 x20 = 7.24 ms/iter  (2 GFLOPs)
```

- ✅ 识别为原生 **gfx1151**，无需 HSA_OVERRIDE
- ✅ 64 GB 统一显存（远大于后续 SmolVLA / Pi0 训练需求）
- ✅ 2048² matmul 稳定在 7 ms 左右，后续会跑更大 benchmark（阶段 5）

---

## 下一步

进入 **阶段 2：Step 4 数据采集**
- 从 `teleop_control.py` 抽出 `_CLIProcess` 基类
- 新增 `record_control.py`（包装 `lerobot-record`）
- 加 port_lock_manager：录制时禁止 teleop 抢端口
- Step 4 UI：dataset 名 / episode 数 / FPS / 实时日志
