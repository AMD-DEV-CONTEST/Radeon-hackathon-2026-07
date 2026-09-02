# StagePoster — Claude Code 指引

> 项目根目录：`/workspace/poster-engine/`
> Go 模块：`github.com/Ripped-sys/StagePoster/backend`
> 目标硬件：AMD Radeon PRO W7900 48 GB + ROCm 7.2

---

## 1. 项目概览

StagePoster 是一个 **AI 原生音乐活动海报引擎**。核心流程：

```
结构化活动 Brief
        ↓
Qwen3.5-9B 艺术指导 Agent
        ↓
3 个结构化设计方案
        ↓
ComfyUI + Z-Image Turbo 生成 3 张候选图
        ↓
用户选择候选图
        ↓
Go 确定性文字 / Logo / 信息排版
        ↓
Qwen Vision 视觉审查与有限轮自动优化
        ↓
最终海报 + 缩略图 + 审查证据
```

前端只与 Go Backend 通信。ComfyUI 和 vLLM 是内部服务，不暴露给浏览器。

---

## 2. 技术栈

| 层 | 技术 | 端口 |
|---|---|---|
| Go Backend | Go 1.25.0 + `net/http` | `:8080` |
| 数据库 | SQLite (modernc.org/sqlite) | 本地文件 |
| 图像生成 | ComfyUI + Z-Image Turbo | `:8188` |
| LLM / VLM | vLLM + Qwen3.5-9B | `:8001` |
| GPU 驱动 | ROCm 7.2 + HIP | — |
| 对外隧道 | Cloudflare Quick Tunnel | HTTPS |

Go 依赖极少（仅 `golang.org/x/image` + `modernc.org/sqlite`），无外部 Web 框架。

---

## 3. 目录结构

```
/workspace/poster-engine/
├── ComfyUI/                         # ComfyUI fork（git submodule）
│   └── models/
│       ├── diffusion_models/
│       │   └── z_image_turbo_bf16.safetensors
│       ├── text_encoders/
│       │   └── qwen_3_4b.safetensors
│       ├── vae/
│       │   └── ae.safetensors
│       └── loras/
│           └── z_image_turbo_distill_patch_lora_bf16.safetensors
├── models/
│   └── Qwen3.5-9B/                  # vLLM 模型文件
├── workflows/
│   └── z_image_poster_v1.json       # ComfyUI 工作流模板
├── venv/                            # ComfyUI Python 3.10.20 环境
├── .venv-vllm/                      # vLLM Python 3.12 环境
├── .env                             # 项目级环境变量（服务端口、密钥等）
├── scripts/                         # 部署与服务管理脚本
│   ├── install-all.sh               # 一键部署
│   ├── start-all.sh                 # 启动所有服务
│   ├── stop-all.sh                  # 停止所有服务
│   ├── status.sh                    # 查看服务状态
│   ├── smoke-test.sh                # 冒烟测试
│   └── ...
└── backend/
    ├── .env.example                 # 后端环境变量模板
    ├── go.mod / go.sum
    ├── cmd/server/
    │   └── main.go                  # 入口：服务初始化 + 启动
    ├── data/
    │   └── poster.db                # SQLite 数据库
    ├── logs/                        # 日志目录
    ├── run/                         # PID 文件 + tunnel URL
    ├── storage/
    │   ├── jobs/                    # ComfyUI 任务输出
    │   ├── assets/                  # 上传素材存储
    │   └── posters/                 # 最终海报输出
    └── internal/                    # Go 内部包（不可外部导入）
        ├── api/                     # HTTP 路由 + 处理器
        │   ├── server.go            # Server 结构体 + 路由组装
        │   ├── posters.go           # 海报相关端点
        │   ├── assets.go            # 素材相关端点
        │   └── ai_sessions.go       # AI 会话端点
        ├── domain/                  # 领域模型 + 状态常量
        │   ├── poster.go            # PosterStatus, CandidateStatus, 请求/响应结构体
        │   ├── ai_session.go        # AISessionStatus, 会话结构体
        │   └── asset.go             # AssetStatus, 素材结构体
        ├── repository/              # SQLite 数据访问层
        │   ├── sqlite.go            # 连接 + 迁移
        │   ├── posters.go           # poster_requests / poster_candidates 表
        │   ├── ai_sessions.go       # ai_sessions / ai_messages 表
        │   └── assets.go            # assets 表
        ├── service/                 # 核心业务逻辑（无 HTTP）
        │   ├── poster.go            # PosterService：ComfyUI 提交 + 轮询
        │   ├── assets.go            # AssetService：素材处理
        │   ├── asset_processor.go   # 异步素材处理 goroutine
        │   └── health.go            # HealthCollector：各组件健康检查
        ├── poster/                  # 海报高级流程编排
        │   ├── service.go           # poster.Service：编排 planner + evaluator + composer
        │   ├── planner.go           # 设计规划：brief → 3 个 variant spec
        │   ├── evaluator.go         # 候选图视觉评估
        │   ├── composition.go       # 排版引擎接口
        │   ├── composer.go          # 排版实现（Go 原生 image/draw）
        │   ├── finalization.go      # 最终化流程
        │   └── reviews.go           # 视觉审查循环
        ├── assistant/               # AI 会话状态机
        │   ├── service.go           # AI Session 主流程
        │   ├── finalize.go          # finalize 逻辑
        │   └── keyed_lock.go        # 会话级锁
        ├── ai/                      # vLLM 客户端 + Runtime
        │   ├── client.go            # vLLM OpenAI 兼容 API 客户端
        │   ├── service.go           # LLM/VLM 调用封装
        │   └── runtime.go           # GPU 显存管理（sleep/wake）
        ├── comfy/                   # ComfyUI 客户端
        │   ├── client.go            # 提交 prompt + 轮询 history
        │   ├── workflow.go          # Workflow JSON 模板加载 + 填充
        │   └── client_memory_test.go # ComfyUI 内存压力测试
        ├── composer/                # 海报排版引擎
        │   └── composer.go          # 文字/Logo/条形码渲染
        ├── storage/                 # 文件系统抽象
        │   ├── filestore.go         # ComfyUI 任务输出存储
        │   ├── assetstore.go        # 素材文件存储（20MB 上限）
        │   └── posterstore.go       # 最终海报文件存储
        └── worker/                  # 后台 goroutine
            ├── reconciler.go        # ComfyUI 任务状态轮询
            └── poster_reconciler.go # 海报流程状态机推进
```

---

## 4. 核心流程

### 4.1 海报生成状态机

```
planning_candidates → generating_candidates → validating_candidates
                                                    ↓
                                              partial_ready (1/3 ready)
                                                    ↓
                                              awaiting_selection
                                                    ↓
                                              selected → composing
                                                    ↓
                                              succeeded / failed / canceled
```

- `worker/reconciler.go`：每 2 秒轮询 ComfyUI job 状态，将 `generating` → `ready`/`failed`
- `worker/poster_reconciler.go`：推进海报流程状态机，触发 composition、review、finalize
- **关键**：`PartialReady` 不算终态，reconciler 必须继续处理剩余候选图

### 4.2 AI 会话状态机

```
collecting_brief → planning → awaiting_approval → generating
                                                    ↓
                                              awaiting_candidate_selection
                                                    ↓
                                              selected → composing → reviewing
                                                    ↓
                                              succeeded / failed / canceled
```

- `assistant/service.go`：管理 AI 会话生命周期
- 用户消息触发 LLM 调用，LLM 决定下一步动作（规划 / 确认 / 选择 / finalize）

---

## 5. 开发工作流

### 编译

```bash
cd /workspace/poster-engine/backend
go build -o poster-backend ./cmd/server
```

### 运行测试

```bash
cd /workspace/poster-engine/backend
go test ./...
```

### 启动服务

```bash
cd /workspace/poster-engine
./scripts/start-all.sh          # 启动 ComfyUI + vLLM + Backend
./scripts/status.sh             # 检查各服务状态
```

### 冒烟测试

```bash
cd /workspace/poster-engine
./scripts/smoke-test.sh          # 组件级冒烟测试
# 完整 E2E 见 docs/one-click-deployment.md
```

### 一键部署

```bash
cd /workspace/poster-engine
sudo -E bash scripts/install-all.sh
```

---

## 6. 环境变量

`.env` 位于项目根目录。关键变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LISTEN_ADDR` | `:8080` | Backend 监听地址 |
| `COMFY_URL` | `http://127.0.0.1:8188` | ComfyUI 地址 |
| `VLM_URL` | `http://127.0.0.1:8001` | vLLM 地址 |
| `VLM_API_KEY` | `stageposter-vlm-local` | vLLM API Key |
| `VLM_MODEL` | `stageposter-vlm` | vLLM 模型名 |
| `DB_PATH` | `backend/data/poster.db` | SQLite 路径。**线上实际指向 `/workspace/persistence/stageposter/data/poster.db`**，见 §11 |
| `STORAGE_ROOT` | `backend/storage/jobs` | 任务输出目录。线上同样指向持久化目录 |
| `WORKFLOW_PATH` | `workflows/z_image_poster_v1.json` | ComfyUI 工作流 |
| `WORKFLOW_KEY` | `poster-text` | 工作流标识 |
| `WORKFLOW_VERSION` | `1.0.0` | 工作流版本 |
| `POSTER_API_TOKEN` | `""` | API 认证 token。**当前为空 = 无鉴权** |
| `CORS_ORIGIN` | `*` | CORS 来源 |
| `POSTER_FONT_REGULAR` | `""` | 正文字体路径（系统字体名） |
| `POSTER_FONT_BOLD` | `""` | 粗体字体路径 |
| `RECONCILE_INTERVAL` | `2s` | reconciler 轮询间隔 |
| `PROMPT_NODE_ID` | `57:27` | ComfyUI prompt 节点 |
| `NEGATIVE_PROMPT_NODE_ID` | `57:34` | ComfyUI negative prompt 节点 |
| `COMFY_CFG` | `""` | 采样器 cfg 覆盖；留空沿用工作流里的值（2）。**负向提示词只在 cfg > 1 时生效** |
| `SEED_NODE_ID` | `57:3` | ComfyUI seed 节点 |
| `REFERENCE_CONTROL_PATCH` | `""` | `ComfyUI/models/model_patches` 下的 Z-Image ControlNet 权重文件名。启用参考图条件化；留空则参考图只影响需求理解那次 VLM 调用 |

---

## 7. 已知约束与坑

### ROCm / GPU
- vLLM `--enable-sleep-mode` 在 ROCm 7.2 + vLLM 0.20.0 上有 `CUDA Error: invalid argument` 问题，**不要启用**
- ComfyUI 和 vLLM 共享单张 W7900。Qwen 唤醒前会自动卸载 ComfyUI 模型（`ReleaseComfyMemory`）
- GPU 架构 `gfx1100`，确保 `rocm-smi` 显示正确

### ComfyUI
- Workflow JSON 中的节点 ID 是固定的（通过 `PROMPT_NODE_ID` / `SEED_NODE_ID` 配置）
- 任务提交后通过 `/history/{prompt_id}` 轮询输出
- 输出图片存储在 ComfyUI 的输出目录，通过 `storage.FileStore` 复制到 `STORAGE_ROOT`
- **参考图条件化是注入的，不是写在模板里的。** 工作流 JSON 里没有任何参考图节点。
  请求带参考素材时，`comfy.Template.Build` 会往*克隆出来的*图里注入
  `LoadImage` → `Canny` → `ModelPatchLoader` → `ZImageFunControlnet`，
  并把采样器的 `model` 输入改接到 ControlNet 上。不带参考图的请求产出的图与从前
  **逐字节一致** —— 这正是这个特性不会回归掉所有既有调用方的原因。
  不要把这些节点搬进模板文件。`TestBuildWithoutReferenceIsUnchanged` 钉住了这条。
- Z-Image 的 ControlNet **不走** ComfyUI 的 `load_controlnet`，走的是 model-patch 路径
  （`comfy_extras/nodes_model_patch.py`）。`comfy/controlnet.py` 里根本没有 lumina 分支，
  在那里搜会得到假的否定结论。
- 参考图必须先送到 ComfyUI：`comfy.Client.UploadImage` 走 `/upload/image`，
  而不是往 ComfyUI 的 `input/` 目录里写文件 —— 这样容器化或远程的 ComfyUI 也能用。

### vLLM
- 启动参数必须带 `--mm-processor-cache-gb 0`。该值默认 4，跑一段时间后**所有带图请求**
  会稳定 500，报 `AssertionError: Expected a cached item for mm_hash=...`，
  而纯文本请求一切正常。这个症状极易被误判成后端 bug。`scripts/start-all.sh` 已带上。

### 环境变量加载
- **后端二进制自己不读 `.env`。** `scripts/start-all.sh` 里做的是
  `set -a; source "$ENV_FILE"; set +a`。手工跑 `./poster-backend` 会静默丢掉
  `REFERENCE_CONTROL_PATCH` 之类的配置，且不报错 —— 表现为功能"莫名不可用"。

### SQLite
- 使用 `modernc.org/sqlite`（纯 Go 实现，无需 CGO）
- 迁移在 `repository/sqlite.go` 的 `Migrate` 中定义
- 所有查询使用 `context.Context` 超时控制

### 并发
- 两个 reconciler goroutine（`worker/reconciler.go` + `worker/poster_reconciler.go`）每 2 秒Tick一次
- **必须有 panic recovery** — 否则 goroutine 静默死亡
- 会话级操作使用 `sync.Mutex` 防止并发竞态

---

## 8. API 设计约定

- 所有 POST 请求体为 JSON
- 错误响应：`{"error": "message"}` + 对应 HTTP status
- 成功响应：`{"data": ...}` 或直接返回资源对象
- 分页：列表端点接受 `?limit=`（1–100，默认 20）和 `?offset=`（默认 0）。
  超范围的值返回 400，不做静默截断。信封里同时有 `items []`、`count`（本页行数）、
  `total`（表内总行数）、`limit`、`offset`。本文件早期版本只写了 `total int` 且没有
  `count`，而代码一直只返回 `count` —— 现在两个都在，且按实际行为描述。
- 认证：`Authorization: Bearer <POSTER_API_TOKEN>`（可选，生产环境建议启用）

---

## 9. 代码风格

- **包名**：`internal/*` 下的小写短名（`api`, `domain`, `service`, `poster`, `assistant` 等）
- **错误**：使用 `errors.New` 定义包级 sentinel error，不要用字符串比较
- **上下文**：所有耗时操作接收 `context.Context`，HTTP handler 从 `r.Context()` 传递
- **日志**：使用标准库 `log`，生产环境建议替换为结构化日志
- **ID 生成**：使用 `domain.NewID(prefix)` 生成 `prefix_xxxxxxxx` 格式 ID
- **JSON**：字段名使用 `json:"camelCase"`（`posterId`、`sessionId`、`createdAt`）。
  本文件此前写的是 `snake_case`，与代码从来不符。请求与响应形状保持一致。
- **错误**：500 响应统一返回 `{"error":"internal server error"}`，真实原因只记服务端日志。
  **不要把 `err.Error()` 透给客户端** —— 文件系统路径和驱动内部细节会从这里泄漏。
- **文件路径**：绝对路径从环境变量读取，不要硬编码

---

## 10. 修改检查清单

修改代码后确认：
- [ ] `go build ./cmd/server` 编译通过
- [ ] `go test ./...` 全部通过
- [ ] 如有数据库变更，在 `repository/sqlite.go` 添加迁移语句
- [ ] 如有新环境变量，在 `.env.example` 和 `main.go` 的 `env()` 调用中添加
- [ ] 如有新的 ComfyUI 节点绑定，更新 `scripts/` 中的节点 ID 注释
- [ ] 冒烟测试通过 `./scripts/smoke-test.sh`
- [ ] 全量接口回归通过 `.venv-vllm/bin/python scripts/e2e-test.py all`
      （30 条路由 / 127 条断言）。**必须用这个解释器，不能用裸 `python3`** ——
      脚本要用 Pillow 合成测试图，而只有 `.venv-vllm` 里装了。系统 `python3`
      会在跑第一条断言之前就 `ModuleNotFoundError: No module named 'PIL'`。

---

## 11. 持久化与备份

云主机会被重置，所以"东西在哪个目录"是个正确性问题，不是运维偏好。

### 目录约定

NFS 持久化根目录是 `/workspace/persistence`。本项目用
`/workspace/persistence/stageposter/`，`.env` 里四个路径全部指向它：

```
DB_PATH             = /workspace/persistence/stageposter/data/poster.db
STORAGE_ROOT        = /workspace/persistence/stageposter/storage/jobs
ASSET_STORAGE_ROOT  = /workspace/persistence/stageposter/storage/assets
POSTER_OUTPUT_ROOT  = /workspace/persistence/stageposter/storage/posters
```

**注意 `backend/data/poster.db` 是早期遗留文件，不是线上库。** 它还在盘上、还会
被 `DB_PATH` 的默认值指到。备份或排查时认错库，会得到一份看着合理但过期的数据。
判断线上库的唯一依据是 `.env` 里的 `DB_PATH`。

### 备份

```bash
bash scripts/backup-persistence.sh          # 快速
bash scripts/backup-persistence.sh --hash   # 附带权重 sha256，慢
```

产物落在 `/workspace/persistence/stageposter/backups/<时间戳>/`，
`backups/latest` 是指向最新一份的符号链接。每份包含 `RESTORE.md`（逐步恢复说明）、
数据库一致性快照、`env.backup`、权重清单、git 提交状态。

三条设计上的理由，改这个脚本前先读：

1. **数据库用 `VACUUM INTO`，不用 `cp`。** 后端在线时 WAL 里可能有数 MB 尚未
   checkpoint 的数据，`cp` 出来的文件要么偏旧要么撕裂。`VACUUM INTO` 取读快照并
   把 WAL 并进单文件，之后脚本对*快照本身*跑 `integrity_check` —— 要断言的是
   "这份备份能用"，而不是"源库没坏"。
2. **`.env` 必须备份。** 它被 `.gitignore` 排除，所以全机只有一份。
3. **43G 权重不进备份，只留清单。** 盘上没那么多空余。清单是为了核对重新下载的结果，
   见下条。

### 恢复时的两个坑

- **权重重新下载必须带 `HF_HUB_DISABLE_XET=1`。** huggingface.co 直连不通，走
  hf-mirror；但只设 `HF_ENDPOINT` 不够 —— Xet 支撑的大文件会绕过镜像直连
  `cas-server.xethub.hf.co` 然后 401。**小文件下来了、权重没下来，目录看着像是好的，
  退出码也可能是 0。** 只能按 `model-manifest.txt` 逐个核对字节数。
- **恢复数据库要删掉旧的 `-wal` / `-shm`。** 否则 SQLite 会拿陈旧的 WAL 去套新库。

### 不在备份范围内

`storage/`（候选图、成品海报、上传素材，约 410M）只有持久化目录里那一份。
整个 `/workspace/persistence` 丢失则历史海报丢失，数据库记录会指向不存在的文件。
这是**已知且被接受**的取舍：成品可以重新生成，原始 brief 在库里。
