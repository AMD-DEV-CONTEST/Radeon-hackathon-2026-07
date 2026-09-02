# Spec: 稳定的运行生命周期 (Stable Run Lifecycle)

| 字段 | 值 |
|------|-----|
| **Spec ID** | `stable-run-lifecycle-260722-0000` |
| **阶段** | Stage E |
| **状态** | ✅ implemented / verified |
| **创建日期** | 2026-07-22 |
| **对应路线图** | FULL_PRODUCT_ROADMAP.zh-CN.md — 阶段 E |

---

## 1. 概述

本 spec 覆盖阶段 E 中运行生命周期管理的四个核心能力：

1. **后台运行** — run 在创建后异步执行，不阻塞 API 响应
2. **进度轮询** — 前端通过 `/progress` 端点获取实时进度快照
3. **步进计时** — 管道中每个阶段（parse / embed / index / retrieve / rules / model_generate / file_write）记录耗时
4. **取消与重试** — 支持取消正在运行的 run 以及重试失败的 run

---

## 2. 用户故事

### US-1: 后台异步运行

**作为** 业务用户
**我想要** 提交审计任务后立即获得 run_id，任务在后台执行
**以便** 无需等待任务完成就可以继续其他操作

**验收标准：**
- POST `/api/projects/{project_id}/runs` 返回 202 + `RunState(status=queued)`
- run 在 `asyncio.Task` 中执行，不阻塞请求线程
- 同一 run_id 不会重复提交执行（dispatch_background_run 有防重复保护）

### US-2: 进度轮询

**作为** 业务用户
**我想要** 查看一个 run 的实时执行进度
**以便** 了解当前处于哪个步骤、处理哪个文件、已完成百分比

**验收标准：**
- GET `/api/runs/{run_id}/progress` 返回 `RunProgress` 模型
- `RunProgress` 包含：`run_id`, `status`, `current_step`, `current_step_name`, `percentage`, `current_file`, `error_summary`, `timing_by_step`, `retry_count`
- 轮询频率由前端控制，无服务端推送依赖

### US-3: 步进计时

**作为** 开发者/运维
**我想要** 查看每个管道步骤的精确耗时
**以便** 定位性能瓶颈

**验收标准：**
- `StepTimer` 上下文管理器在每个步骤进入时记录 `started_at`
- 退出时自动记录 `finished_at` 和 `elapsed_ms`
- 异常时自动捕获 `error` 字段
- `RunState.timing_by_step` 包含完整的 `list[StepTiming]`

### US-4: 取消运行

**作为** 业务用户
**我想要** 取消一个正在执行的 run
**以便** 在发现参数错误时及时止损

**验收标准：**
- DELETE `/api/runs/{run_id}` 设置 `cancel_requested=True`
- 管道在关键检查点检测该标志并终止
- 取消后状态变为 `CANCELLED`

### US-5: 重试运行

**作为** 业务用户
**我想要** 重试一个失败的 run
**以便** 应对临时性错误（如 LLM 超时）

**验收标准：**
- POST `/api/runs/{run_id}/retry` 创建新的 queued run
- 新 run 的 `retry_count = 原值 + 1`
- 超过 `run_max_retries` 上限时返回 429
- 只有 `FAILED` 或 `CANCELLED` 状态的 run 允许重试

---

## 3. 数据模型

### StepDef (StrEnum)

```
parse | embed | index | retrieve | rules | model_generate | file_write
```

### StepTiming

| 字段 | 类型 | 说明 |
|------|------|------|
| `step` | `StepDef` | 步骤名称 |
| `started_at` | `datetime` | 开始时间 |
| `finished_at` | `datetime \| None` | 结束时间 |
| `elapsed_ms` | `float \| None` | 耗时（毫秒） |
| `current_file` | `str \| None` | 当前处理的文件 |
| `error` | `str \| None` | 错误信息 |

### RunProgress

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | 运行 ID |
| `status` | `RunStatus` | 当前状态 |
| `current_step` | `int` | 当前步骤号 (0-8) |
| `current_step_name` | `str` | 步骤名 |
| `percentage` | `int` | 完成百分比 (0-100) |
| `current_file` | `str \| None` | 当前文件 |
| `error_summary` | `str \| None` | 错误摘要 |
| `timing_by_step` | `list[StepTiming]` | 步进计时列表 |
| `retry_count` | `int` | 重试次数 |

### RunState 新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `timing_by_step` | `list[StepTiming]` | `[]` | 步进计时 |
| `retry_count` | `int` | `0` | 重试次数 |
| `cancel_requested` | `bool` | `False` | 取消标志 |
| `current_file` | `str \| None` | `None` | 当前文件 |
| `total_steps` | `int` | `8` | 总步骤数 |

### RunStatus 新增值

```
CANCELLED = "cancelled"
```

---

## 4. API 端点

| 方法 | 路径 | 说明 | 返回 |
|------|------|------|------|
| `GET` | `/api/projects/{project_id}/runs` | 列出项目的所有 run | `list[RunState]` |
| `GET` | `/api/runs/{run_id}/progress` | 获取 run 实时进度 | `RunProgress` |
| `DELETE` | `/api/runs/{run_id}` | 取消 run | `{"cancelled": True/False}` |
| `POST` | `/api/runs/{run_id}/retry` | 重试 run | `RunState` (新) |

---

## 5. 配置

| 配置项 | 默认值 | 范围 | 说明 |
|--------|--------|------|------|
| `run_max_retries` | `3` | 0-10 | 最大重试次数 |
| `run_timeout_seconds` | `600` | 30-7200 | 运行超时（秒） |

---

## 6. 验收目标

- [x] POST runs 返回 202 + queued 状态，不阻塞
- [x] GET progress 返回包含 timing_by_step 的完整快照
- [x] StepTimer 自动记录每个步骤的开始/结束/耗时
- [x] DELETE run 正确设置 cancel_requested 并终止管道
- [x] POST retry 为 FAILED/CANCELLED run 创建新 queued run
- [x] 超过 retry 上限返回 429
- [x] 同一 run 不重复提交执行
- [x] 所有测试通过（test_stage_e_runner.py + test_stage_e_lifecycle.py, 20 个用例）
