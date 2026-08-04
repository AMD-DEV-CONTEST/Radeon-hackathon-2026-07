# BeyondMimic 配方移植到 MJX/AMD —— 过程记录

> 起因：用旧环境训出来的策略"站得住但动作做不出来"，视频里机器人一直踉跄。
> 结论是**环境设计错了**，不是超参没调好。这份文档记录推倒重来的全过程。

---

## 一、旧环境错在哪

旧环境 (`g1_deploy.py`) 继承 MuJoCo Playground 的 G1 Joystick 环境，
把速度指令固定为零复用它的"站立"能力，再叠加一个上肢跟踪奖励。

| | 旧环境 | BeyondMimic |
|---|---|---|
| 跟踪对象 | 上肢 14 个**关节角** | 全身 14 个 **body link 的三维位置/朝向/线速度/角速度** + 根节点 anchor |
| 下肢 | 只有「靠近默认站姿」正则 | 一起跟踪 |
| **终止条件** | **只在摔倒时终止** | **跟踪误差超阈值即终止** |
| reset | 永远从站立姿态、动作第 0 帧 | **RSI**：参考轨迹随机时刻的完整状态 |
| 奖励 | 继承 joystick 一堆 locomotion 项 + 2 项自定义 | 6 项跟踪 + 3 项惩罚，无残留 |
| 采样 | 均匀 | 自适应：失败率高的时间段加权 |

### 最致命的是终止条件

旧环境里「站着不动」是一个**高回报策略**：

```
不摔倒 → episode 跑满 → 累计奖励高
跟踪项只占单步奖励的一部分，不跟踪的代价远小于摔倒的代价
```

策略于是收敛到「站稳 + 手臂随便挥挥」。这解释了为什么指标好看
（500/500 步不摔）而视频难看 —— **我用「没摔倒」当成了动作质量的证据**，
而这正是我在 `sim2sim排查全过程.md` 里写了三遍要避免的错误。

BeyondMimic 的早停让「不跟踪」直接砍断 episode，混不了分。

---

## 二、为什么不能直接用它的代码

| 实现 | 依赖 | AMD 上 |
|---|---|---|
| `HybridRobotics/whole_body_tracking`（原版） | Isaac Lab 2.1.0 + Isaac Sim 4.5.0 | ❌ CUDA 独占 |
| mjlab 复现版 | MuJoCo-**Warp** | ❌ CUDA 独占 |
| 本项目 | MuJoCo **MJX** (JAX-ROCm) | ✅ |

所以只能按源码把 MDP 在 MJX 里重新实现一遍，逐项对齐奖励公式、
权重、std、终止阈值。

### 对齐清单（对照 `tracking_env_cfg.py`）

| 项 | 权重 | std |
|---|---|---|
| `motion_global_anchor_pos` | 0.5 | 0.30 |
| `motion_global_anchor_ori` | 0.5 | 0.40 |
| `motion_body_pos` | 1.0 | 0.30 |
| `motion_body_ori` | 1.0 | 0.40 |
| `motion_body_lin_vel` | 1.0 | 1.00 |
| `motion_body_ang_vel` | 1.0 | 3.14 |
| `action_rate_l2` | −0.1 | — |
| `joint_limit` | −10.0 | — |

奖励形式统一是 `exp(-error / std²)`。

终止：`anchor_z > 0.25m`、`anchor 朝向 > 0.8`、四个末端 `z > 0.25m`、超时。

PPO：网络 `[512,256,128]`、`entropy=0.005`、`gamma=0.99`、`lam=0.95`、`clip=0.2`。

### 有意偏离的地方（都是平台/框架限制，不是随意改的）

| 项 | BeyondMimic | 本项目 | 原因 |
|---|---|---|---|
| 学习率 | 1e-3 + 自适应 KL | 1e-3 固定 | brax PPO 没有 rsl_rl 的自适应 KL 调度 |
| minibatch | `num_mini_batches=4`, `epochs=5` | 16 × 2 | gfx1100 的 XLA 编译图规模上限，乘积必须 ≤ 32 |
| `action_scale` | 逐关节 `0.25·力矩上限/刚度`（0.30~0.90） | 统一 0.5 | Playground 的 G1 用位置执行器，`actuator_forcerange` 全是 0，公式退化成除零；两个模型的 kp 也不是一套。0.5 正好落在原版区间中间 |
| 训练步数 | 30000 iter × 24 × 4096 ≈ **2.95B** | 400~500M | 单卡 4 天窗口内跑不完 2.95B |
| 自适应采样 | 按失败率对时间段加权 | 均匀 RSI | 先验证主干，这一项是加速收敛用的 |

---

## 三、动作数据要补什么

我们的 npz 只有 `root_pos` / `root_quat` / `joint_pos`。BeyondMimic 的奖励在
三维空间里算，需要每个 body link 的位置、朝向、线速度、角速度和关节速度。

`motion_prep.py` 用 MuJoCo 正运动学逐帧摆好 `qpos` 读 `xpos`/`xquat`，
速度用中心差分（姿态用四元数差转旋转矢量）。产出：

```
salute_upright: 310 帧 6.20s  |lin_vel|max 1.42 m/s  |ang_vel|max  5.54 rad/s
tennis:         298 帧 5.96s  |lin_vel|max 1.49 m/s  |ang_vel|max 11.65 rad/s
```

---

## 四、移植过程中踩的坑

### 4.1 `mjx_env` 没有 `init`

Playground 的 API 是 `mjx_env.make_data(...)` + `mjx.forward(...)`，
参数名是 `naconmax` 不是 `nconmax`。

### 4.2 body 线速度的参考点

`data.cvel` 是 **com-based** 空间速度：线速度分量对应的是 `subtree_com`
那一点的速度，不是 body 坐标系原点的速度。而参考轨迹是 `xpos` 的差分。

```python
v_origin = cvel[3:6] + cross(cvel[0:3], xpos - subtree_com[rootid])
```

不修正的话平均差 0.26 m/s，末端手腕差到 1.0 m/s：

| body | cvel 直接 | com 修正后 | `mj_objectVelocity` |
|---|---|---|---|
| pelvis | 0.0008 | 0.0000 | 0.0018 |
| left_wrist_yaw_link | 0.9461 | 0.0002 | 0.1017 |
| right_wrist_yaw_link | 1.0076 | 0.0006 | 0.1093 |
| **平均** | **0.2603** | **0.0001** | 0.0313 |

角速度用 `cvel[0:3]` 就是对的（世界系），不用换算。

### 4.3 自由关节的角速度是机体系

MuJoCo 自由关节：`qvel[0:3]` 是**世界系**线速度，`qvel[3:6]` 是**机体系**角速度。
RSI 时我把参考的世界系角速度直接写进去了。tennis 峰值 11.65 rad/s，
误差平方和一除 `std²=9.86` 就把 `exp` 打到 0 —— 速度奖励恒为零。

```python
ang_body = quat_rotate_inv(root_quat, ang_world)
qvel = concatenate([lin_world, ang_body, joint_vel])
```

### 4.4 用「完美跟踪者」验收环境

改完之后不能只看"能跑"，要验证**奖励函数本身是对的**：
把状态精确设成参考轨迹某一帧，此时所有跟踪奖励都应该 ≈ 1。

```
  帧   anchor_pos  anchor_ori   body_pos   body_ori  body_lin_vel  body_ang_vel
   0      1.0000      1.0000     1.0000     1.0000        1.0000        1.0000
 100      1.0000      1.0000     1.0000     1.0000        1.0000        1.0000
 250      1.0000      1.0000     1.0000     1.0000        1.0000        1.0000
```

任何一项偏离 1，就说明坐标系/参考点/单位约定还有 bug ——
在这种环境里策略再好也拿不到分，训练必然跑偏。
**这个检验应该在写完奖励函数的第一时间就做**，比事后看曲线便宜得多。

### 4.5 brax 的 wrapper 不认 Playground 的 State

Playground 的 `State` 用 `.data`，brax 的 `AutoResetWrapper` 找 `.pipeline_state`：

```
AttributeError: 'State' object has no attribute 'pipeline_state'
```

要传 `wrap_env_fn=wrapper.wrap_for_brax_training`（Playground 自带的）。

### 4.6 `jax.sharding.PositionalSharding` 也没了

JAX 0.11 不只移除了 `device_put_replicated`，`PositionalSharding` 也一起没了。
单卡场景直接 `jax.device_put(stacked, devices[0])` 即可。

---

### 4.7 `sim_dt=0.005` 在 Playground 的 G1 上会积分发散

照抄 BeyondMimic 的 `sim.dt=0.005` + `decimation=4`，结果理想控制器下
`base_z` 飞到 **−165911**。扫描：

| `sim_dt` | 子步数 | 零动作存活 | 理想控制器存活 | 最低 base_z |
|---|---|---|---|---|
| **0.005** | 4 | 11.6/60 | 12.5/60 | **−165911.594** ❌ |
| 0.004 | 5 | 14.1/60 | 15.0/60 | 0.553 |
| **0.002** | 10 | 14.5/60 | 15.0/60 | 0.555 ✅ |
| 0.001 | 20 | 14.4/60 | 15.0/60 | 0.555 |

原因是两个模型的刚度不是一个量级：

- BeyondMimic：`stiffness = armature × (2π·10)²`，10 Hz 自然频率、
  阻尼比 2 —— 刻意做得很软，0.005 够用。
- Playground 的 G1：`kp=75` 配极小电枢，刚度高得多。

用回 Playground 验证过的 **0.002**。

### 4.8 ⭐ 最关键的一条：动作幅度物理上够不到

这一条和奖励设计完全无关，但它单独就足以让手臂动作做不出来。

位置执行器稳态下 `q ≈ ctrl`，而 `ctrl = default_pose + action × action_scale`。
brax 的 `NormalTanhDistribution` 把 action 压在 **[−1, 1]**，
所以关节可达范围就是 `default_pose ± action_scale`。

实测参考轨迹要求的峰值偏移：

| 动作 | 最大需求 | `action_scale=0.5` 能给 | 缺口 |
|---|---|---|---|
| salute | 右肘 **1.709 rad (98°)** | 0.5 rad (28.6°) | **3.4×** |
| tennis | 左/右肩滚 **2.051 rad (118°)** | 0.5 rad | **4.1×** |

tennis 有 **24% 的上肢 (帧×关节) 目标够不到**，salute 有 9.3%。
手臂物理上抬不起来，训多久都没用。

**为什么 BeyondMimic 没这个问题**：它用 rsl_rl，策略是无界高斯，
动作不截断，所以小 `action_scale` 也能输出大偏移。
brax 有 tanh，必须自己保证可达性。

**修法**：目标位置改成相对**参考姿态**而不是 `default_pose`：

```python
motor_targets = ref_joint_pos[t] + action * action_scale
```

策略只需输出**修正量**，可达性由构造保证。这也是 DeepMimic 系
残差控制的常见做法。修完之后零动作（纯跟随参考角度）就能完成
剩余动作的 31~36%，body 位置误差 0.10 m —— RL 只需要学平衡修正。

| | 修之前 | 修之后 |
|---|---|---|
| 零动作存活 | 15/60 步 | 完成剩余动作 31~36% |

### 4.9 episode 长度与「动作放完」

`episode_length = T` 加末帧钳位有个浪费：RSI 平均从中点起步，
约**一半样本**花在"保持末帧姿态"上。

原版是在 episode 内瞬移到新的 RSI 点继续（`_resample_command`）。
本项目改成**动作放完即结束 episode** —— 更简单，所有样本都有效。
代价是末帧被当成 terminal（不 bootstrap），对动作末尾的状态价值
有轻微低估，属于已知可接受的偏差。

---

## 五、两个错误是独立的

回头看，旧环境同时踩了两个坑，而且**互相掩盖**：

| # | 错误 | 后果 | 单独修能否解决 |
|---|---|---|---|
| 1 | 奖励/终止让「站着不动」成为最优解 | 策略主动放弃跟踪 | 否 —— 即使想跟踪也够不到 |
| 2 | `action_scale` 太小，动作够不到 | 手臂物理上抬不起来 | 否 —— 即使能抬也没动力去抬 |

只修任何一个都看不到改善，这大概是它藏了这么久的原因。

---

## 六、验收标准也换了

旧标准（都是坏指标）：

| 指标 | 为什么坏 |
|---|---|
| 「500/500 步不摔」 | 站着不动也满分 |
| 「上肢关节角误差 19°」 | 摔倒后手臂还在动，误差照样小；和视觉上「像不像」相关性弱 |

新标准：

1. **完美跟踪者检验** —— 状态精确设成参考帧，六项奖励必须全 = 1.0000
2. **body 位置误差**（米）—— 在三维空间里量，和视觉直接对应
3. **完成度** —— 走完参考动作的百分比，而不是「活了多少步」
4. **并排视频** —— 左参考、右策略，人眼判断

第 4 条才是最终标准。前三条只用来筛掉明显不行的，不用来宣布成功。

---

## 七、⭐ 真正的根因：auto-reset 不还原 info

前面 4.1~4.9 修的都是真 bug，但修完之后训练**仍然单调劣化** ——
三轮（61M / 61M / 51M 步）全部是：未训练的网络最好，越训越差。

### 消融：三组曲线完全重合

| 组 | 配置 | `ep_len` 走势 | reward 走势 |
|---|---|---|---|
| 基线 | 有惩罚 + entropy 1e-3 | 36 → 19.4 | 129 → 39 |
| A | **关掉两个惩罚** | 36 → 22.4 | 131 → 50 |
| B | 关惩罚 + **零熵** | 36 → 20.9 | 131 → 46 |
| C | 有惩罚 + **零熵** | 36 → 22.5 | 129 → 49 |

三组几乎重合。**劣化与奖励构成、与熵都无关** —— 这个特征本身就说明
问题不在奖励设计，而在训练数据。

### 根因

Playground 的 `BraxAutoResetWrapper` 默认 `full_reset=False`，
它的文档字符串写得很明白：

> If `full_reset` is disabled (default):
>   * the environment will reset to a cached first state.
>   * **only data and obs are reset, not the environment info.**

也就是说 auto-reset 时：

- `data`（qpos/qvel）→ 回到缓存的**第一帧** RSI 状态
- `obs` → 回到第一帧
- **`info` → 原样保留**

而我的参考索引存在 `info["motion_idx"]` 里。于是第一个 episode 结束后，
**机器人的物理状态回到了起点，参考索引却继续往前走** —— 两者永久错位。
再加上终止条件里有 `motion_idx >= T-1`，索引一旦走到末帧就每步都 done，
之后全是 1 步的垃圾样本。PPO 从头到尾都在拿废数据训练。

### 修复

```python
wrap_env_fn=functools.partial(wrapper.wrap_for_brax_training,
                              full_reset=True)
```

`full_reset=True` 会在 done 时真正调用 `env.reset`，`info` 一并重置。
这也正是 RSI 该有的语义：每次重置到参考轨迹的**随机**时刻，
而不是永远复用第一次那一帧。

### 效果

| step | reward | `ep_len` | body_pos 误差 |
|---|---|---|---|
| 0 | 129.39 | 36.0 | 0.0993 m |
| 6M | 171.26 | 44.1 | 0.0886 m |
| 12M | 223.50 | 56.6 | 0.0842 m |
| 18M | 241.98 | 60.8 | 0.0823 m |
| 24M | 288.66 | 71.2 | 0.0751 m |
| 30M | **311.04** | **76.9** | **0.0773 m** |

三项指标全部单调改善。同一份代码、同一套超参，只改这一个布尔值。

### 这个 bug 也解释了旧方案「手臂乱挥」

旧环境 (`g1_deploy.py`) 的 `motion_idx` 是**取模循环**的
（`mod(motion_idx + 1, ref_len)`），所以错位不会让 episode 崩掉 ——
但会让策略在**错误的相位**上被要求跟踪。看起来就是手在乱动。

**这个 bug 从第一天就在，只是在旧环境里表现得不那么致命，**
所以一直被当成"奖励没调好"。

---

## 八、复盘：为什么查了这么久

按发现顺序，一共 8 个 bug：

| # | bug | 单独修能看到改善吗 |
|---|---|---|
| 1 | `mjx_env` 没有 `init`（API 名） | 报错，必修 |
| 2 | `cvel` 参考点是 subtree_com | 否 |
| 3 | 自由关节角速度是机体系 | 否 |
| 4 | `sim_dt=0.005` 积分发散 | 否 |
| 5 | `action_scale` 太小，动作够不到 | 否 |
| 6 | 软限位 0.9 与参考轨迹冲突 | 否 |
| 7 | 奖励量级 / 熵配比 | 否 |
| 8 | **auto-reset 不还原 info** | **是** |

前 7 个都是真 bug，但只要第 8 个还在，修任何一个都看不到改善。
这就是为什么"改一个测一轮"的策略一直没有信号。

**教训**：当消融实验里**多组差异很大的配置给出几乎相同的曲线**时，
不要继续在被消融的那些维度上找原因 —— 应该去查那些**所有组共享**的东西
（数据管线、包装器、环境状态机）。这个信号我第一次看到消融结果就该抓住。

---

*（最终训练结果待补）*
