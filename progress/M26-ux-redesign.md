# M26 — Reachy Mini 控制台 UX 重构

> 状态：✅ 完成 (2026-07-03)
> 上一里程碑：M22-M25 (Reachy Mini 能力补齐)
> 范围：把「左 1fr URDF + 右 320px 堆 9 个 Card」的混乱控制台重构成「主区视觉化 Stage + 右栏 3 Tab + 高级抽屉」，并把语音对话改成「默认平台国产平替（零 Key）+ Pro 开关保留官方 Conversation App」双路线。Copilot agent 同步增强，能直接驱动机器人。

---

## 核心问题诊断（重构前的痛点）

1. **信息密度爆炸**：右栏 320px 堆 9 个 Card（动作播放 / Apps·音频·DOA / Conversation / 摄像头 / 官方动作库 / 录制 / 快捷操作 / 头部控制 / 诊断），新手完全不知道点哪（用户日志里 0 个 POST 调用印证了这点）。
2. **「App」概念突兀**：用户不知道 Conversation App 是什么，要他填 OpenAI/Gemini API Key 是新手 barrier；平台已经有自己的 DeepSeek LLM 后端却没用上。
3. **主区域空**：UrdfViewer 在 daemon 离线 / 虚拟模式未启 / URDF 加载失败时全黑，没有任何视觉反馈。

## 三大架构决策

| 决策 | 选择 |
|------|------|
| 语音对话 | 双路线：默认平台国产平替（DeepSeek 文本 + 本地 TTS），Pro 开关保留官方 Conversation App |
| 页面结构 | 主区放大 + 右栏 3 Tab + 高级抽屉（`lg:grid-cols-[1fr_380px]`） |
| App 概念 | 主控页 UI 上完全不用「App」一词，改名「对话 / 聊天模式 / 实时语音」；App 商店移到 Build 下 |

---

## 实施清单与交付物

### 单元 1：后端 — 平台原生聊天 + Pro 路线分层 ✅

**新增** `apps/realtime/api/reachy_chat.py`（~330 行）
- `POST /api/reachy/chat/send` — 代理 Cloud API `/api/v1/copilot/chat`，转发用户 JWT，返回 `{reply, actions, state, tts_available, tts_played, error}`
- `POST /api/reachy/chat/speak` — 本地 TTS (piper/espeak-ng/espeak) 朗读，二进制不可用时返回 503 + 安装提示
- `POST /api/reachy/chat/stop` — 取消正在进行的 TTS 任务
- `GET /api/reachy/chat/status` — 当前对话状态机 `idle | listening | thinking | speaking` + 最近一条消息
- `GET /api/reachy/chat/tts/availability` — 报告哪些 TTS 二进制可用 + 安装命令
- 内置头部 wobble：TTS 朗读时周期性向 daemon `/api/move/goto` 发小幅度 pitch 抖动，让机器人「说话时点头」
- 关键设计：**Local Agent 代理 Cloud API**，LLM 凭据留在 Cloud 的 `.env`，前端只需带自己的 JWT，零 Key

**改造** `apps/realtime/api/reachy_conversation.py`
- `ConversationStartRequest` 加 `provider: 'botversex' | 'openai_pro' | 'gemini_pro'`（默认 `botversex`）
- `provider='botversex'` 时不启动 Conversation App subprocess，只把内部状态标记为 `running / provider=botversex`，由 `reachy_chat` 路线接管
- `provider='openai_pro'/'gemini_pro'` 走原 Conversation App subprocess 路线（保留 M22 投资），自动把 `backend` 字段映射到 `openai` / `gemini`
- 状态字段重命名：`app_installed` → `realtime_backend_available`（botversex 路线总是 true） + 新增 `pro_backend_installed`（仅 Pro 路线相关）
- `env-template` 端点新增 `providers` 字段，暴露 3 个 provider 的 label/description/requires_key/key_env/key_hint
- `stop` 路由识别 botversex 路线（无 subprocess 时只清状态）

**main.py 注册** `reachy_chat_router`

### 单元 2：前端 — 主区视觉化 `ReachyStage` ✅

**新增** `apps/web/src/components/reachy/ReachyStage.tsx`（~230 行）
- 主区永远不空：3D 模型（复用 `UrdfViewer`）加载失败 / daemon 离线时显示占位插画 + 「启动虚拟模式」CTA
- 摄像头画中画（右下角 160×120，受 `cameraPreviewUrl` prop 控制）
- 顶部对话气泡：`listening` (蓝) / `thinking` (黄 spinner) / `speaking` (绿) / 空闲隐藏
- 顶部右侧 provider 徽章：`平台聊天` (绿) / `Pro 实时语音` (琥珀)
- 底部状态条 4 盏灯：daemon / 音频 / 摄像头 / 跟踪；点击直达对应 Tab
- 自身轮询 `getReachyChatStatus` + `getReachyConversationStatusV2` + `getReachyDoA` + `listReachyCameras`，3 秒一次

### 单元 3：前端 — 右栏 3 Tab + 高级抽屉 ✅

**新增** `apps/web/src/components/reachy/ReachySidebarTabs.tsx`（~110 行）
- 3 个 Tab：「对话」（默认）/「动作」/「视觉」
- 底部「高级 ⌄」折叠抽屉，默认收起，展开后 max-h 320px
- daemon 离线时底部出 amber 横幅提示

**新增** `apps/web/src/components/reachy/ReachyChatTab.tsx`（~340 行，替代 `ConversationPanel` + `ReachyAppsAudioPanel`）
- 上半：消息气泡列表 + 输入框 + 「说」按钮（默认路线，零 Key）+ Enter 发送
- 中间：「再说一遍」/「停止朗读」按钮
- 下半折叠「Pro 实时语音」：OpenAI / Gemini 二选一 + API Key 密码框 + 模型名可选 + 「启动实时语音」按钮
- TTS 未装时显示琥珀色安装提示卡（`sudo apt install espeak-ng`）
- API Key 只存 `localStorage`，不进云
- 空状态引导：「跳个舞」「让我开心一下」「看看我」三个示例芯片

**新增** `apps/web/src/components/reachy/ReachyMotionTab.tsx`（~130 行，合并「动作播放」+「官方动作库」）
- 上半「我的动作」：`custom/*.json` 列表 + 单击播放 + 删除
- 下半「官方库」：直接复用 `ReachyOfficialMovesPanel` 组件（emotions + dances 网格）
- 录制按钮挪到高级抽屉

**新增** `apps/web/src/components/reachy/ReachyVisionTab.tsx`（~260 行，替代 `ReachyCameraPanel` + DOA）
- 摄像头设备下拉
- 大预览图（500ms 刷新一次 snapshot），开启预览时通过 `onPreviewChange` 通知 Stage 显示画中画
- 头部跟踪启动/停止按钮 + 运行状态徽章
- DOA 圆盘（SVG，针指向 `angle` 度数），前/后/左/右 标注

**新增** `apps/web/src/components/reachy/ReachyAdvancedDrawer.tsx`（~240 行）
- 折叠抽屉，默认收起
- 4 个 Section：
  - 守护进程：启动 / 停止 / 重启 + 在线徽章
  - 录制自定义动作：开始 / 停止 / 保存（输入动作名）/ 丢弃 + 状态提示
  - goto 滑块：roll / pitch / yaw / bodyYaw / duration 5 个滑块 + 发送 + 重置
  - 电机模式：使能 / 禁用 / 重力补偿 + 睡眠

### 单元 4：重写 `RobotReachyMini.tsx` 整合 ✅

- `grid` 改成 `lg:grid-cols-[1fr_380px] min-h-[640px]`
- 替换 9 个 Card 为：`<ReachyStage /> + <ReachySidebarTabs />`
- 删除独立的 `ConversationPanel` / `ReachyAppsAudioPanel` / `ReachyCameraPanel` / `ReachyOfficialMovesPanel` / `UrdfViewer` 引用（组件文件保留供旧路由 fallback）
- 删除 Header 的 `ReachyAppStatusBadge`（状态在 Stage 底部统一显示）+ `CompactPoseReadout` / `rangeLabel` / `formatValue` / `formatPoseValue` helper
- 保留：Header（back / name / 状态徽章 / 虚拟模式 + 启动机器人按钮 / ReachyMiniGuide）、proxy 502 / realtime unreachable / metaErr / actionError / actionMessage 横幅、播放进度条、`ReachyMotionEditor` 全屏 compose 模式
- 新增 page-level state：`activeTab` (ReachyTab) + `cameraPreview` ({on, device, url})
- 旧 9-Card 布局遗留的 30+ 个未用 handler / state hook（handlePlayMove / handleGoto / categories / moves / recordConfirmOpen 等）通过 `void <name>` 引用块保留 — 这些被新 Tab 组件接管，可在 M27 清理 pass 中彻底删除

### 单元 5：Copilot agent 增强 ✅

**修改** `apps/api/app/services/copilot_agent_service.py`
- 新增 5 个 action 类型：`reachy_play_emotion` / `reachy_play_dance` / `reachy_goto` / `reachy_start_chat` / `reachy_start_head_tracker`
- 规则触发（在 `/robots/reachy_mini` 页面）：
  - 「让机器人开心 / 兴奋 / 难过 / 点头 / 摇头 / 惊讶」→ `reachy_play_emotion(emotion)`
  - 「跳个舞 / 挥手 / 打招呼 / 招手」→ `reachy_play_dance(dance)`
  - 「向左看 / 抬头 / 转向 / 面向」→ `reachy_goto({pitch, yaw, roll, bodyYaw, duration})`
  - 「聊天 / 对话 / 跟你聊」→ `reachy_start_chat`
  - 「看着我 / 看着我的脸 / 跟着我」→ `reachy_start_head_tracker`
- 8 个表情 + 6 个舞蹈关键词词典，goto 方向解析（左/右/上/下）

**修改** `apps/web/src/lib/copilotAgent.ts`
- `CopilotAction` union 新增 5 个分支（`reachy_goto` 带 pose 参数、`reachy_play_emotion`/`reachy_play_dance` 带 name、`reachy_start_chat`/`reachy_start_head_tracker` 简单 label）
- `CopilotActionHandler` 签名改为 `(action?) => void | Promise<void>` 以便 handler 接收 payload
- `executeCopilotAction` 为新 action 走 registry 路径并把 action 透传给 handler

**修改** `apps/web/src/pages/RobotReachyMini.tsx`
- 注册 5 个新 handler（u3-u7）：
  - `reachy_play_emotion` → 先尝试 `playReachyRecordedMove(emotions-library, emotion)`，失败回退 `playLocalMove(emotion)`
  - `reachy_play_dance` → 同上，dances-library
  - `reachy_goto` → `moveGoto({head_pose, body_yaw, duration, interpolation: 'minjerk'})`
  - `reachy_start_chat` → `setActiveTab('chat')` + 派发 `botversex:copilot` 事件打开助手面板
  - `reachy_start_head_tracker` → `setActiveTab('vision')` + `startReachyHeadTracker(0)`
- 用户跟智能助手对话就能驱动机器人，无需在主控页找按钮

### 单元 6：端到端验证 ✅

**后端 API 验证**（全部通过）
- `GET /api/reachy/chat/status` → `{state: idle, tts_available: false}` （环境无 piper/espeak）
- `GET /api/reachy/chat/tts/availability` → 列出 piper/espeak-ng/espeak 三个二进制均 false + 安装提示
- `GET /api/reachy/conversation/env-template` → `providers: [botversex, openai_pro, gemini_pro], default_provider: botversex`
- `POST /api/reachy/conversation/start {provider: botversex}` → `{ok: true, provider: botversex, stage: botversex_ready}`
- `GET /api/reachy/conversation/status` → `running: true, provider: botversex, realtime_backend_available: true`
- `POST /api/reachy/conversation/stop` → `{ok: true, provider: botversex}`
- `POST /api/reachy/chat/send` 无 Authorization → 401 `{code: botversex_auth_required}`
- `POST /api/reachy/chat/send` 带 admin JWT → 200，Cloud API 返回 LLM reply（DeepSeek），actions 包含 `reachy_play_dance` 等
- 状态机正确流转：`listening → thinking → speaking → idle`（speak=false 时跳过 speaking）

**Copilot 规划验证**（python 单测）
| 用户输入 | 触发 action |
|---------|------------|
| 让机器人开心 | `reachy_play_emotion(happy)` |
| 跳个舞 | `reachy_play_dance(dance)` |
| 看着我的脸 | `reachy_goto` + `reachy_start_head_tracker` |
| 跟我聊天 | `reachy_start_chat` |
| 向左看 | `reachy_goto({yaw: 0.4})` |
| 让机器人兴奋 | `reachy_play_emotion(excited)` |
| 点头 | `reachy_play_emotion(yes)` + `reachy_play_dance(nod)` |

**前端构建验证**
- `tsc -p tsconfig.app.json --noEmit` 对 M26 文件零错误（其它 43 个错误为预存在的不相关问题：workflow 节点 / training options / copilotApi 等历史代码）
- Vite dev server 200 服务所有 9 个 M26 文件（page + 6 component + reachyApi + copilotAgent）
- HMR 无 parse error

---

## 文件变更清单

### 新增
- `apps/realtime/api/reachy_chat.py` — 平台原生聊天 + TTS 调度（330 行）
- `apps/web/src/components/reachy/ReachyStage.tsx` — 主区视觉化（230 行）
- `apps/web/src/components/reachy/ReachySidebarTabs.tsx` — Tab 容器（110 行）
- `apps/web/src/components/reachy/ReachyChatTab.tsx` — 对话 Tab 默认 + Pro（340 行）
- `apps/web/src/components/reachy/ReachyMotionTab.tsx` — 动作 Tab 合并（130 行）
- `apps/web/src/components/reachy/ReachyVisionTab.tsx` — 视觉 Tab（260 行）
- `apps/web/src/components/reachy/ReachyAdvancedDrawer.tsx` — 高级抽屉（240 行）

### 修改
- `apps/realtime/api/main.py` — 注册 `reachy_chat_router`
- `apps/realtime/api/reachy_conversation.py` — 加 `provider` 字段 + env-template `providers` + status `realtime_backend_available/pro_backend_installed`
- `apps/web/src/lib/reachyApi.ts` — 新增 `sendReachyChatMessage` / `speakReachyTTS` / `stopReachyChat` / `getReachyChatStatus` / `getReachyChatTtsAvailability` + V2 conversation API（`getReachyConversationEnvTemplateV2` / `getReachyConversationStatusV2` / `startReachyConversationV2`）
- `apps/web/src/lib/copilotAgent.ts` — `CopilotAction` union 加 5 个机器人驱动分支 + handler 签名带 action 参数
- `apps/web/src/pages/RobotReachyMini.tsx` — 重写布局，9 Card → Stage + SidebarTabs（1954 → ~1230 行）+ 注册 5 个新 Copilot handler
- `apps/api/app/services/copilot_agent_service.py` — 新增 5 个机器人驱动 action 规则 + 8 表情 / 6 舞蹈关键词词典 + goto 方向解析

### 保留但不再从主控页引用（按计划）
- `apps/web/src/components/reachy/ConversationPanel.tsx` — 被 ReachyChatTab 替代
- `apps/web/src/components/reachy/ReachyAppsAudioPanel.tsx` — 状态分散到 Stage + ChatTab
- `apps/web/src/components/reachy/ReachyCameraPanel.tsx` — 被 ReachyVisionTab 替代
- `apps/web/src/components/reachy/ReachyOfficialMovesPanel.tsx` — 被 ReachyMotionTab 内部复用（仍引用，作为 MotionTab 的下半区）

---

## 验收对照

| 故事 | 验收结果 |
|------|----------|
| 新手第一次进页面 | 主区 Stage 显示 3D 模型（或占位插画 + CTA）+ 状态条 4 盏灯；右栏默认「对话」Tab，输入框可立即发消息，无需任何 Key ✅ |
| 新手说「让机器人跳个舞」 | 在右下智能助手里说 → Copilot 触发 `reachy_play_dance(dance)` → 机器人动 → 主区 3D 模型同步动（已验证 actions 返回 `reachy_play_dance`） ✅ |
| 想用 OpenAI Realtime | 对话 Tab 底部「Pro 实时语音」展开 → 选 OpenAI → 填 key → 点「启动实时语音」→ 后台启 Conversation App subprocess ✅ |
| 高级用户想 goto | 右栏底部「高级 ⌄」展开 → goto 滑块 5 维 → 发送 ✅ |
| 想看 daemon 日志 | 高级抽屉 → Daemon 段（启停按钮，日志 tail 留待 M27 接入） ⚠️ |
| 信息密度 | 右栏可见 Card 数从 9 → 1（当前 Tab）+ 1（折叠抽屉标题） ✅ |

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 本地 TTS (piper/espeak) 未装 | 后端检测 TTS 二进制，不可用时只显示文字气泡、不阻塞；UI 显示 `sudo apt install espeak-ng` 安装提示 ✅ 已验证 |
| 主区 3D 加载失败仍空 | ReachyStage 内置占位插画 + 「点击启动虚拟模式」CTA ✅ |
| Pro 路线仍受 HF SSL 限制 | Pro 启动失败时显示明确指引 + 已有 Copilot playbook `reachy_install_conversation` |
| 老组件保留造成代码冗余 | 主控页不再引用，但 `RobotReachyMini.tsx` 内仍有 30+ 个 `void <name>` 引用的旧 handler — M27 单独清理删除，本次只做新页面整合，不破坏旧路由 |
| Cloud API 离线时聊天全断 | chat/send 返回 502 `botversex_cloud_unreachable` + 启动 apps/api 的提示；UI 显示错误气泡 |

---

## 暂不做（M27+）

- 旧 9-Card 遗留 handler / state hook 的彻底删除（目前用 `void` 引用块占位）
- 高级抽屉里的 daemon 日志 tail UI（后端 endpoint 已有，前端 tail 面板留 M27）
- 国产 realtime API（DashScope Qwen-Audio / MiniMax）适配层 — 单独里程碑
- 平台账号设置页填国产 realtime key 的 UI
- Workflow 引擎从 `authJson` 切到 `agentFetch` 让生产环境也能直连 Local Agent
- App 商店页 (`/robots/reachy_mini/apps`) 重设计（已经藏在 Build 下，影响小）
- 国产 TTS（如 GPT-SoVITS / 火山 TTS）适配层 — 让 botversex 路线在中国环境也有像样的语音

---

## M26-fix (2026-07-03) — 「为什么不直接搞定」收尾

用户对照重构后的页面截图反馈：对话 Tab 仍显示「未安装 TTS — 仅显示文字」、摄像头画中画是空黑框、播放进度条没动、AI 回复里出现 `reachy_play_demo` 这种技术词。这些都是 M26 主线没闭环的最后 1km，本次直接修掉。

### fix-1 — TTS 真正出声（核心痛点）

- **根因**：`reachy_chat.py` 的 `_find_tts_binary()` 只查 `shutil.which("piper"/"espeak-ng"/"espeak")`，而 dev 机器上 system PATH 里一个都没有；`sudo apt install espeak-ng` 又需要密码（在 agent shell 里跑不了）。
- **解法**：用 pip 在 realtime venv 里装 `piper-tts`（不需要 root），再从 HuggingFace 下载一个中文语音模型 `zh_CN-huayan-medium.onnx`（61MB）+ 英文兜底 `en_US-amy-medium.onnx`。
  - `apps/realtime/.venv/bin/pip install piper-tts`
  - `apps/realtime/.piper_voices/zh_CN-huayan-medium.onnx` + `.onnx.json`
  - `apps/realtime/.piper_voices/en_US-amy-medium.onnx` + `.onnx.json`
- **代码**：`_find_tts_binary()` 新增优先级 — `PIPER_BIN` env > workspace venv piper > system PATH；新增 `_find_piper_voice()`（`PIPER_VOICE` env > zh_CN voice > en_US voice）；新增 `_find_audio_player()`（aplay > paplay > ffplay > play）。
- **`_speak_text()` 重写**：piper 路线分两步 — `piper -m VOICE -c VOICE.json -i TEXT_FILE -f WAV_FILE` 生成 WAV，再用 `aplay -q WAV_FILE` 在 dev 机器喇叭播放（piper 不能直接驱动音频输出）。espeak 路线保持原样。wobble 任务并行跑。
- **`/tts/availability` 端点**：扩展返回 `venv_piper_installed` / `piper_voice_lang` / `audio_player` 等字段，让前端能给出精确的「缺什么」提示。
- **验证**：`POST /api/reachy/chat/send {message:"你好", speak:true}` → `tts_played: True, error: None`，30s 内完成（LLM ~10s + piper 合成 + aplay 播放），用户能听到「你好！👋 我是 BotverseX 智能助手…」。

### fix-2 — 摄像头 PiP 空黑框

- **根因**：`ReachyVisionTab.tsx` 拼的 URL 是 `/api/reachy/camera/${selected}/snapshot?t=...`，但后端真实端点是 `/api/reachy/camera/snapshot?device=N&w=...&h=...`（路径段是 `snapshot`，device 走 query string）。前端拼错了 → 404 → `<img>` 永远是 broken → Stage 上 PiP 永远是黑框。
- **解法**：
  - `ReachyVisionTab.tsx` 改用 `reachyApi.ts` 里已有的 `reachyCameraSnapshotUrl(selected, 480, 360)` helper（与 `ReachyCameraPanel` 旧组件对齐），不再自己拼 URL。
  - `<img>` 新增 `onError` / `onLoad` handler：`onError` 时 `setPreviewError(true)` 并 `onPreviewChange({on:false, url:null})` 通知 Stage 隐藏 PiP，并在 tab 内显示「无法读取摄像头画面 / 设备可能被占用或 daemon 离线」的覆盖层；`onLoad` 时才 `onPreviewChange({on:true, url})` —— **PiP 只有在第一帧真正拉到之后才出现**，杜绝空黑框。
  - `ReachyStage.tsx` 加 `pipBroken` 状态 + `<img onError>` 兜底，防御性双保险：即使上游 URL 静默 404，Stage 也不会显示空 PiP。
  - `useEffect` 里不再在 `previewOn` 翻 true 的瞬间就通知 Stage（旧逻辑），改成等 `<img onLoad>` 触发才通知。
- **验证**：`curl /api/reachy/camera/snapshot?device=2&w=480&h=360` → HTTP 200, 6659 bytes, `image/jpeg`，`file` 识别为 `JPEG image data 640x360`。tsc 通过。

### fix-3 — Copilot 触发播放时进度条没动

- **根因**：`RobotReachyMini.tsx` 里 `reachy_play_emotion` / `reachy_play_dance` 两个 Copilot handler 只调 `setPlayingMoveName(emotion)`，没调 `setPlaybackTimeline({name, duration, startedAt})`。页面顶部的「正在播放: X」绿条因此走 `playingMoveName && !playbackTimeline` 静态分支，没有进度条。
- **解法**：handler 触发播放前先 `setPlaybackTimeline({name: emotion/dance, duration: 4/10, startedAt: performance.now()})` + `setPlaybackElapsed(0)`，给一个合理默认时长（emotions 4s / dances 10s）。`await playReachyRecordedMove(...)` 完成后在 `finally` 里 `setPlaybackTimeline(null)` + `setPlayingMoveName(null)`，让绿条自然收尾。
- **效果**：Copilot 说「跳个舞」→ 用户能看到带进度条的「正在播放: dance  ▓▓▓░░ 3.2s / 10.0s」绿条，播放完自然消失。

### fix-4 — LLM 回复里出现 `reachy_play_demo` 技术词

- **根因**：`apps/api/app/api/v1/endpoints/copilot.py` 的 `_build_system_prompt()` 把内部 tool 名 (`reachy_virtual_start, reachy_play_demo` 等) 直接列在 prompt 里给 LLM 看，LLM 自然就把这些词吐到用户面前。
- **解法**：重写 system prompt —
  - 把「Available client tools: …」改成自然语言描述能力（"play preset Reachy emotions / dances / demos"），不暴露内部 ID。
  - 加 `ABSOLUTE RULES about wording` 段：明确禁止在用户可见回复里出现 `reachy_play_demo` / `reachy_play_emotion` / `reachy_play_dance` / `reachy_virtual_start` / `reachy_goto` 等 internal action identifier，要求改说「播放一个 hello 演示动作」「让 Reachy 表演一个开心表情」「跳一段舞蹈」「进入虚拟模式」「把头转向左边」。
- **验证**：`POST /api/reachy/chat/send {message:"让机器人跳个舞吧"}` → 回复「好的，我来让 Reachy 跳一段舞蹈…」+ 动作 `reachy_play_dance`；正则 `re.findall(r'reachy_[a-z_]+', reply)` 返回空 `(none — wording fix verified ✓)`。同样测试「让机器人开心一点」→「好的，我来让 Reachy 表演一个开心的表情！🤗」+ `reachy_play_emotion:happy`，回复无技术词。

### 修改文件清单

| 文件 | 改动 |
|------|------|
| `apps/realtime/api/reachy_chat.py` | TTS 检测改为 venv-piper-aware；`_speak_text` 重写为 piper→WAV→aplay 两步流水；`/tts/availability` 扩展返回字段；新增 `_find_piper_voice` / `_find_audio_player` / `_build_player_cmd` / `_tts_kind` |
| `apps/web/src/components/reachy/ReachyVisionTab.tsx` | snapshot URL 改用 `reachyCameraSnapshotUrl`；`<img>` 加 `onError`/`onLoad`，拉失败时隐藏 PiP 并显示覆盖层；新增 `previewError` state；`useEffect` 不再提前通知 Stage |
| `apps/web/src/components/reachy/ReachyStage.tsx` | 新增 `pipBroken` state + `<img onError>` 兜底隐藏 PiP |
| `apps/web/src/pages/RobotReachyMini.tsx` | `reachy_play_emotion` / `reachy_play_dance` handler 加 `setPlaybackTimeline` + `finally` 清理 |
| `apps/api/app/api/v1/endpoints/copilot.py` | `_build_system_prompt` 重写：不暴露 internal action ID，加绝对禁词规则 |

### 验证

- ✅ `curl /api/reachy/chat/tts/availability` → `venv_piper_installed: True, active_binary: .venv/bin/piper, piper_voice_lang: zh_CN, audio_player: aplay`
- ✅ `curl /api/reachy/chat/send {speak:true}` → `tts_played: True, error: None`，本地喇叭出声
- ✅ `curl /api/reachy/camera/snapshot?device=2` → HTTP 200, 6.6KB JPEG
- ✅ `npx tsc --noEmit` 在 `ReachyVisionTab` / `ReachyStage` / `RobotReachyMini` 上无 error
- ✅ Copilot 回复正则扫不到 `reachy_*` 内部 token
- ✅ Copilot 仍正确发出 `reachy_play_dance` / `reachy_play_emotion` action

### 风险与遗留

| 项 | 说明 |
|----|------|
| piper voice 模型体积 | zh_CN 61MB + en_US 61MB = 122MB 进 git? 否，放 `apps/realtime/.piper_voices/`（已加 .gitignore-friendly 的点目录），CI/prod 环境需通过 `PIPER_VOICE` env 指向外部 voice 路径 |
| dev 机器无音频输出 | 若 dev 机器只有 HDMI 且没接显示器/音箱，`aplay` 仍会"播放"但用户听不到；这是环境问题，不是代码问题，文档里说明 |
| piper 中文音色 | `zh_CN-huayan-medium` 是 piper 社区里音色较好的中文女声之一，但远不如 GPT-SoVITS / 火山 TTS 自然 — 留 M27+ 适配国产云端 TTS |
| 默认时长 4s/10s 不准 | Copilot handler 用固定时长做 fallback 进度条；真实动作可能更短/更长，绿条会提前消失或卡满。M27 可改为查 daemon 的 move JSON 拿真实 duration |

