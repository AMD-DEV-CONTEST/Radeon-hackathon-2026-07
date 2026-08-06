# BotverseX — Agent 交接文档

**写于**: 2026-04-20（M7 完结 / 迁移 Ubuntu 前）  
**补充**: 2026-05-05 — 一键启动、源码打包、局域网 WebSocket、当前目录与 README 对齐  
**写给**: 接手开发环境的 Agent / 人类工程师  
**历史范围**: M1 → M7 主要在 Windows + SO-101；当前主线多在 **Linux**，Realtime 已含相机 HTTP/MJPEG、Reachy Mini 平台嵌入等（细节以代码为准）。

---

## 0. 读这份文档需要多久？

> **5 分钟通读，10 分钟可以开始写代码。**
>
> 凡是"已完成"的部分，不需要重新理解实现细节，只需要知道**它存在、它工作、别动它**。
> 凡是"下一步"的部分，读完就能直接动手。

---

## 1. 项目是什么

**BotverseX** = 机器人 Skill 训练和部署平台，目标是"**硬件版 HuggingFace**"。

核心价值主张（刘师傅原话）：
> "机器人硬件很乱，把 Skill、工作流、训练、部署摆出来"
> "卖给 HuggingFace 或 AMD 是最大概率的退出路径"

**不是**：机器人控制器、ROS 平台、仿真软件。
**是**：让任何人能把机器人"教会做一件事"的 SaaS 平台。

---

## 2. 整体架构（3 个服务 + 1 个前端）

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (Vite React :5173)                                 │
│  Dashboard / Skills / Datasets / Training / AIHub / Compare│
└────────────────┬────────────────────────────────────────────┘
                 │ HTTP /api/v1/*  (JWT 认证)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  apps/api  FastAPI :8000  (业务层)                           │
│  - 用户认证 JWT                                             │
│  - Dataset 元数据 CRUD                                      │
│  - Training job 管理 (本地 MLP + Qualia 云)                 │
│  - Model 管理                                               │
│  - AI Hub 代理 (HuggingFace API mirror)                     │
│  - 平台统计 /api/v1/stats                                   │
│  DB: SQLite botversex_dev.db (M8 后考虑 Postgres)           │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTP /api/* + WS /ws/*
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  apps/realtime  FastAPI :8002  (实时层)                      │
│  - WebSocket /ws/teleop   ← 接收 leader 关节数据            │
│  - WebSocket /ws/ui       → 广播给前端 / follower           │
│  - WebSocket /ws/robotstate → 定时推送机器人状态            │
│  - WebSocket /ws/compare  → 推理帧 vs 真实帧对比            │
│  - REST /api/datasets     → 本地 parquet 数据集读取         │
│  - REST /api/runtimes     → 已注册 Runtime 列表             │
│  - REST /api/urdf/*       → URDF + STL mesh 服务            │
└────────────────────────────────────────────────────────────┘

真机侧（Python 进程，不是服务）：
  python -m sender --runtime so101 --mode leader   # 读 leader 臂数据 → /ws/teleop
  python -m sender --runtime so101 --mode follower # 订阅 /ws/ui → 写 follower 臂
```

---

## 3. 代码目录结构

```
botversex/
├── apps/
│   ├── api/                         # FastAPI 业务 API (:8000)
│   │   ├── app/
│   │   │   ├── api/v1/endpoints/    # 所有 REST 端点
│   │   │   │   ├── auth.py          # JWT 登录/注册
│   │   │   │   ├── datasets.py      # 数据集 CRUD
│   │   │   │   ├── trainings.py     # 训练任务 + Qualia
│   │   │   │   ├── models.py        # 模型管理
│   │   │   │   ├── hub.py           # AI Hub (HF API 代理)
│   │   │   │   ├── stats.py         # 平台统计
│   │   │   │   └── teleoperation.py # 遥操控制
│   │   │   ├── models/              # SQLAlchemy ORM 模型
│   │   │   │   ├── dataset.py       # Dataset 表
│   │   │   │   ├── training.py      # TrainingJob + Model 表
│   │   │   │   └── user.py          # User 表
│   │   │   ├── services/
│   │   │   │   ├── hf_hub_service.py  # HuggingFace Hub SDK 封装
│   │   │   │   ├── qualia_service.py  # Qualia Studio API 封装
│   │   │   │   └── trainer.py         # 本地 MLP 训练 worker
│   │   │   ├── migrations/
│   │   │   │   └── m6_skill_columns.py  # 已运行过，勿重复运行
│   │   │   └── core/config.py       # Settings（读 .env）
│   │   ├── botversex_dev.db         # SQLite（含真实数据，随代码走）
│   │   └── requirements.txt
│   │
│   ├── realtime/                    # FastAPI 实时服务 (:8002)
│   │   ├── api/
│   │   │   ├── main.py              # FastAPI app，含 CORS + 所有路由挂载
│   │   │   ├── websocket.py         # ConnectionManager + JointData
│   │   │   ├── robotstate.py        # /ws/robotstate 定时推送
│   │   │   ├── inference.py         # 推理 session 管理
│   │   │   ├── playback.py          # Dataset 回放 API
│   │   │   └── safety.py            # SafetyGate (关节限位 + 增量限幅)
│   │   ├── runtimes/                # 硬件 Runtime 抽象 (M6)
│   │   │   ├── _protocol.py         # Runtime Protocol 定义
│   │   │   ├── so101/               # SO-101 6DoF 实现（已完整）
│   │   │   └── reachy_mini/         # Reachy Mini 9DoF（已注册，dry smoke 绿）
│   │   ├── sender/                  # 真机通信（Python 进程）
│   │   │   ├── __main__.py          # CLI 入口: --runtime --mode --com_port
│   │   │   ├── reader.py            # 读 leader 臂关节角
│   │   │   ├── writer.py            # 写 follower 臂 Goal_Position
│   │   │   ├── follower.py          # Follower 主循环（WS client）
│   │   │   ├── calibration.py       # 关节角度标定
│   │   │   ├── port_scan.py         # COM 口自动扫描
│   │   │   └── calibration_data.json / calibration_follower.json
│   │   ├── datasets/                # 本地录制数据（parquet + botclaw.json）
│   │   ├── models/                  # 本地训练产出 checkpoint
│   │   ├── dora-bambot/URDF/        # SO-101 URDF 模型 + STL mesh
│   │   └── run_api.py               # 启动入口
│   │
│   └── web/                         # Vite + React 前端 (:5173)
│       ├── src/
│       │   ├── pages/               # 所有页面
│       │   │   ├── Dashboard.tsx    # 平台总览（真数据，/api/v1/stats）
│       │   │   ├── Skills.tsx       # Skill + Runtime 列表 + 实时遥测
│       │   │   ├── Datasets.tsx     # 数据集列表
│       │   │   ├── DatasetDetail.tsx # 数据集详情 + 3D 回放 + HF 发布
│       │   │   ├── Training.tsx     # 训练任务（本地 MLP + Qualia 算法）
│       │   │   ├── Models.tsx       # 模型列表
│       │   │   ├── Compare.tsx      # 推理对比（双视角 3D + RMSE）
│       │   │   ├── AIHub.tsx        # AI Hub 列表（接 HF 真数据）
│       │   │   ├── AIHubDetail.tsx  # 模型详情页
│       │   │   ├── AIHubLeaderboard.tsx # 排行榜
│       │   │   ├── Teleop.tsx       # 遥操控制面板
│       │   │   └── Login.tsx        # 登录页
│       │   ├── hooks/
│       │   │   ├── useRobotState.ts      # /ws/robotstate WS hook
│       │   │   └── useTeleopWebSocket.ts # /ws/ui WS hook
│       │   ├── components/layout/Navbar.tsx
│       │   └── lib/realtimeOrigin.ts # WS 默认同源（经 Vite 代理），便于局域网访问
│       └── vite.config.ts           # Proxy: /api/v1→:8000；多数 /api/*、/ws→:8002
│
└── packages/
    └── botclaw-spec/schemas/        # JSON Schema 定义
        ├── skill.schema.json        # Skill 数据模型
        └── robot_state.schema.json  # RobotState WS payload
```

---

## 4. 已完成里程碑（不要碰）

| 里程碑 | 完成内容 | 验收标准 |
|--------|---------|---------|
| **M1** | FastAPI 骨架 + JWT 认证 + SQLite | 登录 → 拿 Token → 访问受保护接口 |
| **M2** | Dataset 录制 + 元数据管理 + parquet 转换 | 录制 → 停止 → 自动出现在 /datasets |
| **M3** | 本地 MLP 训练 + 模型管理 | POST /trainings → worker 跑 → succeeded |
| **M4** | SafetyGate + Compare echo + 推理回放 | Compare 页双视角 3D 播放，RMSE 曲线 |
| **M5** | 真机 Follower 闭环 | written 上涨, dropped=0, 看门狗 ≤0.5s 触发 |
| **M6** | Runtime 抽象 + Reachy Mini + COM 扫描 + /robots→/skills | --runtime so101 / reachy_mini 均可注册 |
| **M7** | HF AI Hub + Qualia 训练后端 + Dashboard 真数据 + HF 发布 | Dashboard 真数字, AI Hub 拉 HF 真模型 |

**M7 之后所有功能已真机验证通过。**

---

## 5. 数据库状态

- 文件：`apps/api/botversex_dev.db`（随代码一起拷过来，已含真实数据）
- 表：`users` / `datasets` / `training_jobs` / `models`
- **M6 migration 已运行**：三张表均已有 `skill_id`、`robot_type`、`train_backend`、`hf_model_id` 字段
- 若新机器上数据库表结构出问题（`no such column` 错误），运行：
  ```bash
  cd apps/api
  python -m app.migrations.m6_skill_columns
  ```

---

## 6. 关键配置

### 6.1 端口约定（不要改）

| 服务 | 端口 | 启动命令 |
|------|------|---------|
| apps/api | 8000 | `uvicorn app.main:app --reload --port 8000` |
| apps/realtime | 8002 | `python run_api.py` |
| apps/web | 5173 | `npm run dev` |

### 6.2 环境变量（`.env` 放在 `apps/api/`）

```env
# 生产/开发都要改的
JWT_SECRET=换成随机字符串最少32位

# Qualia Studio（暂未配置，不配置会降级到 mock 模式）
QUALIA_API_TOKEN=
QUALIA_API_URL=https://api.qualia.studio/v1

# HuggingFace（用于 Dataset 发布到 HF）
HF_TOKEN=

# Ubuntu 上可以切换到真实 Postgres（可选）
# DATABASE_URL=postgresql://user:pass@localhost/botversex
```

### 6.3 CORS 配置位置

两个服务都配置了 CORS，白名单均为 `localhost:5173` / `localhost:3000`：
- `apps/api/app/main.py`（或 app 初始化处）
- `apps/realtime/api/main.py` ← M8 如果跑在不同 IP，改这里

### 6.4 WebSocket 地址（2026-05 更新）

- **默认**：`useTeleopWebSocket.ts` / `useRobotState.ts` 使用 **`src/lib/realtimeOrigin.ts`**，WebSocket 连到**当前页面的 host:port**（例如 `ws://192.168.x.x:5173/ws/...`），由 **Vite dev server 代理**到 Realtime `:8002`。这样在局域网用手机/另一台电脑打开前端时，不会错误连到客户端自己的 `localhost:8002`。
- **覆盖**：设置 `VITE_REALTIME_WS_URL`（完整 `ws://` 或 `wss://` 前缀、无 path）时，将直连该后端；**不要**在局域网演示里把它设成 `ws://localhost:8002`。
- 部分页面（如 Compare / Playback / Training WS）本来就使用 `window.location.host`，行为与上述一致。

### 6.5 一键启动与打包（给工程师）

```bash
# 项目根目录：API + Realtime + Web（日志在 /tmp/botversex_*.log）
bash scripts/dev-all.sh up
bash scripts/dev-all.sh status
bash scripts/dev-all.sh down

# 仅后端（8000 + 8002），脚本会设置 BOTVERSEX_LEROBOT_PATH 等（见 dev-up.sh）
bash scripts/dev-up.sh up
```

**源码交接包**（排除 `.venv`、`node_modules`、`.tmp` 等大目录；解压得到顶层目录 `botversex/`）：

```bash
bash scripts/package-source.sh
# 需要 .git：WITH_GIT=1 bash scripts/package-source.sh
```

---

## 7. 真机操作流程（供参考，M8 前仍适用）

### SO-101 真机启动

```bash
# 推荐：根目录一键（等价于下面 1–3）
# bash scripts/dev-all.sh up

# 终端 1 — 业务 API
cd apps/api && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# 终端 2 — 实时服务
cd apps/realtime && source .venv/bin/activate
python run_api.py

# 终端 3 — 前端（演示局域网请加 --host）
cd apps/web && npm run dev -- --host 0.0.0.0

# 终端 4 — Leader 臂（USB 插 leader 臂）
cd apps/realtime
python -m sender --runtime so101 --mode leader --com_port auto

# 终端 5 — Follower 臂（USB 插 follower 臂，需推理会话激活）
python -m sender --runtime so101 --mode follower --com_port auto --torque-on-start
```

### Ubuntu 串口权限（迁移后必须做一次）

```bash
sudo usermod -aG dialout $USER
# 然后重新登录，或 newgrp dialout
```

Linux 上 COM 口变成 `/dev/ttyUSB0` 等，`--com_port auto` 会自动扫描，无需手动指定。

---

## 8. M8 与视觉链路（历史规划 + 当前代码状态）

### M8 的北极星

> **让机器人"看着做"** — 从纯关节闭环升级到视觉+关节闭环（Policy-from-pixels）

### M8.1 相机通路（当前实现概况）

Realtime 已提供 **HTTP** 相机接口（设备列表、snapshot、MJPEG 流等），前端 Teleop 等页面通过 `/api/camera/*`（Vite 代理到 :8002）拉流。冒烟脚本：`apps/realtime/_scripts/smoke_m8_camera.py`。

若仍要做 **WebRTC 低延迟** 或 RealSense 专用栈，再在 `apps/realtime/api/` 扩展；依赖以 `requirements.txt` 为准。

```bash
# 无 RealSense 时可用 OpenCV + USB 摄像头测通路
pip install opencv-python
```

### M8.2 Policy-from-pixels（SmolVLA / Pi0）

**依赖 M8.1**：需要相机帧作为模型输入。

AMD AI Max 395 的优势在这里体现：
- ROCm 支持（替代 CUDA）
- 推理框架用 ONNX Runtime + ROCm EP，或 PyTorch + ROCm

```bash
# 确认 ROCm 可用
rocm-smi
python -c "import torch; print(torch.cuda.is_available())"  # ROCm 下也返回 True

# 安装 ROCm 版 PyTorch（按 AMD 官方文档）
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.0
```

### M8.3 Reachy Mini

Runtime 与 Web 侧 **RobotReachyMini** 等页面已接入（含本地 daemon / 状态 WS 等，以当前代码为准）。真机联调时仍建议跑通：`/api/runtimes` 可见 `reachy_mini`，再按页面与 `config/robots.json` 配置检查 USB daemon。

---

## 9. 代码规范（延续前任 Agent 的风格）

- **Python**：类型注解优先，`from __future__ import annotations`，async/await
- **FastAPI**：所有端点用 `Depends(get_db)` 拿 session，`Depends(get_current_user)` 验证
- **React**：函数组件 + hooks，Tailwind CSS，`authJson<T>()` 工具函数做认证请求
- **新 Runtime**：必须实现 `_protocol.py` 里的 `Runtime` Protocol，加 dry smoke 脚本验证
- **数据库变更**：不要直接改 ORM 模型就完事，同步在 `app/migrations/` 写迁移脚本
- **不要重写已有的稳定功能**，有 bug 就修，没 bug 别动

---

## 10. 已知遗留问题（低优先级，不紧急）

| 问题 | 位置 | 影响 |
|------|------|------|
| Workflow Editor 页面顶部导航栏有时被遮挡 | `apps/web/src/pages/` | 纯 UI 问题，不影响功能 |
| Reachy 真机环境因设备而异 | `runtimes/reachy_mini/`、`RobotReachyMini.tsx` | 以本机 daemon + 网络为准 |
| QUALIA_API_TOKEN 未配置，Qualia 算法显示为灰色 | Training 页面 | 预期行为，等 Token 申请到再配 |
| 本地训练 MLP 仅支持简单全连接，不支持 ACT | `services/trainer.py` | ACT 走 Qualia 云训练路径 |

---

## 11. 商业化背景（理解做什么、为什么这么做）

刘师傅的核心判断（2026-04-19 凌晨）：

1. **退出路径**：被 HuggingFace 或 AMD 收购概率最高
2. **差异化**：不是做最好的机器人控制器，是做"硬件版 HuggingFace"——整合、调度、生态
3. **第一版标准**：功能不需要多，但每个功能要打磨好，能 demo
4. **数据飞轮**：越多人上传 Skill 数据集，平台越有价值（类比 HF datasets）
5. **Skill 优先于 Robot**：平台的核心资产是 Skill（行为），不是 Robot 型号

对代码决策的影响：
- AI Hub 页面的成色 = 平台的成色，**P0 优先级**
- 每个新功能优先考虑"能不能在 5 分钟 demo 里展示出来"
- 不要自研能用 Qualia / HF 解决的东西

---

## 12. 快速验证清单（迁移到 Ubuntu 后，5 分钟验证）

```bash
# 1. 三服务启动无报错
curl http://localhost:8000/docs           # → FastAPI Swagger 文档
curl http://localhost:8002/api/runtimes   # → {"runtimes":[so101, reachy_mini]}
curl http://localhost:5173               # → React 前端 HTML

# 2. 登录拿 Token（字段为 email + password；开发环境可用你在库里的用户，或 scripts/dev-up.sh 里用到的测试账号）
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test","password":"test"}'
# → {"access_token":"..."}  （若库中无该用户，先注册或换真实账号）

# 3. 数据集列表有数据
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/datasets
# → 应有 5-6 条真实录制数据集

# 4. 平台统计正常
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/stats
# → datasets.total >= 5, training_jobs.total >= 1

# 5. AI Hub 能拉 HF 数据
curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/v1/hub/models?tag=robotics&limit=5"
# → 有 openvla 等真实模型（需要网络访问 HuggingFace）
```

---

## 2026-08-06 状态增补（WebSerial 零安装主线完成后）

> 本节由自主进化循环（30 分钟 cron）维护。最新状态以 `progress/README.md` 已完成清单 + `docs/roadmap.md` 为准。

### 当前主线一句话

**WebSerial 零安装路径（S1–S3 + U1–U4）代码侧全部完成**：Chrome/Edge 打开 `/robots/so101?mode=browser` → 授权串口 → 扫舵机 → 挥手（3D 同动）→ 3 秒录制 → 第一条 dataset 入库 → 故障时浏览器内一键诊断导出日志。全程不装 Python / Local Agent。

### 关键文件地图（新）

| 能力 | 文件 |
|------|------|
| Feetech 协议层 + StsSerialBus | `apps/web/src/lib/webserial.ts`（24 断言冒烟：`scripts/webserial-protocol-smoke.mjs`） |
| 第一动作仪式 + 录制 + 诊断 | `apps/web/src/components/so101/`（BrowserDirectPanel / SerialDiagnostics） |
| 首录写端点 | `apps/realtime/api/datasets.py` → `POST /api/datasets/record`（parquet + botclaw.json） |
| 部署就绪清单 | `docs/deploy-readiness.md`（rsync + 重建命令、验收清单、四个坑） |
| 访谈门禁 | `docs/strategy/2026-08-06-interview-gate.md`（H1/H2/H3，5 场决策规则） |

### 当前纪律（接手必读）

1. **不扩机型/商店/支付**；不重构 `components/b601|reachy`；不动 `apps/realtime/api/b601.py` 内部逻辑。
2. **不新增无用户信号的功能**：下一步做什么（U3 录制深化 / 留存 / 其它）由访谈门禁结论决定，别加戏。
3. **工作区已清零**：137 个历史未提交文件已于 M36 按功能块快照提交；新改动只提交自己的文件。
4. 提交纪律：commit message 准确，不打包别人改动；绝不 push。

### 待办（等真人/硬件，不是代码问题）

- 真机验收：Chrome + SO-101 走部署清单第 3 节 6 项
- 访谈执行：20–30 人触达 → 5 场（M40 材料现成）
- 部署：`docs/deploy-readiness.md` 第 2 节两条命令

---

*原始交接：2026-04-20（M1–M7 语境）*  
*补充：2026-05-05（启动脚本、打包、WS 局域网、文档与 README 对齐）*  
*增补：2026-08-06（WebSerial 主线完成、工作区清零、访谈门禁待执行）*  
*项目负责人：用户*
