# StagePoster Error Codes v1.0

> **⚠️ 历史设计稿 —— 不是实际实现的行为。**
>
> 本文档规定的是 `/api/v1/projects/...` 下的 RFC 9457
> `application/problem+json` 响应。**后端两者都不存在**：没有 `/api/v1` 路由命名
> 空间，错误一律是朴素信封：
>
> ```json
> { "error": "message" }
> ```
>
> 外加相应的 HTTP 状态码（`internal/api/server.go:439`）。500 响应刻意只回
> 通用的 `{"error":"internal server error"}`，真实原因记在服务端日志里，避免
> 泄漏文件系统路径和驱动内部信息。
>
> 前端应当对接的真实接口见 **`docs/frontend-api-handoff.md`**（权威）。
>
> 本文件作为最初的错误分类设计保留。下面的错误码命名和 HTTP 状态映射，作为
> "系统区分了哪些错误"的参考仍然有用；但传输格式不是这样。

错误格式：RFC 9457 Problem Details
Content-Type：application/problem+json

1. 标准结构

{
  "type": "https://stageposter.example/problems/asset-not-found",
  "title": "Asset not found",
  "status": 404,
  "detail": "Asset does not exist or is not available in this project.",
  "instance": "/api/v1/projects/proj_01K.../generations",
  "code": "ASSET_NOT_FOUND",
  "request_id": "req_01K...",
  "retryable": false,
  "job_id": null,
  "errors": []
}

必填字段：

字段

用途

type

稳定的问题类型 URI

title

简短错误名称

status

HTTP 状态

detail

当前请求的说明

instance

出错接口或资源

code

前端判断逻辑使用

request_id

日志关联

retryable

是否建议重试

errors

字段级错误

可选字段：

job_id
project_id
asset_id
retry_after_seconds

不能返回：

Stack Trace

SQL

本地绝对路径

环境变量

Token

ComfyUI 原始内部错误

2. 字段校验错误

{
  "type": "https://stageposter.example/problems/validation-error",
  "title": "Request validation failed",
  "status": 422,
  "detail": "The creative brief contains invalid fields.",
  "instance": "/api/v1/projects/proj_01K.../generations",
  "code": "VALIDATION_ERROR",
  "request_id": "req_01K...",
  "retryable": false,
  "errors": [
    {
      "field": "brief.event.date",
      "code": "INVALID_DATE",
      "message": "Use YYYY-MM-DD."
    },
    {
      "field": "brief.output.candidate_count",
      "code": "OUT_OF_RANGE",
      "message": "Candidate count must be between 1 and 4."
    }
  ]
}

field 使用请求 Body 的点路径。

3. HTTP 状态使用

状态

场景

400

JSON 或 Multipart 无法解析

401

认证失败

403

没有权限

404

资源不存在

409

状态冲突或幂等冲突

413

文件或请求过大

415

不支持的媒体类型

422

字段错误或不支持的组合

429

限流或队列满

500

未预期服务端错误

502

ComfyUI 返回异常

503

服务或推理引擎暂不可用

504

调用推理引擎超时

Job 自身执行失败时，查询 Job 仍返回 HTTP 200，并在 Job Body 中显示 failed。

4. 通用请求错误

Code

HTTP

可重试

MALFORMED_JSON

400

否

MALFORMED_MULTIPART

400

否

VALIDATION_ERROR

422

否

UNSUPPORTED_SCHEMA_VERSION

422

否

REQUEST_TOO_LARGE

413

否

UNSUPPORTED_MEDIA_TYPE

415

否

UNAUTHORIZED

401

视情况

FORBIDDEN

403

否

RATE_LIMITED

429

是

5. Project 错误

Code

HTTP

可重试

PROJECT_NOT_FOUND

404

否

PROJECT_LIMIT_REACHED

422

否

PROJECT_STATE_CONFLICT

409

否

6. Asset 错误

Code

HTTP

可重试

ASSET_NOT_FOUND

404

否

ASSET_NOT_READY

409

视情况

ASSET_TYPE_MISMATCH

422

否

ASSET_PROJECT_MISMATCH

422

否

ASSET_TOO_LARGE

413

否

ASSET_DIMENSIONS_TOO_SMALL

422

否

ASSET_DIMENSIONS_TOO_LARGE

422

否

ASSET_DECODE_FAILED

422

否

ASSET_UNSUPPORTED_FORMAT

415

否

ASSET_UNSAFE_SVG

422

否

ASSET_PROCESSING_FAILED

500

是

ASSET_STORAGE_FAILED

500

是

ASSET_LIMIT_REACHED

422

否

RIGHTS_CONFIRMATION_REQUIRED

422

否

7. Brief 和规划错误

Code

HTTP

可重试

STYLE_PRESET_NOT_FOUND

422

否

LAYOUT_PRESET_NOT_FOUND

422

否

OUTPUT_PRESET_NOT_FOUND

422

否

UNSUPPORTED_OUTPUT_TYPE

422

否

UNSUPPORTED_ASSET_COMBINATION

422

否

MISSING_PRIMARY_ARTIST

422

否

COPY_TOO_LONG

422

否

PLANNING_FAILED

500

视情况

WORKFLOW_NOT_AVAILABLE

503

是

8. Job 错误

Code

场景

可重试

JOB_NOT_FOUND

Job 不存在

否

JOB_NOT_CANCELLABLE

当前状态不可取消

否

JOB_NOT_RETRYABLE

不允许重试

否

JOB_QUEUE_FULL

队列满

是

JOB_INTERRUPTED

后端重启或 Worker 中断

是

JOB_TIMEOUT

任务总超时

是

JOB_CANCELLED

用户取消

否

IDEMPOTENCY_CONFLICT

同一个 Key 对应不同请求

否

队列错误建议带：

retry_after_seconds
Retry-After

9. ComfyUI 和 Workflow 错误

Code

可重试

含义

COMFYUI_UNAVAILABLE

是

无法连接 ComfyUI

COMFYUI_SUBMISSION_FAILED

视情况

Workflow 提交失败

COMFYUI_QUEUE_REJECTED

视情况

引擎拒绝任务

COMFYUI_CONNECTION_LOST

是

监控连接断开

COMFYUI_HISTORY_UNAVAILABLE

是

History 暂不可用

COMFYUI_EXECUTION_FAILED

视情况

执行失败

COMFYUI_OUTPUT_MISSING

视情况

没有预期输出

WORKFLOW_INVALID

否

Workflow 格式错误

WORKFLOW_NODE_ERROR

否

节点错误

MODEL_NOT_FOUND

否

模型缺失

CUSTOM_NODE_NOT_FOUND

否

自定义节点缺失

GENERATION_FAILED

视情况

通用生成错误

原始节点错误只写内部日志。

前端只能收到经过清洗的说明。

10. 输出和排版错误

Code

可重试

OUTPUT_RETRIEVAL_FAILED

是

OUTPUT_STORAGE_FAILED

是

OUTPUT_NOT_FOUND

否

COMPOSITION_FAILED

视情况

FONT_UNAVAILABLE

否

PREVIEW_GENERATION_FAILED

是

OUTPUT_VALIDATION_FAILED

视情况

ComfyUI 有图但最终排版失败时，Job 不能进入 Completed。

11. 数据库和内部错误

Code

HTTP

可重试

DATABASE_UNAVAILABLE

503

是

DATABASE_WRITE_FAILED

500

是

STORAGE_UNAVAILABLE

503

是

INTERNAL_ERROR

500

视情况

详细原因只能进入服务端日志。

12. 前端处理约定

引导用户修改

VALIDATION_ERROR
ASSET_TYPE_MISMATCH
ASSET_UNSUPPORTED_FORMAT
COPY_TOO_LONG
MISSING_PRIMARY_ARTIST
RIGHTS_CONFIRMATION_REQUIRED

显示重试

当：

{
  "retryable": true
}

对于已存在的失败 Job，使用 Retry API，而不是直接重复提交原请求。

显示系统繁忙

RATE_LIMITED
JOB_QUEUE_FULL
COMFYUI_UNAVAILABLE

有 retry_after_seconds 时，前端显示建议等待时间。

调试信息

前端日志和错误页面应保留：

request_id
job_id

13. 服务端日志

错误日志至少包含：

timestamp
severity
request_id
project_id
asset_id
job_id
error_code
stage
comfy_prompt_id
internal_cause

不能记录：

Token

密码

完整环境变量

上传文件二进制

无限制的长 Prompt

用户不必要的隐私元数据

14. Problem Type URI

type 应保持稳定：

https://stageposter.example/problems/validation-error
https://stageposter.example/problems/asset-not-found
https://stageposter.example/problems/job-queue-full

不能每次错误生成一个新的 Type URI。

15. 验收标准

所有接口使用统一错误结构。

前端通过稳定 code 判断处理逻辑。

字段错误能定位到具体字段。

错误明确说明是否可重试。

ComfyUI 内部错误经过清洗。

Request ID 和 Job ID 能串联日志。

不泄漏路径、SQL、Token 和 Stack Trace。

Mock 模式可模拟典型错误。
