# Spec: 阶段 F 复核修复

| 字段 | 值 |
|---|---|
| Spec ID | `phase-f-review-fix-260722-1700` |
| 变更级别 | S2 |
| 日期 | 2026-07-22 |
| 状态 | implemented / verified |

## 背景

阶段 F 为项目建立独立任务库。复核发现任务 API 在打开 SQLite 前没有验证 URL 中的项目是否有效且已创建；这会使未注册项目生成意外数据库目录。另一个问题是查询不存在任务的历史时，接口返回空数组而不是 404。

## 验收

- [x] 所有任务 API 在处理前验证项目 ID 格式。
- [x] 所有任务 API 仅允许已创建项目访问任务库。
- [x] 未注册项目返回 `PROJECT_NOT_FOUND` / HTTP 404。
- [x] 非法项目 ID 返回 `PROJECT_ID_INVALID` / HTTP 422。
- [x] 不存在任务的历史查询返回 HTTP 404。
