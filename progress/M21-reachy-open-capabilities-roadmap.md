# BotverseX × Reachy Mini 开源能力兼容升级 — 完整规划

日期: 2026-07-02
作者: amd + Cursor
状态: 进行中（M21）

## 1. 北极星

让 BotverseX 用户**一键把 Reachy Mini 变成可对话、可表演、可学习**的桌面机器人，**且所有能力对齐 Pollen 官方开源生态**——能用官方 App、能装社区 App、能用官方数据集、能进 BotverseX 工作流训练。

## 2. 原则

- 开源优先：有官方/社区可抄就抄，不闭门造车
- 本机 Agent 直连：硬件相关一律走 `agentFetch` → `:8002` → daemon `:8010`
- 云端 UI 编排：botversex.feispace.me 不碰硬件
- 与现有架构同构：复用 `reachy_proxy.py` 的 `_forward_reachy_json` 模式
- 不破坏 SO-101：串口标签化优先做

## 3. 显式不做

- 不自研语音/LLM（接 OpenAI/Gemini/HF）
- 不做无线版 Reachy（仅 USB Lite + 本机 Agent）
- 不替换 Allan SDK（保持 `reachy_mini_Allan` adapter venv）
- 不做 WebRTC 远程（P3）

## 4. Allan Daemon 实测 API 面（:8010，全部 `/api` 前缀）

> 这是 M21 实施的「可抄清单」。源码：`/home/amd/sdk/reachy_mini_Allan/src/reachy_mini/daemon/app/routers/`

### 4.1 Apps（`routers/apps.py`，274 行）— **M21 必须全代理**

| Method | Path | Body / Query | 返回 | 说明 |
|--------|------|--------------|------|------|
| GET | `/api/apps/list-available` | — | `AppInfo[]` | 所有可用（含未装） |
| GET | `/api/apps/list-available/{source_kind}` | path: `hf_space\|installed\|local` | `AppInfo[]` | 按来源 |
| POST | `/api/apps/install` | `AppInfo` | `{job_id}` | 后台安装 |
| POST | `/api/apps/install-private-space` | `{space_id}` | `{job_id}` | 私有 Space（需 HF token） |
| POST | `/api/apps/remove/{app_name}` | — | `{job_id}` | 后台卸载 |
| POST | `/api/apps/start-app/{app_name}` | — | `AppStatus` | 启动 App |
| POST | `/api/apps/restart-current-app` | — | `AppStatus` | 重启当前 |
| POST | `/api/apps/stop-current-app` | — | `None` | 停止当前 |
| GET | `/api/apps/current-app-status` | — | `AppStatus\|None` | 当前状态 |
| GET | `/api/apps/job-status/{job_id}` | — | `JobInfo` | 安装/卸载/更新进度 |
| WS | `/api/apps/ws/apps-manager/{job_id}` | — | 流式 `JobInfo` | 实时进度 |
| GET | `/api/apps/check-updates?force=bool` | — | `AppUpdatesResponse` | 检查更新（5min 缓存） |
| POST | `/api/apps/update/{app_name}` | — | `{job_id}` | 更新到最新 |

`AppInfo` 字段（`reachy_mini/apps`）：`name, description, url, source_kind, extra{}`

### 4.2 Daemon（`routers/daemon.py`）

| Method | Path | Query | 返回 |
|--------|------|-------|------|
| POST | `/api/daemon/start` | `wake_up=bool` | `{job_id}` |
| POST | `/api/daemon/stop` | `goto_sleep=bool` | `{job_id}` |
| POST | `/api/daemon/restart` | — | `{job_id}` |
| GET | `/api/daemon/status` | — | `DaemonStatus` |

### 4.3 Motors（`routers/motors.py`）

| Method | Path | 返回 |
|--------|------|------|
| GET | `/api/motors/status` | `{mode: enabled\|disabled\|gravity_compensation}` |
| POST | `/api/motors/set_mode/{mode}` | `{status}` |

**注：** `gravity_compensation` 是合法值，BotverseX UI 禁用是历史遗留，M21 重新评估是否解禁。

### 4.4 Move（`routers/move.py`，306 行）— **M24 必看**

| Method | Path | Body / 返回 |
|--------|------|--------------|
| POST | `/api/move/goto` | `GotoModelRequest` → `MoveUUID` |
| POST | `/api/move/play/wake_up` | `MoveUUID` |
| POST | `/api/move/play/goto_sleep` | `MoveUUID` |
| GET | `/api/move/recorded-move-datasets/list/{dataset_name}` | `string[]` |
| POST | `/api/move/play/recorded-move-dataset/{dataset_name}/{move_name}` | `MoveUUID` ← **官方 HF 舞蹈/表情库入口** |
| GET | `/api/move/local-categories` | `string[]` |
| GET | `/api/move/local-moves/list/{category}` | `string[]` |
| POST | `/api/move/play/local-move/{move_name}` | `MoveUUID` |
| POST | `/api/move/stop` | `MoveUUID` body → `{message}` |
| GET | `/api/move/running` | `MoveUUID[]` |
| POST | `/api/move/set_target` | `FullBodyTarget` → `{status}` |
| WS | `/api/move/ws/set_target` | 流式 `FullBodyTarget` |
| WS | `/api/move/ws/raw/write` | raw serial 透传 |
| WS | `/api/move/ws/updates` | move 事件流 |

### 4.5 State（`routers/state.py`）— **DOA 是关键**

| Method | Path |
|--------|------|
| GET | `/api/state/present_head_pose?use_pose_matrix=bool` |
| GET | `/api/state/present_body_yaw` |
| GET | `/api/state/present_antenna_joint_positions` |
| GET | `/api/state/doa` → `{angle, speech_detected}` ← **声源定位，免装 App 即可用** |
| GET | `/api/state/full?with_*=bool...` |
| WS | `/api/state/ws/full?frequency=10&...` |

### 4.6 Volume（`routers/volume.py`）— **这就是 daemon 暴露的音频面**

| Method | Path | Body / 返回 |
|--------|------|--------------|
| GET | `/api/volume/current` | `VolumeResponse{volume, platform, device}` |
| POST | `/api/volume/set` | `VolumeRequest{0-100}` + 自动播测试音 |
| POST | `/api/volume/test-sound` | `TestSoundResponse{status, message}` |
| GET | `/api/volume/microphone/current` | `VolumeResponse` |
| POST | `/api/volume/microphone/set` | `VolumeRequest` |

**关键结论：** daemon 不暴露 `record`/`play_audio`/`tts` HTTP 端点。录音/TTS 由 Conversation App 在 subprocess 内通过 SDK 调。BotverseX 的音频控制 = volume + doa + 装 Conversation App。

### 4.7 Kinematics（`routers/kinematics.py`）

| Method | Path |
|--------|------|
| GET | `/api/kinematics/info` |
| GET | `/api/kinematics/urdf` |
| GET | `/api/kinematics/stl/{filename}` |

### 4.8 HF Auth（`routers/hf_auth.py`）— 装私有 Space 用

未读详情，M22 再补。

### 4.9 启动参数（`main.py` argparse）

- `--serialport auto`（默认）
- `--deactivate-audio`：`action="store_false"`，**默认 `use_audio=True`**，所以只要不传就有音频
- `--kinematics-engine {Placo, NN, AnalyticalKinematics}`（默认 AnalyticalKinematics）
- `--check-collision`
- `--sim` / `--mockup-sim` / `--headless`
- `--no-preload-datasets` / `--preload-datasets`
- `--autostart` / `--no-autostart`
- `--wake-up-on-start` / `--no-wake-up-on-start`
- `--goto-sleep-on-stop` / `--no-goto-sleep-on-stop`
- `--fastapi-host` / `--fastapi-port`
- `--localhost-only` / `--no-localhost-only`

## 5. 目标架构

```
浏览器 (botversex.feispace.me / localhost:5173)
  ├─ 静态 UI / URDF                       → 云端 nginx
  └─ /api/reachy/* / /ws/reachy/*        → 本机 :8002
                                            ↓
本机 Local Agent (apps/realtime, :8002)
  ├─ /api/reachy/* (现有 + 新增 apps/volume/doa/daemon/recorded-move/set_target)
  └─ /ws/reachy/* (state + set_target + apps-manager)
                                            ↓ HTTP/WS
Allan Daemon (:8010, FastAPI)
  ├─ /api/apps/* (官方 App 生命周期)
  ├─ /api/daemon/* /motors/* /move/* /state/* /volume/* /kinematics/*
  └─ App subprocess (Conversation App) → SDK → 音频/相机/电机
                                            ↓ USB
Reachy Mini 硬件
```

## 6. 里程碑路线图

| 里程碑 | 主题 | 估时 | 核心交付 |
|--------|------|------|----------|
| **M21** | 音频解禁 + Apps/Volume/DoA 代理 + 串口标签 | 2-3 天 | 解锁装 App 的基础 |
| **M22** | Reachy App 商店 UI + 一键对话 | 3-4 天 | 用户能聊 |
| **M23** | 摄像头 + head-tracker 代理 | 2-3 天 | 视觉/跟踪 |
| **M24** | 官方 HF 动作库 + Workflow 节点 + 训练管线 | 2-3 天 | 平台化 |
| **M25** | Copilot + 平台对齐 + 文档 + 发布 | 2 天 | 闭环 |

## 7. M21 详细任务（**当前正在做**）

### 7.1 配置改动 `apps/realtime/config/robots.json`

- [x] 去掉 `--deactivate-audio`（默认即开启音频）
- [ ] 增加 `capabilities.audio: true`、`apps: true`、`conversation: true`、`doa: true`
- [ ] 增加 `apps` 配置块：`{enabled: true, default_conversation_app: "reachy_mini_conversation_app"}`
- [ ] 增加 `volume` 配置块：`{controllable: true}`
- [ ] 评估 `gravity_compensation` 解禁（看 Allan daemon 是否支持）

### 7.2 后端代理 `apps/realtime/api/reachy_proxy.py`

新增透传路由（复用 `_forward_reachy_json`）：

**Apps（11 个）：**
- `GET  /api/reachy/apps/list-available`
- `GET  /api/reachy/apps/list-available/{source_kind}`
- `POST /api/reachy/apps/install` (body 透传 `AppInfo`)
- `POST /api/reachy/apps/install-private-space` (body `{space_id}`)
- `POST /api/reachy/apps/remove/{app_name}`
- `POST /api/reachy/apps/start-app/{app_name}`
- `POST /api/reachy/apps/restart-current-app`
- `POST /api/reachy/apps/stop-current-app`
- `GET  /api/reachy/apps/current-app-status`
- `GET  /api/reachy/apps/job-status/{job_id}`
- `GET  /api/reachy/apps/check-updates?force=bool`
- `POST /api/reachy/apps/update/{app_name}`
- `WS   /ws/reachy/apps-manager/{job_id}` (透传 daemon `/api/apps/ws/apps-manager/{job_id}`)

**Volume（5 个）：**
- `GET  /api/reachy/volume/current`
- `POST /api/reachy/volume/set` (body `VolumeRequest`)
- `POST /api/reachy/volume/test-sound`
- `GET  /api/reachy/volume/microphone/current`
- `POST /api/reachy/volume/microphone/set`

**State 增强：**
- `GET /api/reachy/state/doa` (声源定位)

**Daemon 生命周期：**
- `POST /api/reachy/daemon/start?wake_up=bool`
- `POST /api/reachy/daemon/stop?goto_sleep=bool`
- `POST /api/reachy/daemon/restart`
- `GET  /api/reachy/daemon/status`

### 7.3 串口标签化 `apps/realtime/api/setup.py`

- [ ] `_probe_feetech_on_port` 同时返回 motor_id 列表
- [ ] Reachy motor id=10（Dynamixel body_rotation）
- [ ] SO-101 Feetech STS3215（默认 id 1-6）
- [ ] Setup UI 显示「检测到 Reachy 在 ttyACM0 / SO-101 在 ttyACM1」
- [ ] `robots.json` SO-101 ports 改为 `auto`（M21 仅做配置，运行时分配留 M22）

### 7.4 前端 `apps/web/src/lib/reachyApi.ts`

新增：
```typescript
export interface ReachyApp {
  name: string; description: string; url: string;
  source_kind: 'hf_space' | 'installed' | 'local';
  extra?: Record<string, unknown>;
}
export interface ReachyAppStatus { name; pid; running; started_at; ... }
export interface ReachyJobInfo { job_id; command; status; logs[]; ... }

export function listReachyApps(source?: SourceKind): Promise<ReachyApp[]>
export function installReachyApp(app: ReachyApp): Promise<{job_id}>
export function removeReachyApp(name: string): Promise<{job_id}>
export function startReachyApp(name: string): Promise<ReachyAppStatus>
export function stopCurrentReachyApp(): Promise<void>
export function restartCurrentReachyApp(): Promise<ReachyAppStatus>
export function currentReachyAppStatus(): Promise<ReachyAppStatus | null>
export function getReachyJobStatus(jobId: string): Promise<ReachyJobInfo>
export function checkReachyAppUpdates(force?: boolean): Promise<AppUpdatesResponse>

// Volume
export function getReachyVolume(): Promise<VolumeResponse>
export function setReachyVolume(v: number): Promise<VolumeResponse>
export function playReachyTestSound(): Promise<TestSoundResponse>
export function getReachyMicVolume(): Promise<VolumeResponse>
export function setReachyMicVolume(v: number): Promise<VolumeResponse>

// DoA
export function getReachyDoA(): Promise<{angle: number; speech_detected: boolean} | null>

// Daemon lifecycle (full)
export function startReachyDaemon(wakeUp: boolean): Promise<{job_id}>
export function stopReachyDaemon(gotoSleep: boolean): Promise<{job_id}>
export function restartReachyDaemon(): Promise<{job_id}>
export function getReachyDaemonStatus(): Promise<DaemonStatus>
```

### 7.5 前端 `apps/web/src/pages/RobotReachyMini.tsx`

- 顶部加 **当前 App 徽章**（名/状态/Stop 按钮）
- 加 **音频面板**：扬声器音量滑块 + 麦克风电平滑块 + 测试音按钮
- 加 **DOA 指示器**：可选开启，显示声源方向（可视化或数字）
- 现有「守护进程与诊断」折叠区加 `daemon restart` 按钮

### 7.6 端到端验证

- `curl :8002/api/reachy/apps/list-available` 返回 HF App 列表
- `curl :8002/api/reachy/volume/current` 返回音量
- `curl :8002/api/reachy/state/doa` 返回 DOA（有音频时）
- `curl :8002/api/reachy/daemon/status` 返回 daemon 状态
- 不破坏 SO-101 Setup
- 不破坏现有 `/api/reachy/move/*` `/api/reachy/state/*`

### 7.7 进度文档

- [ ] 写 `progress/M21-reachy-apps-audio.md`
- [ ] 更新 `progress/README.md`

## 8. M22 详细任务（M21 完成后启动）

### 8.1 后端

- `apps/realtime/api/reachy_proxy.py` 新增 `/api/reachy/conversation/*`：
  - `POST /conversation/start` (body: `{backend, api_key?, model?, head_tracker?, local_vision?}`)
    - 自动 install `reachy_mini_conversation_app`（若未装）
    - `start-app` 时设 env: `OPENAI_API_KEY` / `GEMINI_API_KEY` / `BACKEND_PROVIDER` / `MODEL_NAME`
  - `POST /conversation/stop`
  - `GET  /conversation/status`
- API Key 安全：localStorage 存，POST 时通过 `agentFetch` 传到本机 Agent，subprocess env，不落盘不上云

### 8.2 前端

- 新页面 `/robots/reachy_mini/apps` (`ReachyMiniApps.tsx`)：
  - HF App 卡片网格
  - 安装进度（job-status 轮询或 WS）
  - 启动/停止按钮
- 新组件 `ConversationPanel.tsx`：
  - backend 切换 HF/OpenAI/Gemini
  - API Key 输入框（localStorage）
  - 实时状态：listening/thinking/speaking/idle
  - 工具按钮：dance/emotion/track_face
- Navbar Build 子菜单加「Reachy Apps」
- `App.tsx` 新路由

### 8.3 验收

- 用户能装 Conversation App + 启动 + 语音对话
- LLM 调 `dance` 工具 → Reachy 真的跳
- API Key 不出现在 ECS / 网络抓包

## 9. M23 详细任务

- 摄像头代理：`/api/reachy/camera/snapshot` + `/ws/reachy/camera` MJPEG
  - 优先用 Allan daemon 暴露的（若没有则 Local Agent 用 `cv2.VideoCapture` 打开 `/dev/video*`）
- head-tracker：`/api/reachy/camera/head-tracker/start|stop` (yolo|mediapipe)
- `RobotReachyMini.tsx` 加摄像头面板 + 跟踪开关
- `ConversationPanel` 暴露 `--head-tracker` 和 `--local-vision`

## 10. M24 详细任务

- 代理 `/api/move/recorded-move-datasets/list/{dataset}` + `/api/move/play/recorded-move-dataset/{dataset}/{move}`
- `RobotReachyMini.tsx` 动作库分官方 HF + 本地两栏
- 新 Workflow 节点：`ReachyPlayMoveNode`、`ReachyStartConversationNode`、`ReachyRecordDatasetNode`、`ReachyEmotionNode`
- `apps/api/app/services/training_service.py`：Reachy 自定义动作 → lerobot 格式
- 推理回灌：policy → `set_target` 流

## 11. M25 详细任务

- Copilot 诊断：`apps/web/src/lib/copilotDiagnostics.ts` 加 Reachy 音频/串口/App 状态检查
- Copilot playbooks：`reachy_install_conversation`、`reachy_audio_debug`、`reachy_serial_conflict`
- Setup 向导 Reachy 分支
- 文档：`docs/architecture.md`、`docs/customer-quickstart.md`、`apps/realtime/README.md`、`botversex-local-agent/README.md`
- 部署：`scripts/sync-local-agent.sh`、`scripts/deploy.sh`、`infra/docker/nginx.conf`

## 12. 横切关注点

### 12.1 串口冲突治理（M21 优先）

- `_probe_feetech_on_port` 返回 motor_id 列表
- Reachy: motor_id=10（Dynamixel）
- SO-101: Feetech STS3215（id 1-6）
- Setup UI 显示分配建议
- `robots.json` SO-101 ports → `auto`

### 12.2 性能

- 继续用 M20 的 `_probe_status_async()` 串行化模式
- App install 用 WS 流（`/ws/reachy/apps-manager/{job_id}`）
- WS 音频流单连接并发限制 1

### 12.3 安全

- API Key 永远只在本机 Agent subprocess env
- App install URL 白名单：`huggingface.co/spaces/*` + `github.com/*`
- Conversation App subprocess 用 `reachy` 用户权限

### 12.4 开源合规

- `THIRD_PARTY.md` 维护
- HF App 卡片显示作者 + License
- Conversation App 检查 License 后 attribution

### 12.5 Local Agent 仓库同步

每里程碑完成执行 `bash scripts/sync-local-agent.sh` 同步到 `botversex-local-agent/` 发布版。

## 13. 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| Conversation App 依赖 OpenAI/Gemini Key | 用户无 Key 用不了 | HF 后端作为零 Key 默认 |
| Allan SDK 与官方 SDK 漂移 | 代理 API 不兼容 | 维护兼容层 + 版本探测 |
| 音频硬件差异 | 部分 Reachy 无麦克风 | UI 显示「无音频」+ 不阻塞运动 |
| HF Hub 网络问题 | 装 App 失败 | 重试 + 离线 bundle（P3） |
| 串口冲突 | 与 SO-101 抢资源 | M21 优先做端口标签化 |
| LLM 工具调用安全 | 机器人乱动 | 工具白名单 + goto 限幅 |

## 14. 验收（端到端用户故事）

完成 M21-M25 后必须跑通：

- **A 零配置聊天**：插 Reachy → 装 Conversation App → HF 后端 → 聊天 → 让它跳 hello
- **B OpenAI 对话 + 工具**：填 Key → 启动 → 说「跳个舞」→ 自动 dance + 语音回复
- **C 视觉跟踪**：开摄像头 + head-tracker → 走到左边 → 头转左
- **D Workflow 编排**：拖 `StartConversation → PlayMove(hello) → RecordDataset` → 一键运行 → 录 10 段 → 进 Training
- **E Copilot 排障**：Reachy 不能说话 → 问 Copilot → 检测 audio → 指引重启
- **F 双机器人共存**：同时插 SO-101 + Reachy → Setup 自动识别 → 各自分配 ttyACM → 都能跑

## 15. 文件改动清单（汇总）

### 后端
```
apps/realtime/config/robots.json                    # 改 capabilities + audio/apps
apps/realtime/api/reachy_proxy.py                   # +~400 行 apps/volume/doa/daemon/recorded-move
apps/realtime/api/setup.py                          # 串口标签化
apps/realtime/requirements.txt                      # +huggingface_hub (M24)
apps/api/app/services/copilot_agent_service.py      # 新 playbooks (M25)
apps/api/app/data/copilot_playbooks_seed.json       # seed (M25)
apps/api/app/services/training_service.py           # Reachy 数据集 (M24)
```

### 前端
```
apps/web/src/pages/RobotReachyMini.tsx              # App 徽章 + 音频 + DOA + 摄像头
apps/web/src/pages/ReachyMiniApps.tsx               # 新页面 (M22)
apps/web/src/components/reachy/ConversationPanel.tsx # 新组件 (M22)
apps/web/src/components/reachy/ReachyCameraPanel.tsx # 新组件 (M23)
apps/web/src/lib/reachyApi.ts                       # 新 API + 类型
apps/web/src/lib/copilotDiagnostics.ts              # Reachy 诊断 (M25)
apps/web/src/components/workflow/nodes/Reachy*      # 4 个新节点 (M24)
apps/web/src/store/workflowStore.ts                 # 注册节点 (M24)
apps/web/src/types/workflow.ts                      # 节点类型 (M24)
apps/web/src/lib/workflowEngine.ts                  # 节点执行 (M24)
apps/web/src/components/layout/Navbar.tsx           # Build 子菜单 (M22)
apps/web/src/lib/routePrefetch.ts                   # 预拉
apps/web/src/App.tsx                                # 新路由 (M22)
```

### 配置 / 部署 / 文档
```
infra/docker/nginx.conf                             # /api/reachy/apps 代理
scripts/sync-local-agent.sh                         # 同步
scripts/deploy.sh                                   # ECS 部署
botversex-local-agent/                              # 同步发布
docs/architecture.md                                # 架构图更新
docs/customer-quickstart.md                         # Reachy 快速上手
progress/M21..M25-*.md                              # 5 篇进度文档
progress/README.md                                  # 索引更新
THIRD_PARTY.md                                      # License attribution
```

## 16. 执行顺序依赖图

```
M21 (音频解禁 + Apps/Volume/DoA 代理 + 串口治理) ← 当前
  ├─► M22 (Conversation UI + 一键对话)
  │     └─► M23 (视觉 + head-tracker)
  └─► M24 (动作库 + Workflow 节点)
        └─► M25 (Copilot + 文档 + 发布)
```

M21 是硬 prerequisite。M22/M24 可并行。M23 依赖 M22 框架。M25 收尾。

## 17. 立即可做

1. **当前正在做**：M21 落地（按本规划 §7）
2. 进度文档：`progress/M21-reachy-apps-audio.md`（M21 完成后写）
3. 时间紧可裁剪：M21 + M22 + M25 即可让用户用上「能说话的 Reachy」

---

## 附录 A — Allan daemon 启动命令现状

```json
"command": [
  "python", "-m", "reachy_mini.daemon.app.main",
  "--serialport", "{serial}",
  "--fastapi-host", "{host}",
  "--fastapi-port", "{port}",
  "--no-preload-datasets",
  "--autostart",
  "--deactivate-audio"   ← M21 删除
]
```

删除 `--deactivate-audio` 后，daemon 默认 `use_audio=True`，DOA 和 volume 端点可用，Conversation App 可调音频 SDK。

## 附录 B — 已知 Allan daemon 路由总览

```
/api/apps/*                  (11 + 1 WS)
/api/daemon/*                (4)
/api/motors/*                (2)
/api/move/*                  (10 + 3 WS)
/api/state/*                 (5 + 1 WS)
/api/volume/*                (5)
/api/kinematics/*            (3)
/api/hf-auth/*               (M22 调研)
```

BotverseX M21 后将代理其中 apps/volume/doa/daemon 全部 + state 增强。
