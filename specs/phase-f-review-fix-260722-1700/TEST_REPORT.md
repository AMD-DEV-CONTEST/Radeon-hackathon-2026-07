# Test Report: 阶段 F 复核修复

| 项目 | 结果 |
|---|---|
| 阶段 F 测试 | `41 passed` |
| 全量测试 | `242 passed, 6 skipped` |
| 阶段 F 验收脚本 | passed |
| specs 严格校验 | passed |

## 覆盖点

- `/api/projects/missing-project/tasks` 返回 404 和 `PROJECT_NOT_FOUND`。
- `/api/projects/INVALID/tasks` 返回 422 和 `PROJECT_ID_INVALID`。
- `/api/projects/{project_id}/tasks/{missing_task}/history` 返回 404。
- SQLite 生命周期、人工确认、导入去重和报告任务库优先级回归通过。
