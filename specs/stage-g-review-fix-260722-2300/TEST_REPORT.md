# Test Report: 阶段 G 复核修复

| 项目 | 结果 |
|---|---|
| 阶段 G 测试 | `87 passed` |
| 阶段 G 验收 | `98/98 passed` |
| 全量测试 | `329 passed, 6 skipped` |
| specs 严格校验 | passed |

## 覆盖点

- 使用阶段 F `task` 表创建的逾期任务会生成 `overdue` 风险。
- 不同项目相同相对路径的版本记录不会污染当前项目的变更检测。
- `../outside.md` 被识别为越界路径并拒绝。
