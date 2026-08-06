# M20 — Reachy 串口自动探测、Local Agent 发布与 Setup 四步化

日期: 2026-05-18

## 完成了什么

在 **M19**（Reachy 控制台 + 云端走 Local Agent）已并入 `9422a8c` 的基础上，本里程碑完成：

1. **Reachy Mini USB 串口自动探测**（`serial: "auto"`），换 `/dev/ttyACM*` 口无需手改配置。
2. **`botversex-local-agent` 独立仓库发布**（GitHub `main` → `b246080`），与 Setup 页 clone 路径一致。
3. **生产网站前端重建**（ECS `index-CS3K-Z5w.js`），Setup 增加 `git pull` 提示。
4. **SO-101 Setup 向导四步化**（连接 → 遥操作 → 录制 → 训练并运行），合并原 Step1/2 与 Step5/6。
5. **生产账号与 CORS**（`ethan` 管理员、访客 `test`、双域名 `feispace.me` / `achao.xin`）。
6. **Local Agent 路由细化**：目录类 API 走云端，硬件 API 走本机 `:8002`。

`72156cd` 已提交：`botversex.achao.xin` 与 `deploy.sh` 双域名；**M20 主体改动仍在工作区，待 commit**。

---

## 相对 M19 的增量对照

| 维度 | M19（2026-05-17 记录） | M20（本里程碑） |
|------|------------------------|-----------------|
| 串口配置 | `robots.json` 可写死路径；M19 真机 smoke 用 `ttyACM0` | **`"serial": "auto"`** + SDK 电机 ping 扫描 |
| Local Agent 仓库 | 文档指向 GitHub，**代码仍为旧版 `/dev/ttyACM0`** | **`b246080` 已 push**，含完整 `reachy_proxy` |
| Setup 步骤 | 6 步（相机/臂/遥操作/录制/训练/推理） | **4 步**（`connect` / `teleop` / `record` / `run`） |
| `localAgent.ts` | 生产一律打本机 `:8002` | **目录 API 同源**，仅硬件走 Agent |
| Git | M19 写明「未提交」 | **`9422a8c` 已含 M17–M19**；M20 增量未提交 |
| 线上 bundle | `index-D85pS6YT.js` | **`index-CS3K-Z5w.js`**（2026-05-18 ECS 构建） |

---

## 新增 / 变更代码审视

### 1. `apps/realtime/api/reachy_proxy.py`（+~298 行，核心）

**职责**：Reachy 守护进程生命周期、HTTP/WS 代理、`/api/reachy/ping` 诊断。

**串口解析优先级**（`_resolve_serial_port_meta`）：

```text
REACHY_MINI_SERIAL_PORT 环境变量
    → BotverseX 托管守护进程记录的 _active_daemon_serial
    → 守护进程 TCP :8010 已开 → 从日志解析最后一次 --serialport
    → configured=="auto" 或 配置路径不存在 → _auto_detect_reachy_port()
    → auto 仍失败 → fallback /dev/ttyACM0（仅作占位，ping hints 会说明）
```

**自动探测**（`_auto_detect_reachy_port`）：

- 遍历 `sorted(glob.glob("/dev/ttyACM*"))`。
- 子进程调用 Allan SDK `lookup_for_motor(port, motor_id=10, baud=1_000_000)`。
- 结果缓存 **30s**；`local-daemon/start` 开头 **强制 invalidate** 并 `force_detect=True`。

**守护进程启动**（`POST /local-daemon/start`）：

- 启动前清缓存；若 HTTP 已可达则从日志回填 `_active_daemon_serial`。
- 子进程写 `/tmp/botversex_reachy_mini_daemon.log`；最多 **30×1s** 等待 HTTP ready。
- 失败时清 `_active_daemon_serial` 与探测缓存。

**Ping**（`GET /api/reachy/ping`）：

- 返回 `serial_detection: { port, source, configured }`。
- 中文/英文 `hints`（含「换 USB 后点启动守护进程会重新探测」）。

**审视结论**：逻辑闭环完整；`fallback ttyACM0` 在 daemon 已占用串口时不再误导（有 log/daemon 分支）。依赖本机已安装 Reachy SDK（`REACHY_MINI_SDK_PATH` / `robots.json` `sdk_path`）。

---

### 2. `apps/realtime/config/robots.json`

```json
"ports": { "serial": "auto" }
```

Reachy `service.command` 仍用 `{serial}` 占位，由 `reachy_proxy` 解析后填入 `--serialport`。

---

### 3. `scripts/sync-local-agent.sh`（新建）

- 将 `reachy_proxy.py` 与 Reachy 的 `transport` / `command` 同步到 `botversex-local-agent`。
- **不覆盖** local-agent 里各用户自己的 `sdk_path`。
- 默认目标：`.tmp/botversex-local-agent`。

---

### 4. `scripts/install-local-agent.sh`（新建）

- 一键 `git clone` / `git pull` `metahubaifeel/botversex-local-agent`。
- CPU-only PyTorch + 阿里云 PyPI 镜像，避免演示机误下 CUDA torch。
- 与 Setup 页说明一致，降低「装 Agent 失败」支持成本。

---

### 5. `apps/web/src/lib/localAgent.ts`

| API 类型 | 路由 |
|----------|------|
| 目录 / 静态 | `/api/robots`, `/api/runtimes`, `/api/urdf` → **同源（云端）** |
| 硬件控制 | `/api/reachy/*`, 录制/遥操作等 → **localStorage 中的 Agent URL** |

新增：`hasConfiguredLocalAgent()`, `clearLocalAgentUrl()`, `isCatalogApiPath()`, `shouldRouteToLocalAgent()`。

**审视结论**：手机/平板打开云端时，不会因 Chrome 同步了桌面 `localhost:8002` 而导致目录 API 失败；Reachy 真机仍要求本机 Agent。

---

### 6. Setup 向导（`apps/web`）

| 文件 | 变更 |
|------|------|
| `setup-types.ts` | `SO101_STEPS` 改为 4 步；保留旧 step id 以兼容 localStorage |
| `SetupProvider.tsx` | `connectComplete()`；`normalizeHydratedState()` 把旧 `camera`/`arm` → `connect`，`train`/`inference` → `run` |
| `Step1Connect.tsx` | **新建**：嵌入 `Step1Camera` + `Step2Arm` |
| `Step4Run.tsx` | **新建**：训练推荐 + 跳转 Training/Inference |
| `Step5Train.tsx` / `Step6Inference.tsx` | **删除** |
| `Step1Camera.tsx` / `Step2Arm.tsx` | 支持 `embedded` 模式 |
| `Setup.tsx` | Reachy：`git pull` 更新 Agent 文案 |

---

### 7. 生产与安全（`apps/api` + `infra/docker`）

| 文件 | 变更 |
|------|------|
| `database.py` | 种子用户：`ethan` / `linux`（admin）；`test` / `test`（guest, pro, 非 admin） |
| `docker-compose.prod.yml` | `JWT_SECRET` / `ENCRYPTION_KEY` 随机值；CORS 仅生产域名（无 localhost） |

**审视结论**：compose 内密钥已写入仓库——生产机应通过 env 覆盖或 secret 管理，避免长期依赖 compose 明文（后续可迁 `.env` + 不提交）。

---

### 8. 其它工作区改动（非 Reachy 主线）

- `Compare.tsx` / `DatasetDetail.tsx`：大篇幅 UI/布局调整（与 M17 数据集体验相关）。
- `RobotReachyMini.tsx`：小改动（与 M19 控制台一致为主）。
- `entitlements.ts`：微调。

---

### 9. 外部仓库 `botversex-local-agent`

- **Commit**：`b246080` on `main`（2026-05-18 push）。
- 与 monorepo `reachy_proxy` + `serial: auto` 对齐。
- 朋友 `git clone` / `git pull` 后即具备换口自动探测。

---

## 解决了什么问题

1. **换 USB 口找不到 Reachy（根因）**
   - `botversex-local-agent` 与早期 `robots.json` 写死 `/dev/ttyACM0`（或错误 ACM 口）。
   - 同一台机多设备时 SO-101 占 ACM0/1，Reachy 常在 **ACM2**。
   - **修复**：电机 ID 10 扫描 + 每次启动守护进程强制重探 + 日志回填占用中的串口。

2. **云端用户误连云端 realtime 控硬件**
   - M19 已用 `agentFetch`；M20 再区分 **目录 API 同源**，避免 localStorage 污染。

3. **Setup 步骤过多**
   - 6 步合并为 4 步，降低首次上手路径长度。

4. **Local Agent 仓库与主仓脱节**
   - `sync-local-agent.sh` + GitHub push，与网站 Setup 说明一致。

---

## 架构（朋友用网站 + Setup Agent）

```text
https://botversex.feispace.me  （静态 UI，bundle index-CS3K-Z5w.js）
  ├─ /api/robots, /api/urdf     → 云端 nginx（无 USB）
  └─ /api/reachy/*, /ws/...     → 本机 Local Agent :8002
         └─ reachy_proxy（serial auto）
                └─ daemon :8010 → USB Reachy Mini
```

---

## 关键命令 / 配置

### 同步 Local Agent 并发布

```bash
bash scripts/sync-local-agent.sh
# 在 botversex-local-agent 目录：
git add api/reachy_proxy.py config/robots.json
git commit -m "fix(reachy): auto-detect USB serial"
git push origin main
```

### 本机验证（真机）

```bash
curl -s http://127.0.0.1:8002/api/reachy/ping | python3 -m json.tool
# serial_detection.source 应为 auto 或 daemon；port 应为实际 ACM 口

curl -sS -m 60 -X POST http://127.0.0.1:8002/api/reachy/local-daemon/start
curl -s -X POST http://127.0.0.1:8002/api/reachy/move/play/local-move/hello
```

### ECS 更新前端（定向 rsync + 构建）

```bash
RSYNC_RSH='ssh -i ~/.ssh/id_ed25519_ecs -o StrictHostKeyChecking=no'
rsync -avz -e "$RSYNC_RSH" \
  apps/web/src/ apps/web/package.json apps/web/package-lock.json \
  apps/web/vite.config.ts apps/web/tsconfig*.json apps/web/index.html \
  apps/web/tailwind.config.js apps/web/postcss.config.js apps/web/public/ \
  root@47.113.126.51:/opt/botversex/apps/web/

ssh -i ~/.ssh/id_ed25519_ecs root@47.113.126.51 \
  'cd /opt/botversex && docker compose -f infra/docker/docker-compose.prod.yml build web && \
   docker rm -f botversex-web && docker compose -f infra/docker/docker-compose.prod.yml up -d web'
```

### 云端 smoke

```bash
curl -sL https://botversex.feispace.me/ | grep -o 'index-[^"]*\.js'
curl -sL https://botversex.feispace.me/assets/index-CS3K-Z5w.js | grep -c 'git pull'
```

---

## 最终结果（2026-05-18 验证）

| 项 | 结果 |
|----|------|
| 本机 `_auto_detect_reachy_port(force=True)` | `/dev/ttyACM2`（通电时） |
| `GET /api/reachy/ping` | `ok: true`, `serial_detection.source: daemon` |
| `POST /local-daemon/start` + `hello` | 200 / uuid |
| 浏览器 `localhost:5173/robots/reachy_mini` | 连接、播放 hello |
| GitHub `botversex-local-agent` `main` | `b246080` |
| 线上 bundle | `index-CS3K-Z5w.js`，含 Setup `git pull` 文案 |
| `botversex.achao.xin` HTTPS | 仍待 DNS/证书（M18/M19 已知）；`feispace.me` 可用 |

---

## 诚实边界 / 剩余问题

- **Monorepo M20 改动未 commit**：`reachy_proxy`、Setup 四步、`database.py` 等仍在工作区。
- **ECS realtime 镜像**：本次主要更新 **web**；云端仍无 USB，朋友必须本机跑 **已 pull 的** Local Agent。
- **SDK 路径**：`robots.json` 默认 `/home/amd/sdk/reachy_mini_Allan`；他人需 `REACHY_MINI_SDK_PATH` 或改 local-agent 配置。
- **compose 明文密钥**：应轮换并改为部署时注入。
- **全量 rsync 到 ECS**：勿 `--delete` 整库；`apps/web` 需含 `package.json` 才能 `build web`。

---

## 下一阶段

1. **Commit M20**：`reachy` serial auto + setup 4-step + `sync-local-agent.sh` + prod seed（单 PR 或拆分）。
2. **local-agent**：在仓库增加 `scripts/install-linux.sh`（与 monorepo `install-local-agent.sh` 对齐或 submodule）。
3. **Reachy smoke**：`scripts/botclaw-acceptance-gate.sh` 增加可选本机 `ping` + `hello` job。
4. **achao.xin SSL**：DNS-01 或 standalone，与 `deploy.sh` 双域名一致。

---

## 关键文件索引

```
apps/realtime/api/reachy_proxy.py      # 串口 auto + daemon 生命周期
apps/realtime/config/robots.json       # reachy_mini serial: auto
scripts/sync-local-agent.sh
scripts/install-local-agent.sh
apps/web/src/lib/localAgent.ts
apps/web/src/lib/setup-types.ts
apps/web/src/components/setup/Step1Connect.tsx
apps/web/src/components/setup/steps/Step4Run.tsx
apps/web/src/pages/Setup.tsx
apps/api/app/models/database.py
infra/docker/docker-compose.prod.yml
# 外部：https://github.com/metahubaifeel/botversex-local-agent @ b246080
```
