# Tech: 阶段 G 复核修复

- Level: S2
- Status: verified

## 实现

- `RiskScanner` 和 `ChangeImpactAnalyzer` 通过 SQLite 元数据确定任务表名，优先使用 `task`，必要时回退至 `tasks`。
- `detect_file_changes()` 增加可选 `project_id`，数据库模式下仅加载该项目的当前文档版本。
- 所有被检测的相对文件路径先解析并验证仍在项目根目录内；越界路径抛出 `ValueError`。
- 补充阶段 F 与阶段 G 的真实衔接测试、项目版本隔离测试与路径越界测试。
