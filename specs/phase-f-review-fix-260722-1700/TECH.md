# Tech: 阶段 F 复核修复

- Level: S2
- Status: verified

## 实现

- 为 `app.api.tasks` 路由增加全局项目范围依赖：先调用 `validate_project_id()`，再通过项目元数据验证项目存在，之后才构造 `TaskLifecycleService`。
- `TaskLifecycleService.get_task_history()` 首先调用 `get_task()`，确保任务不存在时抛出 `LookupError`，由 API 映射为 404。
- 新增 API 回归测试，覆盖未注册项目、非法项目 ID 和不存在任务历史。

## 风险与回滚

这是输入边界收紧：此前依赖未注册项目隐式创建任务库的调用会被正确拒绝。回滚对应提交即可恢复旧行为。
