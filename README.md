# BotverseX

> **English summary** — BotverseX is an **embodied-AI data-loop platform**: one website
> that makes the full loop short and cheap — **connect → teleoperate → record → train →
> deploy** — for real robot runtimes (SO-101, Reachy Mini, B601-RS, LeKiwi, Unitree G1,
> AmazingHand). Recordings land as **LeRobot-format parquet** datasets; training runs
> **locally on AMD Radeon GPUs via ROCm** (verified on Strix Halo / gfx1151, torch
> `2.10.0+rocm7.0`) or on cloud nodes; policies deploy back to the real robot. SO-101 is
> **zero-install**: the browser drives the Feetech STS3215 servos directly through the
> **Web Serial API**.
>
> **Hackathon submission (AMD AI DevMaster 2026, Track 3)** — [Technical report](./docs/hackathon-2026-07/technical-report.md) ·
> [Reproducibility instructions](./docs/hackathon-2026-07/reproducibility.md) ·
> Live site: https://botversex.feispace.me
>
> 中文详细文档见下文。

桌面机器人平台：**Web 控制台 + 业务 API + 实时服务**，覆盖遥操作、录制、训练（含 Qualia 云）、推理与多硬件 Runtime（SO-101、Reachy Mini 等）。

系统架构图（分层、代理、Local Agent、BotClaw 契约）见 **[docs/architecture.md](./docs/architecture.md)**。

更完整的里程碑与排障说明见 **[AGENT_HANDOFF.md](./AGENT_HANDOFF.md)**。
平台叙事、长期定位与产品推进原则见 **[docs/strategy](./docs/strategy/README.md)**。

**上手怎么用（推荐先读）：[docs/HOW-TO-USE.md](./docs/HOW-TO-USE.md)**

## 目录结构（与仓库一致）

```
botversex/
├── apps/
│   ├── web/           # 主前端 (Vite + React)
│   ├── api/           # 业务 API (FastAPI, :8000)
│   └── realtime/      # 实时服务 (FastAPI + WebSocket, :8002)
├── packages/
│   └── botclaw-spec/  # BotClaw 契约（JSON Schema 等）
├── docs/
│   ├── architecture.md  # 系统架构图与代理/桥接说明
│   └── strategy/        # 平台最高纲领、叙事与路线原则
├── scripts/
│   ├── dev-up.sh      # 拉起 API + Realtime（含 LeRobot 路径等）
│   ├── dev-all.sh     # dev-up + 前端 :5173
│   └── package-source.sh  # 打源码包给工程师（排除 venv/node_modules）
└── infra/docker/      # 可选：docker compose 开发栈
```

## 环境要求

- **Node** ≥ 20（前端）
- **Python** 3.12+（api / realtime 各自独立 venv）
- Linux：串口权限 `sudo usermod -aG dialout $USER` 后重新登录

## 推荐：一键本地联调（Linux）

先装好依赖（只需第一次）：

```bash
cd apps/api && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cd ../realtime && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cd ../web && npm install
cd ../..
```

在项目根目录：

```bash
# 若 SO-101 / LeRobot 在本机非常规路径，可导出（见 scripts/dev-up.sh 内注释）
# export BOTVERSEX_LEROBOT_PATH=/path/to/lerobot/src

bash scripts/dev-all.sh up
```

- 前端：<http://127.0.0.1:5173>（`dev-all` 使用 `--host 0.0.0.0`，局域网可用本机 IP 访问）
- API：<http://127.0.0.1:8000/docs>
- Realtime：<http://127.0.0.1:8002/api/setup/health>

停止：

```bash
bash scripts/dev-all.sh down
```

## 手动三终端（等价于上面）

```bash
# 终端 1 — API
cd apps/api && source .venv/bin/activate
uvicorn app.main:app --port 8000 --app-dir .

# 终端 2 — Realtime
cd apps/realtime && source .venv/bin/activate
python run_api.py

# 终端 3 — Web（监听所有网卡便于演示）
cd apps/web && npm run dev -- --host 0.0.0.0
```

## 使用 pnpm（可选）

仓库根目录配置了 `pnpm dev:web`；首次需在 monorepo 根目录 `pnpm install`，再 `pnpm dev:web`。日常开发也可只在 `apps/web` 下用 `npm install` / `npm run dev`，与 `dev-all.sh` 一致。

## 把源码包发给工程师（不要打包 venv）

```bash
bash scripts/package-source.sh
# 默认生成：../botversex-source-YYYYMMDD.tar.gz（与项目目录同级）
# 需要 Git 历史：WITH_GIT=1 bash scripts/package-source.sh
```

解压后按本文「一键」或「三终端」重装 venv 与 `npm install` 即可。

## 配置

- 业务密钥与第三方 Token：在 **`apps/api/`** 下配置 `.env`（勿提交；可参考项目内 `.env.example` 若存在）。
- 前端默认通过 **Vite 代理** 访问 `/api`、`/ws`；局域网演示时不要设置 `VITE_REALTIME_WS_URL=ws://localhost:8002`，否则手机会连到自己机器的 8002。需要固定后端时再设该变量。

## 设计原则（简要）

1. 契约优先：`packages/botclaw-spec` 为 Schema 真源（见 [docs/architecture.md](./docs/architecture.md)）。
2. api / realtime / web 可分开启动，本地通过端口与代理协作；云端真机需 Local Agent 桥接。
3. 真机链路见 `AGENT_HANDOFF.md` 中的 sender / 串口说明。
