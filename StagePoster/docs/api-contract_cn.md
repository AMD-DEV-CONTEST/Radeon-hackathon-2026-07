# StagePoster API Contract v1.0

> **⚠️ 两处与实现不符，照抄会全线 404。**
>
> - **基础路径是 `/api`，不是 `/api/v1`。** 后端没有注册 `/api/v1` 命名空间。
>   本文档多处写 `/api/v1`，前端那样配会每个请求都 404。
> - **错误格式是 `{"error": "message"}` + HTTP 状态码，不是
>   `application/problem+json`。** RFC 9457 那套分类是未实现的设计提案，
>   详见 `docs/error-codes_cn.md` 顶部的说明。
>
> 前端应当对接的真实接口见 **`docs/frontend-api-handoff.md`**（权威）。
>
> 本文档其余部分（资源关系、异步任务模型、素材上传约定）与实现基本一致。

状态：黑客松 MVP 接口契约
服务端：Go + SQLite + 本地文件存储 + ComfyUI
协作方式：Contract First、异步任务、Mock 优先联调

1. 文档目标

本文件定义 StagePoster 前端与后端之间的公共 HTTP API。

前端只负责表达：

用户要制作什么

用户上传了哪些素材

选择了什么设计风格

最终需要什么规格的内容

前端不需要了解：

ComfyUI 节点 ID

Workflow JSON 结构

模型路径

Prompt 模板

Seed

采样器

ComfyUI 队列和 WebSocket 协议

后端负责：

素材接收与管理

Creative Brief 校验

风格解释

Prompt 构建

Workflow 选择

ComfyUI 调度

任务状态管理

Logo 和文字排版

输出文件管理

2. 运行模式

StagePoster 使用同一套 API 支持两种运行模式。

模式

推理方式

使用场景

mock

模拟生成流程

前端本地开发、接口联调、演示兜底

comfy

调用真实 ComfyUI

GPU 服务器联调、比赛展示

从 Mock 切换到 ComfyUI 时，前端不能修改接口调用逻辑，只允许修改 API 地址。

3. 推荐的黑客松部署方式

3.1 真实联调

后端和 ComfyUI 运行在当前 GPU 服务器。

Frontend
   ↓ HTTPS
StagePoster Go Backend
   ↓ localhost / private network
ComfyUI
   ↓
GPU

前端只需要配置：

API_BASE_URL=https://你的后端地址/api/v1

这种方式下，前端同学不需要：

安装 ComfyUI

下载模型

配置 ROCm

获取 SQLite 数据库

同步上传文件

运行 GPU Worker

3.2 本地 Mock

仓库仍需支持本地 Mock 模式，让前端在后端服务器不可用时继续开发。

建议配置：

APP_MODE=mock
DATABASE_PATH=./data/stageposter.db
STORAGE_ROOT=./outputs
SERVER_PORT=8080

后端首次启动时应自动：

创建 data/

创建 outputs/

创建 SQLite 数据库

执行数据库迁移

初始化基础风格和输出规格

加载 Mock 海报

启动相同 API

4. GitHub 提交规则

应提交

数据库迁移定义

初始化数据定义

.env.example

Mock 示例海报

配置模板

API 文档

Workflow Manifest

启动说明

本地运行脚本

不应提交

data/*.db
data/*.db-wal
data/*.db-shm
outputs/projects/
logs/
.env
*.safetensors
*.ckpt
*.pt
*.pth
ComfyUI/output/

SQLite 数据库是运行时文件，不是项目源码。

5. 公网暴露规则

只允许公网访问 StagePoster Go API。

ComfyUI 必须保持私有：

127.0.0.1:8188

或者仅允许后端所在私有网络访问。

禁止：

Browser → ComfyUI API

必须：

Browser → StagePoster API → ComfyUI

后端负责隐藏 ComfyUI 的节点、路径、错误细节和队列协议。

6. API 基础约定

6.1 Base URL

本地：

http://localhost:8080/api/v1

远程：

https://<backend-host>/api/v1

6.2 Content-Type

场景

Content-Type

普通请求

application/json

素材上传

multipart/form-data

标准错误

application/problem+json

图片输出

对应的图片 MIME

6.3 请求头

请求头

是否必须

用途

Accept

推荐

指定响应格式

Content-Type

有 Body 时必须

请求格式

X-Request-ID

可选

前后端日志追踪

Idempotency-Key

创建生成任务时必须

防止重复提交

Authorization

根据部署决定

Demo 访问限制

用户没有提交 X-Request-ID 时，由后端生成并在响应中返回。

6.4 时间与 ID

时间统一使用 UTC RFC 3339。

ID 是不透明字符串。

前端不得解析 ID 的结构。

前端不得依赖数据库自增数字。

前端必须忽略未知的可选响应字段。

7. 核心资源关系

Project
 ├── Assets
 ├── Creative Brief Snapshots
 ├── Generation Jobs
 └── Output Assets

Project

代表一个活动或宣传项目。

Asset

代表用户上传的人物、Logo 和参考图。

Creative Brief

代表一次生成提交时的完整需求快照。

Generation Job

代表一次异步生成任务。

Output Asset

代表最终海报、预览图或后续的视频、VJ 文件。

8. API 列表

8.1 健康检查

GET /health

响应：

{
  "status": "ok",
  "service": "stageposter-backend",
  "mode": "mock",
  "version": "0.1.0",
  "time": "2026-07-20T12:00:00Z"
}

健康检查不能触发模型。

8.2 获取后端能力

GET /capabilities

用途：

获取支持的素材类型

获取可用风格

获取排版模板

获取输出规格

获取上传限制

判断是否支持取消、重试和实时进度

示例响应：

{
  "output_types": ["poster"],
  "asset_types": [
    "artist_image",
    "logo",
    "style_reference",
    "background_reference"
  ],
  "style_presets": [
    {
      "id": "retro_japan_80s",
      "version": "1",
      "display_name": "80s Japan"
    }
  ],
  "layout_presets": [
    {
      "id": "portrait_hero",
      "version": "1",
      "display_name": "Portrait Hero"
    }
  ],
  "output_presets": [
    {
      "id": "poster_2x3",
      "width": 1024,
      "height": 1536
    }
  ],
  "limits": {
    "max_image_bytes": 20971520,
    "max_assets_per_project": 20,
    "max_candidates": 4,
    "max_queued_jobs_per_client": 3
  },
  "features": {
    "mock_mode": true,
    "job_cancel": true,
    "job_retry": true,
    "live_progress": false
  }
}

前端不能把这些能力全部硬编码在页面里。

8.3 创建项目

POST /projects

请求：

{
  "name": "Tokyo Night Festival 2026",
  "project_type": "music_event",
  "client_reference": "frontend-draft-17"
}

约束：

name 必填，1 至 120 字符。

project_type MVP 固定为 music_event。

client_reference 仅用于前端草稿关联。

响应：

{
  "id": "proj_01K...",
  "name": "Tokyo Night Festival 2026",
  "project_type": "music_event",
  "created_at": "2026-07-20T12:00:00Z"
}

8.4 查询项目

GET /projects/{project_id}

响应：

{
  "id": "proj_01K...",
  "name": "Tokyo Night Festival 2026",
  "project_type": "music_event",
  "asset_count": 3,
  "job_count": 2,
  "created_at": "2026-07-20T12:00:00Z",
  "updated_at": "2026-07-20T12:05:00Z"
}

8.5 上传素材

POST /projects/{project_id}/assets

请求格式：

multipart/form-data

字段：

字段

必填

说明

file

是

文件

asset_type

是

素材类型

label

否

展示名称

rights_confirmed

是

用户确认有权使用

client_asset_id

否

前端本地 ID

响应：

{
  "id": "asset_01K...",
  "project_id": "proj_01K...",
  "asset_type": "artist_image",
  "status": "ready",
  "label": "Lead singer",
  "mime_type": "image/png",
  "width": 2048,
  "height": 2048,
  "size_bytes": 4821931,
  "preview_url": "https://<host>/api/v1/assets/asset_01K.../preview",
  "created_at": "2026-07-20T12:01:00Z"
}

后端不能返回内部文件路径。

8.6 查询项目素材

GET /projects/{project_id}/assets

响应：

{
  "items": [
    {
      "id": "asset_01K...",
      "asset_type": "artist_image",
      "status": "ready",
      "label": "Lead singer",
      "preview_url": "https://<host>/api/v1/assets/asset_01K.../preview"
    }
  ]
}

8.7 获取素材预览

GET /assets/{asset_id}/preview

用于页面缩略图。

8.8 获取素材内容

GET /assets/{asset_id}/content

用于获取原始或标准化素材。

前端不得自行拼接文件路径。

8.9 创建生成任务

POST /projects/{project_id}/generations

请求头：

Idempotency-Key: 每次用户明确提交时生成的唯一值

请求：

{
  "output_type": "poster",
  "brief": {
    "schema_version": "1.0",
    "event": {
      "name": "Tokyo Night Festival",
      "date": "2026-08-01",
      "start_time": "19:30",
      "venue": "Shibuya Stage",
      "city": "Tokyo"
    },
    "performers": [
      {
        "name": "Neon Echo",
        "role": "headliner"
      }
    ],
    "copy": {
      "headline": "TOKYO NIGHT",
      "subheadline": "NEON ECHO LIVE",
      "call_to_action": "Tickets Available",
      "lyrics_excerpt": "Meet me under the city lights",
      "language": "en"
    },
    "style": {
      "preset_id": "retro_japan_80s",
      "preset_version": "1",
      "mood": ["nostalgic", "energetic"],
      "palette": ["#E94F64", "#1C2841", "#F6D58A"],
      "layout_preset_id": "portrait_hero",
      "prompt_hint": "City-pop night atmosphere"
    },
    "asset_bindings": [
      {
        "role": "primary_artist",
        "asset_id": "asset_artist"
      },
      {
        "role": "event_logo",
        "asset_id": "asset_logo"
      },
      {
        "role": "style_reference",
        "asset_id": "asset_style"
      }
    ],
    "output": {
      "preset_id": "poster_2x3",
      "candidate_count": 2,
      "format": "png",
      "include_clean_background": false
    },
    "rights_confirmed": true
  }
}

响应状态：

202 Accepted

响应：

{
  "job_id": "job_01K...",
  "project_id": "proj_01K...",
  "status": "queued",
  "stage": "queued",
  "progress": 0,
  "poll_url": "https://<host>/api/v1/jobs/job_01K...",
  "created_at": "2026-07-20T12:02:00Z"
}

后端必须保存完整 Brief 快照。

8.10 查询任务

GET /jobs/{job_id}

运行中：

{
  "id": "job_01K...",
  "project_id": "proj_01K...",
  "status": "running",
  "stage": "generating",
  "progress": 58,
  "message": "Generating poster candidate 1 of 2",
  "attempt": 1,
  "outputs": [],
  "created_at": "2026-07-20T12:02:00Z",
  "started_at": "2026-07-20T12:02:03Z",
  "updated_at": "2026-07-20T12:03:12Z"
}

完成：

{
  "id": "job_01K...",
  "project_id": "proj_01K...",
  "status": "completed",
  "stage": "completed",
  "progress": 100,
  "message": "Poster generation completed",
  "outputs": [
    {
      "id": "out_01K...",
      "type": "poster",
      "format": "png",
      "width": 1024,
      "height": 1536,
      "url": "https://<host>/api/v1/outputs/out_01K.../content",
      "preview_url": "https://<host>/api/v1/outputs/out_01K.../preview"
    }
  ],
  "completed_at": "2026-07-20T12:04:30Z"
}

任务执行失败时，任务资源仍然存在，因此查询接口返回 HTTP 200：

{
  "id": "job_01K...",
  "status": "failed",
  "stage": "generating",
  "progress": 58,
  "error": {
    "code": "GENERATION_FAILED",
    "message": "The generation engine failed",
    "retryable": true
  }
}

8.11 取消任务

POST /jobs/{job_id}/cancel

响应：

{
  "job_id": "job_01K...",
  "status": "cancelling"
}

取消为尽力而为。

如果 GPU 已经完成，任务仍可能进入 completed。

8.12 重试任务

POST /jobs/{job_id}/retry

请求：

{
  "strategy": "same_plan"
}

响应：

{
  "job_id": "job_new",
  "retry_of": "job_old",
  "status": "queued"
}

重试创建新任务，不能修改旧任务状态。

8.13 获取输出预览

GET /outputs/{output_id}/preview

8.14 获取最终输出

GET /outputs/{output_id}/content

MVP 可由 Go 后端直接读取本地文件并返回。

以后换对象存储时，前端接口不变。

9. 前端轮询约定

MVP 不单独实现 SSE 或前端 WebSocket。

建议：

前 10 秒每秒查询一次。

之后每 2 秒查询一次。

遇到 completed、failed、cancelled 停止。

网络失败不能重新创建任务。

页面刷新后根据 job_id 恢复查询。

progress=100 不等于完成，必须判断任务状态。

10. CORS

远程后端只允许：

前端线上域名
http://localhost:5173

允许的方法：

GET
POST
OPTIONS

允许的请求头：

Content-Type
Authorization
X-Request-ID
Idempotency-Key

不要在携带凭据的请求中配置：

Access-Control-Allow-Origin: *

11. SQLite 约定

SQLite 只由后端访问。

前端永远不读取 .db 文件。

数据库放服务器本地磁盘。

开启 WAL。

使用短事务。

MVP 只运行一个后端实例。

Job 必须先写数据库，再进入内存队列。

后端重启时检查未完成任务。

.db 文件不提交 Git。

建议表：

projects
assets
generation_jobs
job_events
output_assets
idempotency_keys
schema_migrations

12. ComfyUI 边界

ComfyUI Adapter 内部负责：

上传输入图片

提交 API Workflow

获取 prompt_id

监听 WebSocket

查询 Queue

查询 History

获取输出文件

翻译节点错误

这些信息不得成为前端契约的一部分。

13. API 冻结规则

前后端开始开发前，必须确认：

路径

请求字段

必填字段

响应字段

枚举

Job 状态

错误结构

上传限制

冻结后：

可增加可选字段

不可随意重命名字段

不可删除已有字段

新增状态枚举必须通知前端

内部实现可以自由调整

14. 验收标准

前端能创建 Project。

前端能上传人物图、Logo、风格参考图。

前端能提交完整 Creative Brief。

后端立即返回 Job ID。

前端能展示任务阶段。

前端能收到海报 URL。

Mock 和 Comfy 模式接口一致。

前端只修改 API_BASE_URL 即可切换环境。

ComfyUI 不直接暴露给浏览器。
