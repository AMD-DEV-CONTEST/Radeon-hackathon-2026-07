# BotverseX 怎么用（源码包上手）

面向拿到本源码包的工程师 / 演示同学。更细的架构见 [architecture.md](./architecture.md)，客户向说明见 [customer-quickstart.md](./customer-quickstart.md)。

---

## 1. 平台是什么

BotverseX 是桌面机器人 **Web 控制台 + 业务 API + 本机实时层**：

| 进程 | 目录 | 端口 | 作用 |
|------|------|------|------|
| Web | `apps/web` | **5173** | React 控制台（机器人页、工作流、训练等） |
| API | `apps/api` | **8000** | 用户 / 数据集元数据 / 训练任务 / Hub |
| Realtime | `apps/realtime` | **8002** | 真机：遥操、录制、Reachy / B601 代理 |

浏览器默认走 Vite 代理：`/api`、`/ws` → realtime `:8002`；业务 `/api/v1` → api `:8000`。

**真机永远在本机 realtime 上跑**，不是云端直接控臂。

---

## 2. 目录地图（源码）

```
botversex/
├── apps/
│   ├── web/                 # 前端 Vite + React
│   ├── api/                 # FastAPI 业务 API
│   ├── realtime/            # Local Agent / 实时服务（机器人主入口）
│   │   ├── api/             # b601.py / reachy_proxy.py / …
│   │   ├── config/          # robots.json · robots.windows-demo.json
│   │   ├── runtimes/        # so101 / reachy_mini / b601_rs
│   │   └── run_api.py       # 启动入口（开发用 --http）
│   └── pi0_sidecar/         # 可选推理侧车
├── packages/botclaw-spec/   # 契约 Schema（真源）
├── docs/                    # 架构 / 上手 / Windows 演示
├── scripts/                 # Linux 一键启动、打包、B601/Reachy 工具
│   ├── linux/               # 演示机重启等
│   └── windows/             # Windows 演示机脚本
├── vendor/                  # 第三方参考（如 reBotArm）
├── progress/                # 里程碑笔记（开发过程）
└── README.md
```

---

## 3. 环境要求

- **Node.js** ≥ 20  
- **Python** 3.12+  
- Linux 真机：用户加入 `dialout`（串口）后重新登录  
  `sudo usermod -aG dialout $USER`

### 机器人额外依赖（按需）

| 机器人 | 额外需要 |
|--------|----------|
| **Reachy Mini** | Allan SDK：`~/sdk/reachy_mini_Allan`（或设 `REACHY_MINI_SDK_PATH`）；USB 串口；**本体电源必须打开** |
| **reBot B601-RS** | PCAN-USB + SocketCAN（`can0`）、主臂 USB、48V 从臂；LeRobot / motorbridge（见 `scripts/rebot-lerobot-install.sh`） |
| **SO-101** | LeRobot + Feetech 串口（见 `scripts/dev-up.sh` 注释） |

---

## 4. 第一次安装（解压后）

```bash
cd botversex   # 解压出来的目录

# API
python3 -m venv apps/api/.venv
./apps/api/.venv/bin/pip install -r apps/api/requirements.txt

# Realtime（Local Agent）
python3 -m venv apps/realtime/.venv
./apps/realtime/.venv/bin/pip install -r apps/realtime/requirements.txt

# Web
cd apps/web && npm install && cd ../..

# 可选：复制环境变量模板
# cp apps/api/.env.example apps/api/.env   # 若存在
```

密钥只放本机 `.env`，**不要**打进源码包或提交 git。

---

## 5. 日常启动 / 停止（Linux）

```bash
cd botversex
bash scripts/dev-all.sh up      # API + Realtime + Web
```

- 控制台：<http://127.0.0.1:5173>  
- API 文档：<http://127.0.0.1:8000/docs>  
- 健康检查：<http://127.0.0.1:8002/api/setup/health>  

停止：

```bash
bash scripts/dev-all.sh down
```

### 手动三终端（等价）

```bash
# 1) API
cd apps/api && source .venv/bin/activate
uvicorn app.main:app --port 8000 --app-dir .

# 2) Realtime（开发务必 --http，否则 Vite 代理 502）
cd apps/realtime && source .venv/bin/activate
python run_api.py --http

# 3) Web
cd apps/web && npm run dev -- --host 0.0.0.0
```

---

## 6. 按机器人怎么用

### 6.1 Reachy Mini（随机表演 / 官方动作库 / 官方双工对话）

BotverseX 默认接 **Reachy Mini Lite**（外接电脑 + USB）。完整版（板载树莓派 / WiFi / 电池）规格对照见 [docs/reachy-mini-seeed.md](./reachy-mini-seeed.md)（整理自 [Seeed Wiki](https://wiki.seeedstudio.com/cn/reachymini_getting_started/)）。

1. USB 插入电脑，**打开机器人本体电源**（只插 USB 不够，会出现  
   `No Reachy motor on /dev/ttyACM0`）。
2. 启动平台后打开：  
   <http://127.0.0.1:5173/robots/reachy_mini>
3. 点 **启动机器人**（拉起 daemon `:8010`）。
4. **动作** Tab → 官方表情/舞蹈，或开 **随机表演**（约每 10 秒从 HF 官方库抽一个）。
5. **对话** Tab → **官方实时对话**（默认 HuggingFace，**无需 OpenAI/Gemini Key**）→ 开始对话；运行后内嵌 Web UI（`:7860`）。
6. 高级抽屉 → **规格与入门**：Lite/完整版差异、组装注意、HF App 清单。

Lite 硬件摘要：6-DOF 头 + 身体旋转 + 2 天线；4 麦克风 + 5W 喇叭 + 广角摄像头；约 28cm / 1.5kg；无板载 WiFi/电池/加速度计。

环境变量（可选）：

| 变量 | 说明 |
|------|------|
| `REACHY_MINI_SDK_PATH` | Allan SDK 路径 |
| `REACHY_MINI_SERIAL_PORT` | 固定串口，如 `/dev/ttyACM0` |

HF 官方库 / Conversation App 需本机可访问 HuggingFace，或已有缓存 / `HF_ENDPOINT` 镜像。

### 6.2 reBot B601-RS / B601-DM（遥操 → 数据 → Qualia Pi0.5 → 算力节点部署）

最短闭环（不必先懂所有 Tab）：

1. **硬件**：DM 串口 `/dev/ttyACM0`（或 RS：`can0`），主臂 USB，从臂 48V。打开 <http://127.0.0.1:5173/robots/b601_rs>  
2. **连接面板**：连接 → 唤醒从臂 → **遥操** Tab 试手感；**停止遥操会卸力**。  
3. **数据 Tab**：选相机（冰球常用 front=`/dev/video4` icspring + side=`/dev/video6` 1080P USB；编号会变，以预览为准）→ 填任务描述 → 开始采集。  
4. **上传 HF**：数据 Tab 展开「上传到 Hugging Face」→ `你的用户名/数据集名`。  
   - **给 Qualia 云训：保持「私有」未勾选（公开）**——Qualia 目前无法读私有 HF 仓。  
5. **训练**：打开 <http://127.0.0.1:5173/training?runtime=b601_rs&algorithm=pi05>  
   - 算法选 **Pi0.5**，backend 云端 Qualia，`dataset_hf_id` 填上一步 Hub id，GPU 建议 `n3-L40x1`，smoke 约 2h / 正式 4–6h。  
   - 需本机 API 已配置 `QUALIA_API_TOKEN`（`apps/api/.env`）。  
6. **算力节点**：到 <http://127.0.0.1:5173/settings/remote-compute> 配置你的推理节点（本机 / 远端 SSH / 云 HTTP）。详见 [docs/remote-compute.md](./remote-compute.md)。  
7. **部署 Tab**：本机采相机+关节 → 算力节点推理 → 本机驱动臂。见下方「smoke / 全量」。

#### 算力节点

BotverseX 不假设你拥有任何特定型号的 GPU 机器。你可以配置任意数量的「算力节点」：

- **本机**（默认）：sidecar 跑在本机。无 GPU 时只能跑小模型（如 ACT）；有本地 NVIDIA GPU 时可跑 Pi0.5。
- **远端 SSH**：朋友的 GB10 / DGX Spark、家里的服务器、云 VM 都行。BotverseX 通过 SSH rsync 模型过去。
- **远端 HTTP**：仅 HTTP 推理服务，无法 SSH（如云推理服务）。

#### Smoke vs 正式全量

| | Smoke（冒烟） | 正式全量 |
|--|--|--|
| 含义 | 用很少数据（约 10 集）快速训一版，验证整条链路能跑通 | 用完整数据集（如 125 集）训的生产向模型 |
| 数据示例 | `userresu2026/b601-dm-icehockey-smoke` | `userresu2026/b601-dm-icehockey-v1` |
| 预期 | 可能已有粗动作/一点抓取感，但不可靠 | 更稳、更贴任务 |
| 节点默认模型路径 | `<node.model_root>/pi05_smoke_patched` | `<node.model_root>/pi05_icehockey_v1` |

**不要在无 GPU 的笔电上 load Pi0.5**（容易 OOM）。推理走你配置的算力节点的 sidecar。

#### 全量训完后换模验收

1. 部署页看「全量 Qualia 训练进度」→ 状态为 succeeded 且出现 `output_model_id`。  
2. 点 **同步到算力节点并加载**（或本机执行）：
   ```bash
   python scripts/sync_model_to_remote.py --node-id <your_node> --job-id <QUALIA_JOB_ID> --load
   # 老脚本名仍可用（deprecated 别名）：
   python scripts/sync_pi05_to_gb10.py --job-id <QUALIA_JOB_ID> --load
   ```
3. 确认「算力节点已加载模型」标签为 **正式全量**。  
4. 选 front/side，预览画面与录制一致。  
5. 周围留空 → **部署到机械臂** → 先慢动观察；异常立刻 **急停（停推理+卸力）**。  
6. 任务文案须与录制/训练一致（冰球默认文案不要改乱）。

轮询训练：`python scripts/poll_qualia_pi05_smoke.py --job-id <id>`（脚本名历史遗留，支持任意 job）。

已跑通的示例数据：

| Hub dataset | 用途 |
|-------------|------|
| `userresu2026/b601-dm-icehockey-smoke` | 10 eps 冒烟 |
| `userresu2026/b601-dm-icehockey-v1` | 125 eps 正式（合并包） |

详细硬件：`docs/customer-quickstart.md` § B601、`docs/b601-*.md`。

> **与 Reachy 不冲突**：Reachy 用 `/dev/ttyACM0`，B601 主臂用 `/dev/ttyUSB0`，从臂用 CAN。可同时插着，但演示时建议一次专注一台。

### 6.3 Windows 演示机

见 [windows-demo-setup.md](./windows-demo-setup.md)。要点：

- 用 `scripts/windows/run-detached.cmd` 或计划任务 `BotverseX-Dev`
- 配置 `robots.windows-demo.json`
- Windows **无 SocketCAN**，B601 真机遥操请用 Linux；演示机以 Reachy 为主

---

## 7. 常用排障

| 现象 | 处理 |
|------|------|
| Vite `502` / 「实时服务未响应」 | 确认 `:8002` 在跑；用 `python run_api.py --http` |
| Reachy「No Reachy motor…」 | 开本体电源；拔插 USB；确认串口是 ACM 不是被 B601 占用的 USB0 |
| B601 Internal Server Error（Windows） | 无 CAN 时 health 应快速返回；更新后的 `b601.py` 已做 Windows 快路径 |
| 串口 Permission denied | `dialout` 组 + 重新登录 |
| 官方动作库空 / 502 | HF 网络或缓存；Linux 可先在能上网的机器下好 hub 缓存再拷贝 |

健康检查：

```bash
curl -s http://127.0.0.1:8002/api/setup/health
curl -s http://127.0.0.1:8002/api/robots | head
```

---

## 8. 再打源码包

```bash
bash scripts/package-source.sh
# 输出：../botversex-source-YYYYMMDD-HHMM.tar.gz
# 需要 git 历史：WITH_GIT=1 bash scripts/package-source.sh
```

包内 **不含** `.venv` / `node_modules` / `.env` / 训练权重 / Piper 语音模型（`.piper_voices`）；解压后按第 4 节重装依赖。Reachy 对话 TTS 无 Piper 时会降级到 espeak。

---

## 9. 相关文档索引

| 文档 | 内容 |
|------|------|
| [README.md](../README.md) | 仓库总览与一键命令 |
| [architecture.md](./architecture.md) | 分层架构图 |
| [customer-quickstart.md](./customer-quickstart.md) | 客户向连接说明 |
| [windows-demo-setup.md](./windows-demo-setup.md) | Windows 演示机 |
| [AGENTS.md](./AGENTS.md) | 给 AI/开发者的约定 |
| [AGENT_HANDOFF.md](../AGENT_HANDOFF.md) | 交接与里程碑 |
| `progress/` | 功能迭代笔记（M21 Reachy Apps 等） |
