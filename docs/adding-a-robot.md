# 如何接入一台新机器人

BotverseX 用 **Runtime manifest + capability 协议** 扩展硬件，不必为每台机器人重写整站。

## 清单

1. **`apps/realtime/config/robots.json`** — 加 entry：`runtime_id`、`transport`、`capabilities`、`capability_tags`、`ui.route`。**注意**：`state_endpoint` 和 `ui.onboarding_steps` 字段已废弃（T2-3 清理），统一走 `GET /api/robots/<id>/state`，onboarding 步骤硬编码在 `apps/web/src/components/setup/setup-types.ts`。
2. **`apps/realtime/runtimes/<id>/__init__.py`** — 实现 `RuntimeInfo` + `create_reader()`（只读状态）；写控制走 CLI/daemon 时 `create_writer()` 可抛 `NotImplementedError`。
3. **`apps/realtime/runtimes/_capabilities.py`** — 可选：声明 `RobotCapability` 集合（如 `SO101_CAPS`）供未来通用工作台面板注册表使用。**注意**：`RUNTIME_CAPABILITIES` dict 和 `capability_tags()` 函数已删除（T2-3 清理），前端直接读 manifest 里的 `capability_tags` 数组。
4. **专用 router（可选）** — 若有 daemon/CLI wrapper：`apps/realtime/api/<robot>.py`，注册到 `main.py`；通用 state 仍走 `GET /api/robots/<id>/state`。
5. **URDF** — 放进 `apps/realtime/static/urdf/<id>/`。
6. **前端** — 仅在有特化端点时建 `lib/<robot>Api.ts`；状态优先 `getRobotState(id)` + `useRobotRuntimeState(id)`。
7. **Tour** — `apps/web/src/components/onboarding/tours.ts` 加卡片 `data-tour` 一步。
8. **Copilot** — `copilot_site_knowledge.md` 加成熟度标签（教学演示 / 课题实验 / 论文复现）。

## 验收

- `GET /api/runtimes` 与 `GET /api/robots` 可见新 runtime。
- `GET /api/robots/<id>/state` 返回 JSON（哪怕 placeholder），**无需再改** `robots.py` 主分支（generic reader fallback）。
- 遥操/录制若有 live joints：`WS /ws/robots/<id>/state` 在运行时 ≥5Hz 推送。
- Robots 页卡片可进入向导或工作台。

## 参考样板

**B601-RS** 是第一个走完通用契约的真机集成：

| 层 | 路径 |
|----|------|
| Manifest | `config/robots.json` → `b601_rs` |
| Runtime reader | `runtimes/b601_rs/__init__.py` |
| Capability 特化 | `api/b601.py`（calibrate / recover / snapshot） |
| 通用 state | `GET /api/robots/b601_rs/state` |
| 前端 WS | `useRobotRuntimeState('b601_rs')` |
| 运动学 / 重力补偿 | `api/b601_kinematics.py`、`api/b601_gravity_comp.py` + `runtime_lock.py` |
| ROS2 bridge | `api/b601_ros2.py` — 子进程 bringup，不嵌入 FastAPI |

详见 [b601-kinematics.md](./b601-kinematics.md)、[b601-ros2.md](./b601-ros2.md)。

## B601-DM 双臂（预埋）

当 `runtimes/b601_dm/` 出现并在 manifest 声明 `bimanual` capability 时，前端 URDF Viewer 启用双臂镜像 UI，无需新网站。

## Adding a reBot B601-DM (Damiao motors)

B601-DM 是 B601-RS 的兄弟款，把 RobStride CAN 电机换成 Damiao 4340P/4310，CAN 适配器从 SocketCAN 换成 USB-CAN 串口桥（Damiao 官方协议）。BotverseX 已经把 `b601_dm` 和 `bi_b601_dm` 写进 `apps/realtime/config/robots.json`，复用同一套 `apps/realtime/api/b601.py`（通过 `B601_ARM_VARIANT=dm` 切换）。

### 前置依赖

- **lerobot fork**（不是上游 lerobot）：`pr-3967` 分支，已经把 `rebot_b601_dm_follower` / `bi_rebot_b601_follower` / `rebot_102_leader` / `bi_rebot_102_leader` 注册成 lerobot 标准类型。
  ```bash
  git clone -b pr-3967 https://github.com/<your-fork>/lerobot.git
  cd lerobot && pip install -e .
  ```
- **motorbridge**：Damiao USB-CAN 桥的 CLI（`motorbridge-gateway`、`motorbridge-cli`）。
- **aarch64 only**（DGX Spark / Jetson Orin / Raspberry Pi 5 with NVMe）：用 cu130 wheels。`pip install torch --index-url https://download.pytorch.org/whl/cu130`。
- **x86_64**：用标准 wheels 即可。

### Linux 主机准备

```bash
# Damiao USB-CAN 适配器通常枚举为 /dev/ttyACM2（与 SO-101 主控臂会冲突，建议先插 B601 再插 SO-101）
# 卸载 brltty（它会抢占 USB-CAN 设备）
sudo systemctl stop brltty 2>/dev/null || true
sudo systemctl disable brltty 2>/dev/null || true
sudo apt remove -y brltty 2>/dev/null || true

# 给 dialout 组访问串口的权限
sudo usermod -aG dialout $USER
# 注销重新登录后生效；或临时 chmod：
sudo chmod 666 /dev/ttyACM2
```

### 在 BotverseX 中启用

1. 打开 `http://127.0.0.1:5173/robots/b601_dm`。
2. 连接面板：选 Damiao USB-CAN 串口（默认 `/dev/ttyACM2`）+ Star Arm 102 主臂串口。
3. 走和 B601-RS 一样的流程：唤醒从臂 → 校准 → 遥操 → 录数据 → 训练 → 部署。
4. **部署**：B601-DM 的 Pi0.5 推理同样走「算力节点」抽象。默认是 `local`（本机 CPU/本地 GPU）；如果你有一台远端 GPU 机器（朋友的 GB10、家里的服务器、云 VM），到 `设置 → 算力节点` 添加一个节点即可。BotverseX 不假设你拥有任何特定型号的 GPU 机器。

### 双臂（bi_b601_dm）

- 两只 B601-DM 从臂 + 两只 Star Arm 102 主臂。
- lerobot fork 已经把 `bi_rebot_b601_follower` 和 `bi_rebot_102_leader` 注册成标准类型。
- 路由：`/robots/bi_b601_dm`。前端 URDF Viewer 自动启用双臂镜像 UI（`bimanual` capability）。

### 参考

- Seeed reBot B601-DM getting-started：`https://wiki.seeedstudio.com/rebot_b601_dm/`
- lerobot fork：见 `~/lingbot/lerobot` 上的 `pr-3967` 分支（参考实现）
- Damiao 电机手册：`https://damiaomotor.com/`

## Adding LeKiwi (mobile manipulator)

LeKiwi 是一只会跑的机械臂：3 轮全向 Kiwi 底盘 + SO-101 6 轴臂。lerobot fork 已经把 `lekiwi` 和 `lekiwi_orin`（Jetson Orin 专用）注册成标准类型，BotverseX 把它接进 runtime 系统。

### 注册

`apps/realtime/config/robots.json` 已经有 `lekiwi` 条目，`apps/realtime/runtimes/lekiwi/__init__.py` 是 reader/writer stub（注册 `RuntimeInfo`，真实硬件驱动走 lerobot CLI）。前端 `apps/web/src/lib/robotCatalog.ts` 有 LeKiwi 卡片元数据。

### 在 BotverseX 中使用

1. 打开 `/robots` → 点 LeKiwi 卡片 → 进入 `/robots/lekiwi`。
2. 走 4 阶段上手：连接 → 遥操 → 录数据 → 训练并运行。
3. 遥操两种方式：
   - **SO-101 主臂**（经典）：插主臂串口，用 `lerobot-teleoperate`。
   - **Quest 2/3 WebXR**（省钱）：在 Quest 浏览器打开 `https://<本机 IP>:8002/quest`，点「进入 XR」。手柄位姿 → 末端执行器；左摇杆 → 底盘移动；扳机 → 夹爪；B 键 → 急停。
4. 训练走云端 Qualia（Pi0.5 / SmolVLA / ACT），部署走算力节点（默认本机，可配远端 GPU）。

### 应用场景：握手采集

LeKiwi 的招牌应用场景是「在人群中握手」。BotverseX 在 Workflow Editor 里加了 `lekiwi_handshake_collect` 节点（在「SCENARIOS」分类下），按三段式计划采数据：

| 层级 | 目标 | 描述 |
|------|------|------|
| L1 | 20 集 | 单人正面握手，固定距离 |
| L2 | 50 集 | 不同接近角度、不同手高度 |
| L3 | 100 集 | 人群环境、动态干扰、噪声 |

每达到一层，模型在新一层上能跑得更稳。前端有 `LeKiwiHandshakeProgressCard` 组件可视化「还差多少集就到下一层」。

### 参考

- lerobot fork 的 `lekiwi` 实现：`src/lerobot/robots/lekiwi/`
- Quest 遥操 API：`apps/realtime/api/quest_teleop.py`
- 三段式数据计划：`~/brainbot/lingbot_configs/handshake_data_plan.md`（GB10 上的参考实现）

## Adding Quest 2/3 WebXR teleop

Quest 遥操是 BotverseX 的「数据采集乘数器」——用户没有主臂也能采数据，Quest 2/3 比 SO-101 主臂便宜得多。

### 后端

`apps/realtime/api/quest_teleop.py` 提供：

| 路径 | 方法 | 说明 |
|------|------|------|
| `/quest` | GET | WebXR HTML 页面（Quest 浏览器打开） |
| `/ws/quest` | WS | Quest ↔ Local Agent 双向：Quest 发位姿，Local Agent 发臂状态 |
| `/api/quest_teleop/start` | POST | 启动 Quest 驱动的遥操子进程 |
| `/api/quest_teleop/stop` | POST | 停止 |
| `/api/quest_teleop/status` | GET | 当前状态 |
| `/api/quest_teleop/url` | GET | 告诉 UI 在 Quest 上打开哪个 URL |

### 在 Setup 页集成

Setup 页可以加一个「用 Quest 遥操」选项，提示用户在 Quest 浏览器打开 `https://<本机 IP>:8002/quest`。Local Agent 必须在跑，且 Quest 和 Local Agent 在同一局域网。

### 操作映射

| Quest 输入 | 机器人动作 |
|-----------|-----------|
| 右手柄位姿 | 末端执行器目标位姿 |
| 右手扳机 | 夹爪闭合 / 松开 |
| 左摇杆 | 底盘移动（仅 LeKiwi） |
| 右手 B 键 | 急停（卸力） |

## Adding Isaac Sim pretraining (Workflow node)

Isaac Sim 仿真预训练是「冷启动利器」——没有真机数据也能先训一版策略，再用真机数据微调。

### Workflow Editor 节点

`isaac_sim_pretrain` 节点在「SIMULATION」分类下。配置：

| 字段 | 默认 | 说明 |
|------|------|------|
| scenario | `roco_task_board` | IROS 2026 task-board（默认） |
| robot | `lekiwi` | lekiwi / so101 / unitree_g1 / ... |
| algorithm | `rl_ppo` | rl_ppo / sac / diffusion_policy |
| total_steps | 100_000 | 仿真训练步数 |
| compute_node_id | （空） | 用默认算力节点 |
| output_model_id | （空） | 训完后推到 HF 的 repo id |

### 后端

节点执行时调远端算力节点上的 `~/roco/run_roco.sh`（或类似脚本）。产出的 ckpt 通过 `sync_model_to_remote.py` 反向同步回 BotverseX 云端模型仓库，再分发到各台算力节点。

> 注：仿真预训练目前是「先注册节点 + UI 可拖」状态。后端调用脚本（`run_roco.sh` 等）需要用户在自己的算力节点上准备好。BotverseX 不假设你拥有 GB10——任何能跑 Isaac Sim 的 GPU 机器都行。

## Adding AmazingHand (dexterous hand, Preview)

AmazingHand 是一只 8 自由度人形手，可接在 Reachy2 腕部。BotverseX 把它注册成 preview runtime——卡片在 `/robots` 可见，但完整遥操/录制/训练/部署闭环还在路上。

### 注册

`apps/realtime/config/robots.json` 有 `amazing_hand` 条目，标 `preview: true`。前端 catalog 卡片有 "Preview" 徽章。`/robots/amazing_hand` 路由用 `RobotPreview` 组件，显示「现在能用 / 正在来的路上」两栏。

### 路线图

- 现在能用：在 `/robots` 看到卡片，知道平台支持灵巧手
- 正在来的路上：遥操（Quest 手柄或数据手套）、录制示教、云端训练 Pi0.5 / 灵巧手专用 VLA、部署到 AmazingHand 实物

## Adding Unitree G1 (humanoid, Preview)

Unitree G1 是一只 16+ 自由度人形机器人。BotverseX 把它注册成 preview runtime，让生态看见平台「从机械臂走向人形」的方向。

### 注册

`apps/realtime/config/robots.json` 有 `unitree_g1` 条目，标 `preview: true`。前端 catalog 卡片有 "Preview" 徽章。`/robots/unitree_g1` 路由用 `RobotPreview` 组件。

### 路线图

- 现在能用：在 `/robots` 看到卡片
- 正在来的路上：
  - RL 步态策略作为 Workflow 节点（UFO / LearningHumanoidWalking / kungfu）
  - Isaac Sim 仿真预训练 → 部署到 G1
  - Quest 3 全身遥操
  - 人形 + 灵巧手 + 移动底盘组合场景

