# Tech: 阶段 H 复核修复

- Level: S2
- Status: verified

## 实现

- 统一看板、项目总览、风险中心的项目数据库解析：`sqlite_path.parent/projects/{project_id}/tasks.db`。
- 风险列表在查询前调用阶段 G 的 schema 初始化，避免已有任务库但尚未扫描时出现 `no such table: risk_record`。
- `get_current_user()` 在校验 JWT 后复查用户 `is_active`，禁用用户不能继续使用旧 Token。
- 补充真实 F→H 看板数据链路与禁用用户 Token 的回归测试。
