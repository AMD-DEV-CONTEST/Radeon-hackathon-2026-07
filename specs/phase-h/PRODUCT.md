# Phase H — Team Collaboration Workspace

## 产品规格

**版本:** 1.0
**日期:** 2026-07-22
**状态:** 开发完成

---

## 概述

Phase H 为 ProjectPack 提供完整的团队协作工作台，包括：
- 用户认证与授权（JWT）
- 项目成员管理与基于角色的权限控制
- 项目总览仪表盘
- 任务看板（筛选/排序/分组）
- 风险中心（分配/生命周期）
- 报告中心（草稿/审批/PDF+DOCX导出）
- 多实体评论与 @提及
- 站内通知收件箱

## 验收目标

| 编号 | 目标 | 状态 |
|------|------|------|
| H.1 | 用户认证（登录/Token/个人信息/用户列表） | ✅ |
| H.2 | 四级角色权限（admin/pm/member/guest） | ✅ |
| H.3 | 项目总览聚合视图 | ✅ |
| H.4 | 任务看板（筛选/排序/分组） | ✅ |
| H.5 | 风险分配与生命周期管理 | ✅ |
| H.6 | 报告创建/提交/审批/PDF+DOCX导出 | ✅ |
| H.7 | 评论与 @提及通知 | ✅ |
| H.8 | 通知收件箱 | ✅ |
| H.9 | 文件下载权限 | ✅ |
| H.10 | 端到端集成工作流 | ✅ |

## 技术架构

- **认证**: HMAC-SHA256 自签名 JWT，PBKDF2 密码哈希
- **权限**: FastAPI Depends 注入式权限守卫
- **存储**: SQLite（user_account, project_member, comment, notification, report_draft 等 8 张新表）
- **导出**: ReportLab（PDF）+ python-docx（DOCX）
- **测试**: pytest，64 个测试用例覆盖所有验收目标
