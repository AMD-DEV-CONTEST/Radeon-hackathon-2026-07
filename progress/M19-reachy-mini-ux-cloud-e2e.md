# M19 — Reachy Mini 控制台、Local Agent 云端路由与生产 E2E

日期: 2026-05-17

## 完成了什么

在 M18 生产同步基础上，完成 **Reachy Mini 专用控制页** 的大改、**Realtime 侧 Reachy 代理 API**、**云端 UI + 本机 Local Agent 控真机** 的路由修复，并将变更 **rsync 到 ECS**、重建 `web` / `realtime` 容器，跑通云端与本机端到端 smoke。

产品形态：用户打开 `http://botversex.feispace.me/robots/reachy_mini` 加载云端静态资源；硬件相关 HTTP/WS 走本机 `http://localhost:8002`（与 Setup/Teleop 一致）。

## 当前总体状态

### 前端（`apps/web`）

| 文件 | 变更要点 |
|------|----------|
| `src/pages/RobotReachyMini.tsx` | 左 URDF 大视口 + 姿态叠加；右动作/快捷/头部控制；可折叠「守护进程与诊断」；daemon 在线后自动连 10 Hz WS；去掉 UUID；播放中显示动作名；冷启动约 3s 显示未连接 |
| `src/lib/reachyApi.ts` | 新建；全部 Reachy REST 经 `agentFetch` |
| `src/lib/robotApi.ts` | 新建；机器人服务启停等经 `agentFetch` |
| `src/lib/localAgent.ts` | 已有；生产 host 非 localhost 时 API/WS 指向 `:8002` |
| `src/lib/urdf.ts` | `body_rotation` → `yaw_body`；Stewart 关节不写预览；`URDF_BODY_JOINT_DEADBAND_RAD = 0.004` 减抖动 |
| `vite.config.ts` | dev 代理 `/api/reachy`、`/api/robots` |

**UX 约束（已知限制）：**

- **重力补偿**按钮禁用：daemon 默认 `AnalyticalKinematics`，无 Placo 时 SDK 返回 500。
- **3D 预览**不映射 `stewart_*`，避免低头假象。

### Realtime（`apps/realtime`）

| 文件 | 变更要点 |
|------|----------|
| `api/reachy_proxy.py` | 新建；`/api/reachy/*` HTTP 代理 + `/ws/robots/reachy_mini/state` → daemon `ws://127.0.0.1:8010/api/state/ws/full` |
| `api/robots.py` | 新建；`/api/robots/reachy_mini/service/start|stop` 等 |
| `api/robot_config.py` | 读取 `config/robots.json` |
| `config/robots.json` | SDK 路径、`daemon_port` 8010、串口等 |
| `data/reachy_mini_moves/` | dances（hello/nod/shake/wiggle）、emotions（calm/excited/happy/sad） |
| `api/main.py` | CORS 含 `http://botversex.feispace.me` |

### 部署（`infra/docker` + `scripts`）

- `nginx.conf`、`docker-compose.prod.yml`、`web.prod.Dockerfile`、`realtime.Dockerfile`
- `scripts/deploy.sh` — ECS 构建/启停约定（Podman 需 `stop/rm` 旧 web 容器）

### 生产（ECS `47.113.126.51:/opt/botversex`）

- 定向 rsync（排除 `node_modules`、`.venv`、`.git`、`.tmp`）；**勿**全库 rsync（曾误扫 `.pnpm-store`）。
- 重建：`botversex-web`、`botversex-realtime`；`botversex-api` 保持运行。
- 线上 bundle：**`index-D85pS6YT.js`**（替代 M18 记录的 `index-JLvHS0yE.js`）。
- 云端 `/api/reachy/ping` → `ok: false`（无 USB，预期）。

## 解决了什么问题

1. **云端打开 Reachy 页无法控制真机**
   - 原 `fetch('/api/reachy/...')` 与 `ws://{host}/ws/...` 打到云端 realtime（无机器人）。
   - 改为 `agentFetch` / `agentWsUrl`，生产页走本机 `:8002`。

2. **状态流失败 `reachy_state_stream_failed`**
   - 根因多为 daemon 电机读失败 → HTTP 503，非路由错误。
   - 恢复：`POST .../service/stop` 再 `service/start`；日志 `/tmp/botversex_reachy_mini_daemon.log`。

3. **重力补偿 Internal Server Error**
   - Placo 未启用时 SDK `set_motor_control_mode(GravityCompensation)` 抛错。
   - UI 固定禁用并 tooltip 说明。

4. **URDF 身体/头部抖动**
   - `body_rotation` 编码器噪声 → `yaw_body` 4 mrad 死区；预览跳过 Stewart 关节。

5. **生产 web 镜像未更新**
   - Podman 同名容器可能继续跑旧 bundle；更新需 `stop/rm botversex-web` 后 `up -d --build web`。

## 架构（云端 UI + 本机 Agent）

```text
浏览器 @ botversex.feispace.me
  ├─ 静态 UI、URDF 文件     → 云端 nginx → web / realtime
  └─ /api/reachy/*、/ws/... → localhost:8002 (Local Agent)
                                    → daemon :8010 → USB Reachy Mini
```

## 关键命令 / 配置

### 本机开发

```bash
# Realtime Local Agent
cd /path/to/botversex
bash scripts/dev-up.sh up          # :8002

# Reachy daemon（SDK 环境）
# robots.json: sdk_path, serial, daemon_port 8010
```

### 同步到 ECS（推荐定向 rsync）

```bash
RSYNC_RSH='ssh -i ~/.ssh/id_ed25519_ecs -o StrictHostKeyChecking=no'
rsync -avz -e "$RSYNC_RSH" \
  --exclude node_modules --exclude .venv --exclude .git --exclude .tmp \
  apps/web/src/ apps/realtime/api/ apps/realtime/config/ \
  apps/realtime/data/reachy_mini_moves/ infra/docker/ scripts/deploy.sh \
  root@47.113.126.51:/opt/botversex/

ssh -i ~/.ssh/id_ed25519_ecs root@47.113.126.51 'cd /opt/botversex && \
  docker compose -f infra/docker/docker-compose.prod.yml stop web realtime 2>/dev/null; \
  docker rm -f botversex-web botversex-realtime 2>/dev/null; \
  docker compose -f infra/docker/docker-compose.prod.yml up -d --build web realtime'
```

### 云端 smoke（无机器人）

```bash
for u in / /robots /robots/reachy_mini /skills /training /login; do
  curl -s -o /dev/null -w "$u %{http_code}\n" "http://botversex.feispace.me$u"
done
curl -s -o /dev/null -w "urdf %{http_code}\n" \
  "http://botversex.feispace.me/api/urdf/reachy_mini/reachy_mini.urdf"
curl -s "http://botversex.feispace.me/api/robots" | grep -q reachy_mini && echo robots OK
curl -s "http://botversex.feispace.me/" | grep -o 'index-[^"]*\.js'
```

### 本机 Agent + 真机 smoke

```bash
curl -s http://127.0.0.1:8002/api/reachy/ping
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  http://127.0.0.1:8002/api/reachy/move/play/local-move/hello \
  -H 'Content-Type: application/json' -d '{"category":"dances"}'
# 浏览器：http://botversex.feispace.me/robots/reachy_mini
# 网络面板应见 localhost:8002 与 ws://localhost:8002/ws/robots/reachy_mini/state?frequency=10 → 101
```

## 最终结果（2026-05-17 验证）

### A. 云端（无 USB）

| 项 | 结果 |
|----|------|
| M18 路由 `/`, `/robots`, `/skills`, `/training`, `/login` | 200 |
| `/robots/reachy_mini` 新 UI | 200，`index-D85pS6YT.js` |
| URDF + 示例 STL GET | 200 |
| `/api/robots` 含 `reachy_mini` | 是 |
| 云端 `/api/reachy/ping` | `ok: false`（预期） |

### B. 云端 URL + 本机 `:8002` + 真机

| 项 | 结果 |
|----|------|
| ping / motors / status / moves 列表 | 200 |
| WS 10 Hz 状态流 | 101 |
| 守护进程 | `:8010`, `/dev/ttyACM0` |
| hello 播放（浏览器）、happy/wake/sleep/goto（API） | 200 |
| 重力补偿 | 禁用，无 500 |
| 页面无 `reachy_state_stream_failed`（daemon 健康时） | 通过 |

## SDK 路径迁移（2026-05-17）

- 原路径 `/home/amd/下载/reachy_mini_Allan` 已 **mv** 至 `/home/amd/sdk/reachy_mini_Allan`（含 `.venv`）。
- [`apps/realtime/config/robots.json`](../apps/realtime/config/robots.json) 中 `sdk_path` 已更新；改配置后需 **重启 realtime**（`load_robot_config` 有 `@lru_cache`）。
- 覆盖路径可用环境变量：`REACHY_MINI_SDK_PATH`。

## 诚实边界 / 剩余问题

- **Git 状态（2026-05-18）**：M19 主体已并入 `9422a8c`；串口 auto、Setup 四步化等见 [M20](./M20-reachy-serial-autodetect-and-agent-release.md)（工作区待 commit）。
- **全量 tarball scp / 全库 rsync**：后台任务曾中止；以定向 rsync 为准，避免 `.pnpm-store`。
- **URDF STL**：Reachy 网格多，云端首次加载控制台可能大量 STL 请求；不影响控制链路。
- **daemon 503**：电机通信错误需手动 stop/start 守护进程。
- **重力补偿**：需 Placo；短期保持 UI 禁用。
- **登录 API**：`POST /api/v1/auth/login` 使用 `email` 字段（非 `username`）；浏览器已登录态与 curl 脚本字段需一致。

## 下一阶段（Reachy 相关）

1. 将 Reachy 控制页 smoke 并入 `scripts/botclaw-acceptance-gate.sh`（云端静态 + 本机 Agent 可选 job）。
2. 固化 `scripts/deploy-reachy.sh` 或扩展 `deploy.sh` 仅同步 Reachy 相关路径。
3. daemon 健康检查与自动恢复提示（503 → 一键重启守护进程文案）。
4. 可选：Placo 运动学以启用重力补偿；URDF 云端 mesh CDN/缓存优化。

## 关键文件索引（便于 Agent 接手）

```
apps/web/src/pages/RobotReachyMini.tsx
apps/web/src/lib/reachyApi.ts
apps/web/src/lib/robotApi.ts
apps/web/src/lib/localAgent.ts
apps/realtime/api/reachy_proxy.py
apps/realtime/api/robots.py
apps/realtime/config/robots.json
apps/realtime/data/reachy_mini_moves/
infra/docker/docker-compose.prod.yml
scripts/deploy.sh
```
