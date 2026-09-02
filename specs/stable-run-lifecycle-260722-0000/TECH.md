# TECH.md — 稳定的运行生命周期

- Level: S2
- Status: verified

## 1. 架构决策

### 1.1 dispatch_background_run 防重复

```python
# app/services/runs.py
async def dispatch_background_run(...):
    current = await get_run(run_id)
    if current.status not in (RunStatus.QUEUED, RunStatus.FAILED, RunStatus.CANCELLED):
        return current  # 已在运行中，不重复提交
    # 标记为 running 后提交 asyncio.Task
```

使用 `RunState.status` 作为防重复锁：只有 QUEUED / FAILED / CANCELLED 状态才允许进入执行队列。

### 1.2 进度回调

```python
# app/agent/runner.py — ControlledRunner.run()
async def progress_callback(step: int, step_name: str, current_file: str | None = None, error: str | None = None):
    state.current_step = step
    state.status = _step_to_status(step)
    state.current_file = current_file
    if error:
        state.error = error
    await _save_state(state)
```

回调在每个管道步骤完成后触发，将进度写入 `RunState` 并持久化。

### 1.3 StepTimer 上下文管理器

```python
# app/observability/audit.py
class StepTimer:
    def __init__(self, timing_list, step, current_file=None): ...
    def __enter__(self) -> StepTiming: ...
    def __exit__(self, exc_type, exc_val, exc_tb): ...
```

- `__enter__`: 记录 `started_at`，创建 `StepTiming` 对象
- `__exit__`: 记录 `finished_at`，计算 `elapsed_ms = (monotonic_now - monotonic_start) * 1000`
- 异常时自动捕获 `error = str(exc_val)` 并追加到 `timing_list`

### 1.4 Cancel 机制

```
DELETE /api/runs/{run_id}
  → runs_service.cancel_run(run_id)
  → 设置 state.cancel_requested = True
  → runner.run() 在关键检查点检测标志
  → 设置 state.status = CANCELLED，提前退出
```

关键检查点：每个步骤开始前、LLM 调用后、文件写入前。

### 1.5 Retry 机制

```
POST /api/runs/{run_id}/retry
  → 验证 retry_count < run_max_retries (否则 429)
  → 验证 status ∈ {FAILED, CANCELLED} (否则 400)
  → 创建新 RunState:
      run_id = new_uuid(), project_id = 原, retry_count = 原 + 1
  → dispatch_background_run(new_state)
  → 返回 202 + new RunState
```

---

## 2. 文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/schemas/models.py` | 修改 | 新增 StepDef, StepTiming, RunProgress；RunState 新增字段；RunStatus 新增 CANCELLED |
| `app/schemas/__init__.py` | 修改 | 导出 Stage E 新增模型 |
| `app/observability/audit.py` | 修改 | 新增 StepTimer 类、validate_run_id 函数 |
| `app/agent/runner.py` | 修改 | ControlledRunner.run() 增加 step_timer、cancel_check、progress_callback |
| `app/services/runs.py` | 修改 | 新增 dispatch_background_run、cancel_run、retry_run；list_runs 按 created_at 排序 |
| `app/api/runs.py` | 修改 | 新增 progress、cancel、retry、list 端点 |
| `app/config.py` | 修改 | 新增 run_max_retries, run_timeout_seconds |
| `tests/test_stage_e_runner.py` | 新增 | 9 个测试用例 |
| `tests/test_stage_e_lifecycle.py` | 新增 | 11 个测试用例 |

---

## 3. 关键实现细节

### 3.1 RunProgress.percentage 计算

```
percentage = min(100, int((current_step / total_steps) * 100))
```

其中 `total_steps` 默认 8（对应 7 个 StepDef + 1 个完成步骤）。

### 3.2 StepTiming.elapsed_ms 精度

使用 `time.monotonic()` 而非 `datetime.now()`，避免系统时间调整带来的偏差。

### 3.3 Cancel 的幂等性

- 对已 `CANCELLED` 的 run 再次 cancel 返回 `{"cancelled": False}`
- 对 `COMPLETED` 的 run 执行 cancel 返回 `{"cancelled": False}`
- 只有 `QUEUED` / `SCANNING` / `INDEXING` / `RETRIEVING` / `EVALUATING` / `DRAFTING` / `WAITING_CONFIRMATION` 状态的 run 可以取消

### 3.4 list_runs 排序

按 `created_at` 降序排列，最新 run 在前。

---

## 4. 测试覆盖

### test_stage_e_runner.py (9 tests)

| 测试 | 说明 |
|------|------|
| `test_step_timer_creates_timing` | StepTimer 正常记录开始/结束/耗时 |
| `test_step_timer_captures_error` | 异常时自动填充 error 字段 |
| `test_step_timer_multiple_steps` | 多个步骤按顺序记录 |
| `test_validate_run_id_valid` | 32 字符 hex 校验通过 |
| `test_validate_run_id_invalid` | 非法格式抛出 ValueError |
| `test_run_progress_fields` | RunProgress 所有字段正确填充 |
| `test_step_def_covers_all_phases` | StepDef 枚举值完整 |
| `test_run_state_cancel_requested_default` | cancel_requested 默认为 False |
| `test_run_state_timing_by_step_default` | timing_by_step 默认为空列表 |

### test_stage_e_lifecycle.py (11 tests)

| 测试 | 说明 |
|------|------|
| `test_dispatch_background_run_sets_status` | 提交后状态转为 running |
| `test_dispatch_background_run_no_double_dispatch` | 已有 running 状态不重复提交 |
| `test_cancel_run` | 取消后 cancel_requested=True |
| `test_cancel_already_cancelled` | 重复取消返回 False |
| `test_cancel_completed_run` | 已完成 run 无法取消 |
| `test_retry_run` | 重试创建新 queued run |
| `test_retry_increments_count` | retry_count 正确递增 |
| `test_retry_exceeds_limit` | 超过上限返回 429 |
| `test_retry_non_failed` | 非 FAILED/CANCELLED 状态返回 400 |
| `test_list_runs_ordered` | 按 created_at 降序排列 |
| `test_progress_endpoint` | /progress 端点返回完整 RunProgress |
