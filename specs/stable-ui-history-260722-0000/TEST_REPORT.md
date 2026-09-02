# TEST_REPORT.md — 运行历史与详情页

| 字段 | 值 |
|------|-----|
| **Spec ID** | `stable-ui-history-260722-0000` |
| **测试日期** | 2026-07-22 |
| **测试结果** | ✅ **API 层测试全部通过** |

---

## 测试覆盖

UI 层依赖的 API 端点已在以下测试套件中验证：

### test_stage_e_lifecycle.py

| 测试 | 覆盖功能 |
|------|----------|
| `test_progress_endpoint` | GET `/progress` → RunProgress |
| `test_cancel_run` | DELETE `/runs/{id}` → cancel_requested=True |
| `test_list_runs_ordered` | list_runs → 按 created_at 降序 |

### test_stage_e_runner.py

| 测试 | 覆盖功能 |
|------|----------|
| `test_run_progress_fields` | RunProgress 所有字段完整性 |
| `test_step_timer_multiple_steps` | timing_by_step 列表完整性 |
| `test_step_def_covers_all_phases` | StepDef 枚举完整性 |

---

## 验收对照

| 验收标准 | 状态 |
|----------|------|
| Run History 独立标签页 | ✅ workbench.py — `gr.Tab("Run History")` |
| 历史表格字段完整 | ✅ _fmt_run_list 含所有必要列 |
| 查看详情显示摘要+计时 | ✅ _fmt_run_detail 返回 (summary, timing_table) |
| 取消可刷新列表 | ✅ cancel_selected 返回 (_fmt_run_list) |
| 手动刷新历史 | ✅ refresh_history 按钮 |
| 页面加载自动加载 | ✅ demo.load 调用 _fmt_run_list |
| gr.State 跨标签同步 | ✅ history_state.change 自动同步 |
| 全局 /api/runs 端点 | ✅ global_runs.py |
| 空记录友好提示 | ✅ "No runs yet." |
