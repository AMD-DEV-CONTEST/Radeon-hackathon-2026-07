# Spec: 运行历史与详情页 (Run History & Detail Pages)

| 字段 | 值 |
|------|-----|
| **Spec ID** | `stable-ui-history-260722-0000` |
| **阶段** | Stage E |
| **状态** | ✅ implemented / verified |
| **创建日期** | 2026-07-22 |
| **对应路线图** | FULL_PRODUCT_ROADMAP.zh-CN.md — 阶段 E |

---

## 1. 概述

本 spec 覆盖阶段 E 的 Gradio 工作台中新增的 **Run History** 标签页，提供运行历史浏览、详情查看、取消运行等功能。

---

## 2. 用户故事

### US-1: 运行历史列表

**作为** 业务用户
**我想要** 在一个统一的页面上查看所有项目的历史运行记录
**以便** 快速了解每个项目的审计进度

**验收标准：**
- 新增 "Run History" 标签页，独立于 "Report Generation"
- 表格列：Project、Run ID（前 8 位缩写）、Status、Step、Retries、Created
- 状态显示为人类友好的标签（如 `Completed`、`Failed`）
- 无记录时显示 "No runs yet."

### US-2: 运行详情

**作为** 业务用户
**我想要** 查看某次运行的完整详情
**以便** 了解每个步骤的耗时和任何错误信息

**验收标准：**
- "View detail" 按钮：选择项目和 run_id 前 8 位后查看
- 显示运行摘要：Status、Step、Percentage、Current File、Retries、Error
- 显示步进计时表：Step、Started、Elapsed (ms)、File、Error
- 无效的 run_id 显示友好提示

### US-3: 取消运行

**作为** 业务用户
**我想要** 从 UI 取消一个正在进行的运行
**以便** 及时终止错误的审计任务

**验收标准：**
- "Cancel run" 按钮（红色 stop 样式）取消选中的 run
- 取消后自动刷新历史列表
- 取消结果以 Markdown 形式反馈

### US-4: 历史刷新

**作为** 业务用户
**我想要** 手动刷新历史记录
**以便** 及时查看最新状态

**验收标准：**
- "Refresh history" 按钮触发重新加载
- 页面加载时自动加载历史
- 项目选择器与主标签页同步

---

## 3. UI 布局

```
┌─────────────────────────────────────────────────────────┐
│ Tab: Run History                                        │
├─────────────────────────────────────────────────────────┤
│ [Refresh history]                                       │
│                                                         │
│ | Project | Run ID | Status | Step | Retries | Created |│
│ |---------|--------|--------|------|---------|---------|│
│ | smoke-a | abc123  | Running| 3/8  | 0       | 2026...││
│                                                         │
│ Project: [dropdown]  Run ID: [textbox]                  │
│ [View detail]  [Cancel run]                             │
│                                                         │
│ ── Detail ──                                            │
│ Status: Running    Step: 3/8 (37%)                      │
│ Current: retrieve  File: report.xlsx                    │
│ Retries: 0         Error: —                             │
│                                                         │
│ ── Step Timing ──                                       │
│ | Step | Started           | Elapsed (ms) | File | Err |│
│ |------|-------------------|-------------|------|-----|│
│ | parse| 2026-07-22T10:00  | 120.5        | a.md | -   |│
└─────────────────────────────────────────────────────────┘
```

---

## 4. 数据流

### 4.1 历史列表加载

```
GET /api/runs → list_all_runs() → _fmt_run_list() → Markdown 表格
```

`_fmt_run_list` 使用全局 `/api/runs` 端点，返回跨项目运行记录，按 `created_at` 降序排列。

### 4.2 运行详情

```
GET /api/projects/{project_id}/runs/{run_id}/progress → _fmt_run_detail() → (summary, timing_table)
```

`_fmt_run_detail` 解析 `RunProgress` 的以下字段：
- 摘要区：`status`, `current_step`, `total_steps`, `percentage`, `current_step_name`, `current_file`, `retry_count`, `error_summary`
- 计时表：`timing_by_step[].step`, `.started_at`, `.elapsed_ms`, `.current_file`, `.error`

### 4.3 取消运行

```
DELETE /api/projects/{project_id}/runs/{run_id} → client.cancel_run() → 刷新历史
```

### 4.4 状态同步

使用 `gr.State` 组件在 "Report Generation" 和 "Run History" 标签页之间共享运行历史数据，确保报告生成完成后历史标签页自动更新。

---

## 5. 代码结构

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/ui/workbench.py` | 修改 | 新增 Run History 标签页、_fmt_run_list、_fmt_run_detail、_poll_progress、STATUS_LABEL 新增 cancelled |
| `app/api/global_runs.py` | 新增 | GET `/api/runs` 全局端点，返回所有项目运行历史 |

### 关键函数

| 函数 | 说明 |
|------|------|
| `_fmt_run_list(client)` | 渲染全局运行历史 Markdown 表格 |
| `_fmt_run_detail(client, project_id, run_id)` | 渲染单个运行的摘要 + 步进计时表 |
| `_poll_progress(client, project_id, run_id, max_wait=180)` | 轮询进度直到完成，每 2s 更新 |
| `cancel_selected(project_id, run_id)` | 取消选中运行并刷新历史 |
| `view_run_detail(project_id, run_id)` | 查看运行详情 |
| `refresh_history()` | 刷新历史列表 |

---

## 6. ApiClient 新增方法

```python
class ApiClient:
    def list_all_runs(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/runs")

    def cancel_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        return self.request("DELETE", f"/api/projects/{project_id}/runs/{run_id}")
```

---

## 7. 验收目标

- [x] Run History 标签页独立显示
- [x] 历史表格包含所有必要字段（Project / Run ID / Status / Step / Retries / Created）
- [x] 查看详情按钮显示运行摘要 + 步进计时表
- [x] 取消按钮可取消运行并刷新列表
- [x] 刷新按钮手动刷新历史
- [x] 页面加载时自动加载历史
- [x] 跨标签页历史状态通过 gr.State 同步
- [x] 所有测试通过（test_stage_e_runner.py + test_stage_e_lifecycle.py 中 UI 相关用例）
