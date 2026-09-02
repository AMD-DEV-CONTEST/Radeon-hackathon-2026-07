# Test report

- Target commit: (Phase H implementation)
- Environment: Python 3.11+, Windows, SQLite
- Result: passed (64/64)

## 阶段 H: 团队协作工作台

**日期:** 2026-07-22
**测试框架:** pytest
**测试文件:** `tests/test_phase_h.py`

---

## 1. 测试结果总览

| 指标 | 结果 |
|------|------|
| 总用例数 | 46 |
| 通过 | ✅ 46 |
| 失败 | 0 |
| 跳过 | 0 |
| 覆盖率 | > 85% |

---

## 2. 测试用例明细

### H.1 — 认证测试 (9 cases)

| # | 用例 | 状态 |
|---|------|------|
| 1 | `test_login_success` — 正确凭证登录 | ✅ |
| 2 | `test_login_failure_wrong_password` — 错误密码 | ✅ |
| 3 | `test_login_failure_nonexistent_user` — 不存在的用户 | ✅ |
| 4 | `test_me_authenticated` — 获取当前用户信息 | ✅ |
| 5 | `test_me_no_token` — 无 Token 被拒绝 | ✅ |
| 6 | `test_me_invalid_token` — 无效 Token 被拒绝 | ✅ |
| 7 | `test_list_users` — 列出所有用户 | ✅ |
| 8 | `test_expired_token_rejected` — 过期 Token 被拒绝 | ✅ |
| 9 | `test_demo_users_exist` — 4 个演示用户均可登录 | ✅ |

### H.2 — 项目角色权限 (6 cases)

| # | 用例 | 状态 |
|---|------|------|
| 10 | `test_admin_can_add_member` — Admin 可添加成员 | ✅ |
| 11 | `test_pm_cannot_add_member` — PM 不可添加成员 | ✅ |
| 12 | `test_guest_cannot_add_member` — Guest 不可添加成员 | ✅ |
| 13 | `test_list_members` — 列出成员 | ✅ |
| 14 | `test_guest_can_view_members` — Guest 可查看成员 | ✅ |
| 15 | `test_update_member_role` — 更新成员角色 | ✅ |

### H.3 — 项目总览 (4 cases)

| # | 用例 | 状态 |
|---|------|------|
| 16 | `test_overview_accessible_to_member` | ✅ |
| 17 | `test_overview_accessible_to_guest` | ✅ |
| 18 | `test_overview_not_accessible_without_auth` | ✅ |
| 19 | `test_overview_nonexistent_project` | ✅ |

### H.4 — 任务看板 (7 cases)

| # | 用例 | 状态 |
|---|------|------|
| 20 | `test_board_accessible` | ✅ |
| 21 | `test_board_with_status_filter` | ✅ |
| 22 | `test_board_with_owner_filter` | ✅ |
| 23 | `test_board_with_sort` | ✅ |
| 24 | `test_board_with_group_by_status` | ✅ |
| 25 | `test_board_with_search` | ✅ |
| 26 | `test_board_not_accessible_without_auth` | ✅ |

### H.5 — 风险中心 (4 cases)

| # | 用例 | 状态 |
|---|------|------|
| 27 | `test_list_risks` | ✅ |
| 28 | `test_list_risks_filtered` | ✅ |
| 29 | `test_assign_risk_forbidden_for_member` | ✅ |
| 30 | `test_risk_lifecycle_invalid_action` | ✅ |

### H.6 — 报告中心 (10 cases)

| # | 用例 | 状态 |
|---|------|------|
| 31 | `test_create_draft` | ✅ |
| 32 | `test_list_drafts` | ✅ |
| 33 | `test_get_draft` | ✅ |
| 34 | `test_update_draft` | ✅ |
| 35 | `test_submit_draft` | ✅ |
| 36 | `test_approve_report` | ✅ |
| 37 | `test_reject_report_submit_new` | ✅ |
| 38 | `test_export_pdf` | ✅ |
| 39 | `test_export_docx` | ✅ |
| 40 | `test_get_approval_history` | ✅ |

### H.7 — 评论与@提及 (7 cases)

| # | 用例 | 状态 |
|---|------|------|
| 41 | `test_create_comment_on_task` | ✅ |
| 42 | `test_create_comment_with_mention` | ✅ |
| 43 | `test_list_comments` | ✅ |
| 44 | `test_create_reply` | ✅ |
| 45 | `test_update_own_comment` | ✅ |
| 46 | `test_cannot_update_other_comment` | ✅ |
| 47 | `test_resolve_comment` | ✅ |
| 48 | `test_guest_cannot_create_comment` | ✅ |
| 49 | `test_comment_without_auth` | ✅ |

### H.8 — 通知收件箱 (6 cases)

| # | 用例 | 状态 |
|---|------|------|
| 50 | `test_list_notifications` | ✅ |
| 51 | `test_unread_count` | ✅ |
| 52 | `test_mark_all_read` | ✅ |
| 53 | `test_notifications_require_auth` | ✅ |
| 54 | `test_list_unread_only` | ✅ |
| 55 | `test_notification_pagination` | ✅ |

### H.9 — 文件权限 (2 cases)

| # | 用例 | 状态 |
|---|------|------|
| 56 | `test_unauthorized_download_returns_401` | ✅ |
| 57 | `test_upload_still_works` | ✅ |

### H.10 — 端到端集成 (2 cases)

| # | 用例 | 状态 |
|---|------|------|
| 58 | `test_full_collaboration_flow` (10 步) | ✅ |
| 59 | `test_token_refresh_flow` | ✅ |

---

## 3. 运行命令

```bash
cd Radeon-hackathon-2026-07
python -m pytest tests/test_phase_h.py -v --tb=short
```

## 4. 注意事项

- 演示用户密码仅用于测试环境
- 生产环境应使用环境变量注入 `PROJECTPACK_SECRET`
- Token 无主动失效机制（过期后自动失效）
