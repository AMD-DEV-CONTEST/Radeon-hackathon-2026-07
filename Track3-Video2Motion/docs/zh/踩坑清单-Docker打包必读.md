# 踩坑清单 · Docker 打包必读

> 这份是**操作性**清单，专门给打包和复现用。每一条都是实测踩过的，
> 漏掉任何一条镜像都跑不起来或者结果是错的。
>
> 排查过程见 [`BeyondMimic移植记录.md`](BeyondMimic移植记录.md) 和
>。

---

## 〇、最要命的三条（漏了会静默出错，不报错）

| # | 坑 | 症状 | 处理 |
|---|---|---|---|
| 1 | **Playground 的 auto-reset 不还原 `info`** | 训练越训越差，未训练的网络反而最好 | `wrap_for_brax_training(..., full_reset=True)` |
| 2 | **GVHMR 按文件名复用缓存** | 同名视频静默返回上次结果 | 跑之前 `rm -rf outputs/demo/<name>`；唯一破绽是日志里 `Time elapsed: 0.03s` |
| 3 | **unitree_mujoco 的 PD 在 DDS 回调里算** | 原生 MuJoCo 好好的，一接 DDS 就 47 步摔 | PD 移进仿真循环，见第五节 |

这三条的共同点：**不报错**。所以必须在打包时就固化，不能指望运行时发现。

---

## 一、三个 Python 环境必须互相隔离

它们**装在一起会互相踩**，Docker 里要么三个 venv，要么多阶段镜像。

| venv | 关键依赖 | 不能有 |
|---|---|---|
| `/persistent/gvhmr_env` | PyTorch 2.9.1+rocm7.2.1、pytorch3d | jax |
| `/persistent/GMR/gmr` | 重定向依赖 | — |
| `/persistent/mjx` | JAX 0.11 (rocm7-plugin)、MuJoCo、MJX、brax、gradio | torch |

验证方式：

```bash
/persistent/gvhmr_env/bin/python -c "import torch; import jax"   # 必须报 No module named 'jax'
/persistent/mjx/bin/python      -c "import jax;   import torch"  # 必须报 No module named 'torch'
```

**后端只能用子进程 + 文件交换**（`webapp/pipeline.py` 就是这么做的），
不要试图在一个进程里 import 两边。

---

## 二、ROCm / JAX 安装顺序

```bash
# 1) JAX-ROCm 必须最先装，装完立刻验证
python3 -m venv /persistent/mjx && source /persistent/mjx/bin/activate
pip install --upgrade "jax[rocm7-local]"
python -c "import jax; print(jax.default_backend(), jax.devices())"
# 期望: gpu [RocmDevice(id=0)]        不是 gpu 就别往下走

# 2) 仿真与训练
pip install mujoco mujoco-mjx brax mujoco_playground gradio
pip install "setuptools<81"      # >=81 移除 pkg_resources，lightning 会崩
```

| 坑 | 症状 | 处理 |
|---|---|---|
| ROCm torch wheel 绑定本地 triton | `No matching distribution found for triton==3.5.1+rocm7.2.1` | 四个本地 wheel 必须**一起**装 |
| pytorch3d 编译 | `No module named 'torch'` | `--no-build-isolation` |
| pytorch3d 把机器编译爆 | 30+ 个 cc1plus，sshd fork 不出来，`kex_exchange_identification: Connection closed` | `MAX_JOBS=8`，串行 |
| chumpy 装不上 | `No module named 'pip'`，还会中断整批安装 | 单独装 + `--no-build-isolation` + 两处 sed（`inspect.getargspec`→`getfullargspec`、删 numpy 别名） |
| ultralytics 8.2.42 | `weights_only=True` 挡住 YOLO 权重 | `pip install -U --no-deps ultralytics` |
| wis3d / pycolmap | 以为能跳过 | **不能** —— `cv2_utils.py` 模块级 import |

---

## 三、AMD gfx1100 的两个硬限制

**1. XLA 编译图规模上限**

```
num_minibatches × num_updates_per_batch ≤ 32
```

超了直接段错误，Python 层没有任何异常。已排除显存（48 GB 只用 28 MB）、
`pmap`、环境实现 —— 是后端编译器的限制。本项目用 `16 × 2`。

**2. brax 与 JAX 0.11 不兼容**

brax 0.14.2 调用了 JAX 0.11 已移除的 `jax.device_put_replicated`。
NVIDIA 用户可以降级 JAX，**AMD 用户不行**（版本被 `jax-rocm7-plugin` 锁死）。
必须在 `import brax` **之前**打垫片：

```python
if not hasattr(jax, "device_put_replicated"):
    import jax.numpy as jnp
    def _dpr(x, devices):
        n = len(devices)
        st = jax.tree_util.tree_map(lambda y: jnp.stack([jnp.asarray(y)] * n), x)
        return jax.device_put(st, devices[0]) if n == 1 else st
    jax.device_put_replicated = _dpr
```

> `jax.sharding.PositionalSharding` 也一起被移除了，别用它写垫片。

**3. MuJoCo Playground 默认后端是 CUDA 独占的**

```python
cfg.impl = "jax"     # 官方默认 "warp"，Warp 只支持 CUDA
```

不设的话报 `IndexError: list index out of range`（来自 `warp.get_cuda_device`），
毫无指向性。

---

## 四、环境实现里的坑（移植 BeyondMimic 时踩的）

| # | 坑 | 后果 |
|---|---|---|
| 1 | `data.cvel` 的线速度在 **subtree_com** 那点，不是 body 原点 | 手腕速度差 1.0 m/s；修法 `v = cvel[3:6] + ω × (xpos − subtree_com)` |
| 2 | 自由关节 `qvel[3:6]` 是**机体系**角速度，不是世界系 | 速度奖励恒为 0（误差平方和除以 std² 后 exp 下溢） |
| 3 | `sim_dt=0.005` 在 Playground 的 G1 上积分发散 | `base_z` 飞到 −165911；用 **0.002** |
| 4 | `action_scale=0.5` 够不到参考姿态 | brax 的 tanh 把动作压在 [−1,1]，位置执行器稳态 `q≈ctrl`，手臂物理上抬不起来。改成**相对参考姿态**下指令 |
| 5 | `soft_joint_pos_limit_factor=0.9` 与参考冲突 | 参考本身 269/298 帧超界，完美跟踪也被罚 −2.09/步。用 **1.0** |
| 6 | 奖励乘 `dt` 导致熵项压过任务奖励 | brax 的熵项不归一化，`5e-3×entropy(≈41)≈0.205` vs 任务 0.044。保持奖励 O(1)/步、`entropy_cost=1e-3` |
| 7 | `deterministic_eval` 默认 False | 评估用的是带噪声的策略，指标不可信 |
| 8 | **auto-reset 不还原 `info`** | 见第〇节第 1 条 |

**验收环境的正确方式**：把状态精确设成参考轨迹某一帧，
六项跟踪奖励必须**全部 = 1.0000**。任何一项偏离就说明坐标系/参考点/单位
还有 bug。这个检查应该在写完奖励函数当天就做。

---

## 五、部署侧（sim2sim / 真机）

### 5.1 unitree_mujoco 桥接层的 PD 必须移进仿真循环

原实现在 `LowCmdHandler`（DDS 回调，50 Hz）里算力矩写进 `mj_data.ctrl`，
两条指令之间那个力矩被**当成常量保持 20 ms**。

| 场景 | PD 闭环频率 |
|---|---|
| 训练（position 执行器） | 500 Hz |
| 真机（电机驱动器固件） | 1~2 kHz |
| unitree_mujoco 原实现 | **50 Hz 零阶保持** |

实测（同策略同模型，只改这一项）：

| PD 闭环 | 存活 |
|---|---|
| 50 Hz 零阶保持，kd = 2 / 5 / 10 | 18 / 24 / 18 ❌ |
| 200 Hz 子步闭环 | **500/500** ✅ |

**加大阻尼救不回来** —— 不是阻尼不够，是采样率不够。补丁见
`成果产物/code/third_party_patches/`。

### 5.2 策略观测只能用 SDK 真实提供的量

`LowState` 只有：`motor_state.q` / `.dq`、`imu_state.quaternion`、
`imu_state.gyroscope`。

**不能用**：
- 躯干**线速度**（IMU 不给，需要状态估计）
- 躯干**世界位置**（没有全局定位）

所以 BeyondMimic 的 `motion_anchor_pos_b` 和 `base_lin_vel` 都必须从
policy 观测里去掉（官方也提供了 `Wo-State-Estimation` 配置）。
critic 可以保留 —— 非对称 actor-critic，特权信息只在训练时用。

**这件事必须在训练前决定**，训完了再裁维度就得重训。

### 5.3 其它部署坑

| 坑 | 症状 | 处理 |
|---|---|---|
| 把目标角度灌进力矩执行器 | 不同策略摔在**同一步**，跟踪误差反而小 | 按 `actuator_biastype` 分派：`none`=力矩，`affine`=位置 |
| 站立 keyframe 高度手估 | 上电瞬间硬着地 | 接触二分法求解；`geom_xpos` 是几何体**中心**不是最低面 |
| `lo` 网卡不支持组播 | 收不到 LowState 超时 | 写 CycloneDDS XML 走回环单播，**两端都要设** |
| 桥接层无条件 import pygame | `ModuleNotFoundError: pygame` | 装上（即使关了手柄） |
| 仿真先跑、控制端后连 | 机器人在等待期间就躺了 | 收到第一条 LowCmd 再推进物理 |
| viewer 强依赖 GLFW | 容器里 `GLFWError: DISPLAY missing` | 用无头版 EGL 离屏渲染；Xvfb+x11grab 抓出来是静止帧 |
| 离屏画布 > 640×480 | 报错让你改第三方 XML | 运行时改 `mj_model.vis.global_.offwidth/offheight` |

---

## 六、Docker 分层建议

```
base           ROCm 7.2.1 runtime
 ├─ stage-mjx    venv: jax[rocm7-local] -> mujoco/mjx/brax/playground/gradio
 ├─ stage-gvhmr  venv: torch-rocm wheels(四个一起) -> pytorch3d(MAX_JOBS=8) -> 其余
 └─ stage-gmr    venv: 重定向依赖
final          三个 venv + 代码 + 第三方补丁 + 权重
```

**必须固化进镜像的补丁：**

1. `unitree_sdk2py_bridge.py` —— PD 移出 DDS 回调（第 5.1 节）
2. `unitree_mujoco.py` —— 仿真循环里调 `ApplyPD()`
3. `scene_29dof.xml` —— 站立 keyframe，高度用接触二分求解
4. GVHMR 的 `chumpy` 两处 sed
5. `unitree_mujoco_headless.py` —— 无头录制版

**运行时环境变量：**

```dockerfile
ENV MUJOCO_GL=egl                       # 离屏渲染；osmesa 只在纯 CPU 时用
ENV XLA_PYTHON_CLIENT_PREALLOCATE=false # 否则 JAX 一上来吃满显存
ENV CYCLONEDDS_URI=file:///app/cyclonedds_lo.xml
ENV MPLBACKEND=Agg                      # GVHMR 需要
```

**暴露端口**：`7860`（Gradio）。

**别忘了**：
- `apt install xvfb`（GMR 的重定向脚本需要）
- `pip install pygame`（unitree_mujoco 桥接层无条件 import）
- 提交前删掉 `/persistent/id_ed25519` 之类的私钥

---

## 七、排查方法论（这次学到的）

| 教训 | 这次的体现 |
|---|---|
| **消融实验里多组差异很大的配置给出几乎相同的曲线 → 去查所有组共享的东西** | 关惩罚/关熵/都关三组曲线重合，真因是包装器 |
| **两个不同的输入失败在同一个点 → 一定不是输入的问题** | 两个策略都恰好第 18 步摔 → 单位 bug |
| **说「A 修好了 B」之前先确认对比里只变了 A** | 「DR 关上了 sim2sim 缺口」是错的，那次 `kd` 也变了 |
| **不要用「没摔倒」当动作质量的证据** | 500/500 步不摔的策略，手臂根本没动 |
| **写完奖励函数当天就做完美跟踪者检验** | 六项奖励必须全 = 1.0000 |
| **第三方仿真器 ≠ 真机** | 桥接层的 50 Hz ZOH 是实现限制，真机不是这样 |
