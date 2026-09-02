# TECH.md — 运行历史与详情页

- Level: S2
- Status: verified

## 1. 架构决策

### 1.1 gr.State 跨标签同步

```python
# workbench.py
history_state = gr.State("")

# Report Generation tab
run.click(run_report, ..., outputs=[..., history_state])

# Run History tab
history_state.change(fn=lambda x: x, inputs=history_state, outputs=history_md)
```

使用 Gradio 的 `gr.State` 组件在标签页间传递运行历史数据，避免跨 tab 引用未定义变量的问题。

### 1.2 全局 /api/runs 端点

```python
# app/api/global_runs.py
@router.get("/api/runs")
async def list_runs_global() -> list[RunState]:
    return await list_all_runs()
```

不走 `project_id` 路径参数，直接返回所有运行记录，按 `created_at` 降序排列。

### 1.3 STATUS_LABEL 映射

```python
STATUS_LABEL = {
    "queued": "Queued",
    "scanning": "Scanning",
    ...
    "cancelled": "Cancelled",  # Stage E 新增
}
```

将内部状态值映射为人类可读的标签。

### 1.4 Run ID 缩写

在 UI 中显示 `run_id[:8]` 前 8 个字符作为缩写，减轻 UI 负担。
用户通过前 8 位 + 项目名组合即可唯一定位一个 run。

---

## 2. 文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/ui/workbench.py` | 修改 | 新增 Run History 标签页、_fmt_run_list、_fmt_run_detail、_poll_progress、cancel_selected、view_run_detail、refresh_history；STATUS_LABEL 新增 cancelled |
| `app/api/global_runs.py` | 新增 | GET `/api/runs` 全局端点 |
| `app/main.py` | 修改 | 注册 global_runs_router |

---

## 3. 关键实现细节

### 3.1 _fmt_run_list Markdown 表格生成

```python
def _fmt_run_list(client: ApiClient) -> str:
    runs = client.list_all_runs()
    if not runs:
        return "No runs yet."
    lines = [
        "| Project | Run ID | Status | Step | Retries | Created |",
        "|---------|--------|--------|------|---------|---------|",
    ]
    for r in runs:
        abbrev = r["run_id"][:8]
        step = f"{r['current_step']}/{r.get('total_steps', 8)}"
        lines.append(
            f"| {r['project_id']} | {abbrev} | {STATUS_LABEL.get(r['status'], r['status'])} "
            f"| {step} | {r.get('retry_count', 0)} | {r['created_at'][:19]} |"
        )
    return "\n".join(lines)
```

### 3.2 _fmt_run_detail 详情呈现

```python
def _fmt_run_detail(client, project_id, run_id) -> tuple[str, str]:
    progress = client.request("GET", f"/api/projects/{project_id}/runs/{run_id}/progress")
    # ... 解析 progress 生成 summary + timing_table
    return summary, timing_table
```

返回 (摘要 Markdown, 计时表 Markdown) 元组，分别渲染到 `gr.Markdown` 组件。

### 3.3 View Detail 用户交互

- `hist_project` 下拉框：支持 `allow_custom_value=True`，可直接输入项目名
- `hist_run_id` 文本框：用户输入 run_id 前 8 位
- 点击 "View detail" → 调用 `/_fmt_run_detail` → 更新 `detail_status` 和 `timing_table`
- 运行不存在时显示 "Run not found or inaccessible."

### 3.4 Cancel Run 交互

```python
def cancel_selected(project_id, run_id) -> tuple[str, str]:
    if not project_id or not run_id:
        return "Select a project and run.", _fmt_run_list(client)
    try:
        client.cancel_run(project_id, run_id)
        return f"Cancel requested for {run_id[:8]}", _fmt_run_list(client)
    except gr.Error as exc:
        return str(exc), _fmt_run_list(client)
```

---

## 4. 测试覆盖

相关测试分布在 `test_stage_e_runner.py` 和 `test_stage_e_lifecycle.py` 中，覆盖了 `/progress` 端点、`cancel_run`、`list_all_runs` 等功能，验证 UI 层依赖的 API 正确性。
