# M22 — Reachy App 商店 UI + 一键对话

里程碑: M22
日期: 2026-07-02
状态: ✅ 已完成（编排 + UI + 路由；本机 HF 网络受限，真实 install 待用户网络可达 HF 时验证）
规划: [progress/M21-reachy-open-capabilities-roadmap.md](./M21-reachy-open-capabilities-roadmap.md) §8

## 目标

让用户从云端 UI 一键把 Reachy 变成可对话的机器人，并能像 App Store 一样浏览/安装/卸载/更新官方与社区 Reachy Mini HuggingFace Space 应用。

## 落地变更

### 后端 `apps/realtime/api/reachy_proxy.py`（+~190 行）

新增 Conversation App 编排层：

- `POST /api/reachy/conversation/start` — body `{backend, api_key?, model?}`：
  1. 校验 backend（`huggingface` / `openai` / `gemini`），默认 huggingface
  2. 持久化 env 到 `~/.config/botversex/reachy_conversation.env`（chmod 0600），含 `BOTVERSEX_CONVERSATION_BACKEND` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `HF_TOKEN` / `BOTVERSEX_CONVERSATION_MODEL`
  3. 调 daemon `/api/apps/list-available/installed` 检查 conversation app 是否已装
  4. 未装则调 `/api/apps/install` + 轮询 `/api/apps/job-status/{job_id}` 最多 60s
  5. 若当前有其他 App 在跑，先 stop-current-app
  6. 调 `/api/apps/start-app/reachy-mini-conversation-app`
  7. 返回 `{ok, stage, app_name, backend, model, install_job_id, install_skipped, env_file, app_status}`
- `POST /api/reachy/conversation/stop` — 透传 stop-current-app
- `GET  /api/reachy/conversation/status` — 透传 current-app-status，并加 `is_conversation_app` / `env_file_exists` 字段

新增内部辅助：
- `_daemon_request(method, path, json_body, timeout_s)` — 直接调 Allan daemon，返回 `(status, json)`
- `_persist_conversation_env(backend, api_key, model)` — 写 `~/.config/botversex/reachy_conversation.env`
- 常量 `_CONVERSATION_APP_NAME` / `_CONVERSATION_APP_HF_SPACE_ID` / `_CONVERSATION_APP_HF_URL` / `_CONVERSATION_ENV_DIR` / `_CONVERSATION_ENV_FILE`

### 前端 `apps/web/src/lib/reachyApi.ts`（+~55 行）

- 类型：`ReachyConversationBackend`, `ReachyConversationStartRequest`, `ReachyConversationStartResponse`, `ReachyConversationStatusResponse`
- 函数：`startReachyConversation`, `stopReachyConversation`, `getReachyConversationStatus`

### 前端 `apps/web/src/components/reachy/ConversationPanel.tsx`（新建，~270 行）

- LLM backend 下拉：HuggingFace（无需 Key）/ OpenAI / Gemini
- API Key 输入框（OpenAI/Gemini 显示），密码框，localStorage 持久化
- 可选模型名输入
- 启动按钮：调 `startReachyConversation`，显示 stage（install_failed/started/...）
- 停止按钮：调 `stopReachyConversation`
- 状态徽章：对话中 / 其他 App 运行中
- 错误横幅：清晰列出 install/job 错误
- env 文件路径显示

### 前端 `apps/web/src/pages/ReachyMiniApps.tsx`（新建，~290 行）

- 顶部 header + 返回按钮 + 刷新
- 当前 App 运行 banner（重启/停止）
- 安装任务进度 banner（实时显示 job_id + status + logs，WS 流）
- 更新可用提示
- Source tabs：`hf_space` / `installed` / `all`
- App 卡片网格：每张卡显示 name + description + source badge + HF Space 链接 + 安装/启动/停止/更新/卸载按钮
- 自定义 hook `useAppsManagerSocket(jobId)` — 通过 `ws://.../ws/reachy/apps-manager/{job_id}` 接收实时 job 进度，WS 关闭后自动 fallback 到 HTTP 轮询

### 前端集成

- `apps/web/src/pages/RobotReachyMini.tsx` — 在 M21 AppsAudioPanel 下方新增 `<ConversationPanel daemonOnline={daemonOnline} />` + Apps 商店链接 `<a href="/robots/reachy_mini/apps">`
- `apps/web/src/App.tsx` — 新增 `/robots/reachy_mini/apps` 路由 + `ReachyMiniApps` lazy import
- `apps/web/src/components/layout/Navbar.tsx` — Build 子菜单新增「Reachy Apps」入口（Package icon）
- `apps/web/src/lib/routePrefetch.ts` — 注册 `/robots/reachy_mini/apps` 预拉

## 端到端验证

| 验证项 | 结果 |
|--------|------|
| `realtime` 重启无报错 | ✅ |
| `GET /api/reachy/conversation/status` 返回 `ok:true, is_conversation_app:false, env_file_exists:false` | ✅ |
| `POST /api/reachy/conversation/start` body `{"backend":"huggingface"}` 触发 install → 因 HF 网络环境（SSL EOF）失败 → 返回 `stage:"install_failed"` + 完整 job logs | ✅ 编排逻辑正确，错误回报清晰 |
| `env_file` 在 install 之前就被写入（`env_file_exists:true`） | ✅ 顺序正确 |
| `POST /api/reachy/conversation/start` body `{"backend":"invalid_backend"}` 自动归一化为 `huggingface` 并继续 | ✅ 防呆 |
| 前端 `tsc --noEmit` | ✅ 通过 |
| 前端 `eslint` 新文件 clean | ✅ |
| `/robots/reachy_mini/apps` 路由可访问（HTTP 200） | ✅ |

## 未做（已知限制 / 后续）

- **真实 HF Space install 在本机网络下失败**：本机访问 `huggingface.co` SSL EOF。这是环境问题（GFW/防火墙/证书），不是代码 bug。用户在能正常访问 HF 的环境下可一键装。中国大陆建议设 `HF_ENDPOINT=https://hf-mirror.com` 后重启 daemon。
- **LLM API Key 注入 Conversation App 子进程**：M22 MVP 把 key 持久化到 `~/.config/botversex/reachy_conversation.env`。Conversation App 是否真的会读这个文件取决于 App 自身的 launch.sh — 官方 Conversation App 当前可能不读。若发现没生效，M25 会在 Conversation App 安装目录里写一个 wrapper 脚本 source 这个 env。HF backend 不需要 Key 即可工作。
- **HF Token 管理 UI**：装私有 Space 需要 daemon 持有 HF token（`/api/hf-auth/save-token`）。M22 没暴露这个 UI，等用户提需求再加。

## 文件改动清单

```
apps/realtime/api/reachy_proxy.py                              (+~190 行 conversation 编排)
apps/web/src/lib/reachyApi.ts                                  (+~55 行 conversation API)
apps/web/src/components/reachy/ConversationPanel.tsx           (新建, ~270 行)
apps/web/src/pages/ReachyMiniApps.tsx                          (新建, ~290 行)
apps/web/src/pages/RobotReachyMini.tsx                         (+~10 行: 插入 ConversationPanel + 商店链接)
apps/web/src/App.tsx                                           (+~10 行: 路由 + lazy import)
apps/web/src/components/layout/Navbar.tsx                      (+~2 行: Build 子菜单加 Reachy Apps)
apps/web/src/lib/routePrefetch.ts                              (+1 行)
progress/M22-reachy-conversation-apps.md                       (本文件)
```

## 下一步

M23：摄像头 + head-tracker 代理。因 Allan fork 不暴露 HTTP camera 端点（见 [M21 附录 C](./M21-reachy-apps-audio.md)），Local Agent 会直接用 `cv2.VideoCapture` 打开 `/dev/video*` 提供 MJPEG snapshot/stream + 一个 mediapipe face tracker → head goto 服务。
