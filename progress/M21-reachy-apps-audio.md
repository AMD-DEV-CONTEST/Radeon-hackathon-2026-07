# M21 — Reachy Mini 音频解禁 + Apps/Volume/DoA/Daemon 代理 + 串口标签化

里程碑: M21
日期: 2026-07-02
状态: ✅ 已完成
规划文档: [progress/M21-reachy-open-capabilities-roadmap.md](./M21-reachy-open-capabilities-roadmap.md)

## 目标

把 Reachy Mini 官方 Allan daemon 的「App 生态 / 音频 / 声源定位 / daemon 生命周期」全部接入 BotverseX Local Agent，让用户从云端 UI 即可一键装官方 App、调音量、看声源方向、重启 daemon；并解决与 SO-101 的串口冲突识别问题。这是 M22（一键对话）/ M23（视觉）/ M24（动作库 + Workflow）的前置基础。

## 实测发现（可抄清单）

读 Allan SDK 源码（`/home/amd/sdk/reachy_mini_Allan/src/reachy_mini/daemon/app/routers/`）确认 daemon `:8010` 暴露的 HTTP API 全集：

| 路由组 | 端点数 | 关键 |
|--------|--------|------|
| `/api/apps/*` | 12 + 1 WS | HF App 安装/启动/卸载/更新/job-status |
| `/api/daemon/*` | 4 | start/stop/restart/status |
| `/api/motors/*` | 2 | status + set_mode (含 gravity_compensation) |
| `/api/move/*` | 10 + 3 WS | goto/wake_up/sleep/recorded-move-dataset/local-moves/set_target/raw write |
| `/api/state/*` | 5 + 1 WS | head_pose/body_yaw/antennas/doa/full |
| `/api/volume/*` | 5 | speaker + mic + test-sound |
| `/api/kinematics/*` | 3 | info + urdf + stl |

**关键修正：** daemon 不暴露 record/play_audio/tts HTTP 端点。录音/TTS 由 Conversation App 在 subprocess 内通过 SDK 调。所以「让 Reachy 能说话」=「装 Conversation App」，不是「BotverseX 加 TTS 路由」。

## 落地变更

### 配置 `apps/realtime/config/robots.json`
- ✅ 删除 daemon command 中的 `--deactivate-audio`（默认 `use_audio=True`，启用音频）
- ✅ 新增 `service.audio` 配置块（`enabled: true, can_disable: true`）
- ✅ 新增 `service.apps` 配置块（`enabled: true, default_conversation_app: reachy_mini_conversation_app, default_backend: huggingface, backends: [huggingface, openai, gemini]`）
- ✅ `capabilities` 新增 7 个字段：`audio, doa, volume_control, apps, conversation, recorded_move_datasets, set_target_stream`

### 后端 `apps/realtime/api/reachy_proxy.py`（+~270 行）
- ✅ **Apps 代理（12 个 HTTP + 1 WS）**：
  - `GET  /api/reachy/apps/list-available` 与 `/{source_kind}`
  - `POST /api/reachy/apps/install` / `install-private-space` / `remove/{name}` / `start-app/{name}` / `restart-current-app` / `stop-current-app` / `update/{name}`
  - `GET  /api/reachy/apps/current-app-status` / `job-status/{job_id}` / `check-updates`
  - `WS   /ws/reachy/apps-manager/{job_id}`（流式安装进度）
- ✅ **Volume 代理（5 个）**：`/api/reachy/volume/{current,set,test-sound,microphone/current,microphone/set}`
- ✅ **DoA 代理**：`GET /api/reachy/state/doa`（声源方向，免装 App 即可读）
- ✅ **Daemon 生命周期代理（4 个）**：`/api/reachy/daemon/{start,stop,restart,status}`
- ✅ **Audio 自动降级**：daemon 启动失败且日志含 `gi' module is required for GStreamerAudio` 时，自动 retry 一次带 `--deactivate-audio`，并在响应里返回 `audio_fallback_used: true` + `audio_warning: "..."`。**实测生效**：本机 GStreamer 缺失，自动降级后 daemon 正常运行，volume/daemon status/apps 全部可用，仅 DOA 返回 null。
- ✅ 新增 `_daemon_log_shows_audio_error()` 日志诊断函数

### 串口标签化 `apps/realtime/api/setup.py`
- ✅ `PortInfo` 新增 `looks_like_reachy: bool` 与 `robot_guess: Literal['so101', 'reachy_mini', 'unknown']`
- ✅ `list_ports` 在 Feetech 探测落空 + Allan SDK 安装的前提下，对每个 port 跑 `_ping_reachy_motor_on_port(port)`（Dynamixel motor id=10 探测）
- ✅ Setup UI 现在能显示「Feetech Motor Controller (SO-101 / STS3215)」或「Reachy Mini (Dynamixel body_rotation id=10)」，用户一眼能看清哪台机器人占哪个 ttyACM

### 前端 `apps/web/src/lib/reachyApi.ts`（+~180 行）
- ✅ 类型：`ReachyApp, ReachyAppStatus, ReachyJobInfo, ReachyAppUpdateStatus, ReachyAppUpdatesResponse, ReachyVolumeResponse, ReachyTestSoundResponse, ReachyDoAInfo, ReachyDaemonState, ReachyLocalDaemonStartResponse`
- ✅ 函数：`listReachyApps / listReachyAppsBySource / installReachyApp / installPrivateReachySpace / removeReachyApp / startReachyApp / restartCurrentReachyApp / stopCurrentReachyApp / getCurrentReachyAppStatus / getReachyJobStatus / checkReachyAppUpdates / updateReachyApp`
- ✅ 函数：`getReachySpeakerVolume / setReachySpeakerVolume / playReachyTestSound / getReachyMicVolume / setReachyMicVolume`
- ✅ 函数：`getReachyDoA`
- ✅ 函数：`startReachyDaemon / stopReachyDaemon / restartReachyDaemon / getReachyDaemonState`

### 前端组件 `apps/web/src/components/reachy/ReachyAppsAudioPanel.tsx`（新文件，~330 行）
- ✅ 当前 App 名 + 运行中徽章 + Stop/Restart 按钮（5s 轮询）
- ✅ 扬声器音量滑块（0-100，onChange 直接 POST `/volume/set`）
- ✅ 麦克风电平滑块 + 测试音按钮
- ✅ DOA 声源方向显示（角度 + 方向标签 + 说话检测指示灯）
- ✅ Daemon 生命周期：Start / Stop / Restart 三按钮
- ✅ 守护进程未连接时显示友好占位
- ✅ Lint 通过：`react-hooks/set-state-in-effect` 用 `setTimeout` 延迟首次 refresh 解决

### 前端 `apps/web/src/pages/RobotReachyMini.tsx`
- ✅ 顶部新增 `ReachyAppStatusBadge` 内联组件（5s 轮询当前 App，运行中显示「App: xxx」蓝色徽章）
- ✅ 右栏 controls 区在「动作播放」卡片下方插入 `<ReachyAppsAudioPanel daemonOnline={daemonOnline} />`

## 端到端验证

| 验证项 | 结果 |
|--------|------|
| `apps/realtime` 服务重启无报错 | ✅ |
| `/api/setup/health` 仍正常（realtime_ok=true, serial_device_count=1） | ✅ |
| `/api/runtimes` 仍包含 reachy_mini + so101 | ✅ |
| `/api/robots` reachy_mini capabilities 含 audio/apps/conversation/doa/volume_control/... | ✅ |
| `/api/setup/ports` 返回 `looks_like_reachy` 和 `robot_guess` 字段 | ✅ |
| `POST /api/reachy/local-daemon/start` 触发 audio 自动降级（GStreamer 缺失场景） | ✅ `audio_fallback_used: true` |
| daemon 起来后 `GET /api/reachy/daemon/status` 返回 `state: "running"` | ✅ |
| `GET /api/reachy/apps/list-available` 返回 `[]`（无 App 安装，符合预期） | ✅ |
| `GET /api/reachy/apps/current-app-status` 返回 `null` | ✅ |
| `GET /api/reachy/volume/current` 返回 `{volume: 79, platform: "Linux", device: "Reachy Mini Audio..."}` | ✅（volume_control_linux 用 amixer/pactl，与 GStreamer 解耦） |
| `GET /api/reachy/state/doa` 在 audio 降级时返回 `null` | ✅（符合预期，装 GStreamer 后会有值） |
| `/api/teleop/status` SO-101 路由仍正常 | ✅ 未受影响 |
| 前端 `tsc --noEmit` 类型检查 | ✅ 通过 |
| 前端 `eslint` 新文件无 error | ✅ ReachyAppsAudioPanel.tsx / reachyApi.ts clean |
| `RobotReachyMini.tsx` 已有 lint 错误（daemonReady 未使用、connect 提前访问）属于历史技术债，非 M21 引入 | ⚠️ 留待后续单独修 |

## 未做（留待 M22-M25）

- 装 Conversation App 的 UI 商店页面（M22）
- 实时对话面板 ConversationPanel + 后端启动 App 时注入 LLM API Key（M22）
- 摄像头/head-tracker 代理（M23）
- 官方 HF 动作库 + Workflow 节点 + Reachy 数据集训练管线（M24）
- Copilot 诊断 + 文档 + 部署脚本同步（M25）
- 自动分配 ttyACM 给 SO-101 vs Reachy（当前仅显示标签，不自动改 port；M21 优先级低，等用户反馈再决定是否自动）

## 文件改动清单

```
apps/realtime/config/robots.json                              (改)
apps/realtime/api/reachy_proxy.py                             (+~270 行)
apps/realtime/api/setup.py                                    (+~45 行)
apps/web/src/lib/reachyApi.ts                                 (+~180 行)
apps/web/src/components/reachy/ReachyAppsAudioPanel.tsx       (新建, ~330 行)
apps/web/src/pages/RobotReachyMini.tsx                        (+~30 行)
progress/M21-reachy-open-capabilities-roadmap.md              (新建, 规划)
progress/M21-reachy-apps-audio.md                             (本文件)
```

## 下一步

启动 M22：Reachy App 商店 UI + 一键对话（ConversationPanel）。

## 附录 C — Allan fork vs 官方 pollen-robotics/reachy_mini 兼容矩阵

由 explore agent 完整源码调研补充（[Reachy Mini daemon REST API 调研](2a47a9e8-8848-4c1b-bfff-8a4069687cc3)）：

**Allan fork 独有（BotverseX 已用 / 可继续用）：**
- `/api/move/local-categories` + `/api/move/local-moves/list/{category}` + `/api/move/play/local-move/{name}` — 本地 JSON 动作库，BotverseX 已代理
- CORS `allow_origins=["*"]`（比官方宽松，对开发友好）

**官方有、Allan fork 没有（M22-M25 注意）：**

| 路由 | 影响 | 决策 |
|------|------|------|
| `/api/camera/specs` | M23 摄像头内参 | Allan fork 走 WebRTC/Unix socket `/tmp/reachymini_camera_socket`；M23 用 Local Agent `cv2.VideoCapture` 直开 `/dev/video*` 而非依赖 daemon |
| `/api/media/{acquire,release,status,play_sound,stop_sound,clear_incoming_audio,wobbling/enable,wobbling/disable,sounds/*}` | M22 Conversation App bar 边、M23 摄像头让出 | M22 不依赖 daemon media 端点；Conversation App subprocess 内部直接调 SDK MediaManager |
| `/api/audio/config/*` | XVF3800 音频板参数 | 不做（硬件相关，BotverseX 用户少） |
| `WS /ws/sdk` | SDK WebSocket | 不做（已有 Zenoh + HTTP） |
| `--startup-app <name>` CLI | M22 一键启动 Conversation App | Allan fork 没有此 CLI → M22 在 BotverseX Local Agent 层用 `start-app` API 达成同样效果 |
| `--no-media` CLI（关 camera+audio+WebRTC） | M21 已用 `--deactivate-audio` | Allan fork 仅支持 `--deactivate-audio`，足够 M21 |

**结论：** Allan fork 的 apps/volume/state.doa/daemon/motors/move 全部可代理（M21 已完成）。M22 Conversation App 走 SDK subprocess 即可，**不依赖** Allan fork 缺失的 media 端点。M23 摄像头需要 Local Agent 自起 `cv2.VideoCapture`，**不依赖** daemon。规划保持不变。

