# Technical specification

- Level: S1
- Status: implemented

## 阶段 H: 团队协作工作台

**版本:** 1.0
**日期:** 2026-07-22
**状态:** 开发完成

---

## 1. 架构概览

```
app/
├── api/
│   ├── auth.py          # 认证 API（login, me, users）
│   ├── members.py       # 成员管理 API
│   ├── overview.py      # 项目总览 API
│   ├── task_board.py    # 任务看板 API
│   ├── risks.py         # 风险中心 API
│   ├── reports.py       # 报告中心 API
│   ├── comments.py      # 评论 API
│   ├── notifications.py # 通知 API
│   └── files.py         # 文件权限（已更新）
├── security/
│   ├── auth.py          # JWT 认证服务 + 密码哈希
│   └── permissions.py   # 基于角色的权限守卫（FastAPI Depends）
├── services/
│   ├── membership.py    # 成员管理服务
│   ├── comments.py      # 评论与 @提及服务
│   ├── notifications.py # 通知服务
│   └── report_center.py # 报告中心服务
└── schemas/
    ├── phase_h_sql.py   # Phase H 数据库 DDL + 种子数据
    └── models.py        # Pydantic 模型（已扩展）
```

## 2. 数据库 Schema

### 新增表

| 表名 | 用途 |
|------|------|
| `user_account` | 用户账户（含密码哈希） |
| `project_member` | 项目成员关系与角色 |
| `comment` | 多实体评论 |
| `mention` | @提及记录 |
| `notification` | 站内通知 |
| `report_draft` | 报告草稿 |
| `report_approval` | 审批记录 |
| `risk_assignment` | 风险负责人分配 |

### 数据库路径
- 主库: `{sqlite_path}/projectpack.db`

## 3. 认证机制

### Token 格式
- **算法:** HMAC-SHA256
- **有效期:** 24 小时
- **Secret:** 环境变量 `PROJECTPACK_SECRET`，默认 `projectpack-dev-secret-2026`
- **Token 结构:** `{header.b64}.{payload.b64}.{signature}`

### 密码存储
- **算法:** PBKDF2-HMAC-SHA256
- **迭代次数:** 100,000
- **盐长度:** 16 bytes
- **格式:** `{salt_hex}:{hash_hex}`

## 4. 权限模型

### 角色层级
```
admin (4) > pm (3) > member (2) > guest (1)
```

### 权限守卫
```python
# FastAPI Depends 函数
require_project_role("member")  # 要求 member+
require_project_role("pm")      # 要求 pm+
require_project_role("admin")   # 要求 admin
require_any_project_role("pm", "admin")  # 要求 pm 或 admin
```

### 实现原理
1. 从 `Authorization: Bearer {token}` 提取用户
2. 查询 `project_member` 表获取用户在该项目的角色
3. 比较角色层级，低于要求则返回 403

## 5. API 端点

### Auth
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| POST | `/auth/login` | 无 | 用户登录 |
| GET | `/auth/me` | 认证 | 当前用户信息 |
| GET | `/auth/users` | 认证 | 用户列表 |

### Members
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/projects/{pid}/members` | guest+ | 成员列表 |
| POST | `/projects/{pid}/members` | admin | 添加成员 |
| PUT | `/projects/{pid}/members/{uid}` | admin | 更新角色 |
| DELETE | `/projects/{pid}/members/{uid}` | admin | 移除成员 |

### Overview
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/projects/{pid}/overview` | guest+ | 项目总览 |

### Task Board
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/projects/{pid}/board/tasks` | guest+ | 任务看板(筛选/排序/分组) |

### Risks
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/projects/{pid}/risks` | guest+ | 风险列表 |
| PUT | `/projects/{pid}/risks/{rid}/assign` | pm+ | 分配负责人 |
| PUT | `/projects/{pid}/risks/{rid}/lifecycle` | pm+ | 生命周期变更 |

### Reports
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/projects/{pid}/reports` | guest+ | 报告列表 |
| POST | `/projects/{pid}/reports` | member+ | 创建草稿 |
| GET/PUT | `/projects/{pid}/reports/{did}` | guest+ | 获取/编辑草稿 |
| POST | `/projects/{pid}/reports/{did}/submit` | member+ | 提交审批 |
| POST | `/projects/{pid}/reports/{did}/approve` | pm+ | 审批 |
| GET | `/projects/{pid}/reports/{did}/export/pdf` | member+ | 导出PDF |
| GET | `/projects/{pid}/reports/{did}/export/docx` | member+ | 导出DOCX |
| GET | `/projects/{pid}/reports/{did}/approvals` | guest+ | 审批历史 |

### Comments
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/projects/{pid}/comments` | guest+ | 评论列表 |
| POST | `/projects/{pid}/comments` | member+ | 发表评论 |
| PUT | `/projects/{pid}/comments/{cid}` | 作者 | 编辑评论 |
| DELETE | `/projects/{pid}/comments/{cid}` | 作者或pm+ | 删除评论 |
| POST | `/projects/{pid}/comments/{cid}/resolve` | pm+ | 标记已解决 |

### Notifications
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/notifications` | 认证 | 通知列表 |
| GET | `/notifications/unread-count` | 认证 | 未读计数 |
| PUT | `/notifications/read-all` | 认证 | 全部已读 |
| PUT | `/notifications/{nid}/read` | 认证 | 单个已读 |

### Files (updated)
| Method | Path | 权限 | 说明 |
|--------|------|------|------|
| GET | `/api/projects/{pid}/files/download/{path}` | member+ | 下载文件 |

## 6. 依赖

### 新增运行时依赖
- `reportlab>=4,<6` — PDF 报告导出
- `python-docx>=1.2,<2` — DOCX 报告导出（已存在）

### 无需新增依赖
- 认证使用纯 Python 标准库（`hashlib`, `hmac`, `base64`）
- 无外部 JWT 库依赖

## 7. 错误码

新增 Phase H 错误码（`app/observability/error_codes.py`）:

| 错误码 | HTTP | 中文消息 |
|--------|------|---------|
| `AUTH_INVALID_CREDENTIALS` | 401 | 用户名或密码错误 |
| `AUTH_TOKEN_EXPIRED` | 401 | 认证已过期，请重新登录 |
| `AUTH_TOKEN_MISSING` | 401 | 缺少认证信息，请先登录 |
| `AUTH_TOKEN_INVALID` | 401 | 认证信息无效 |
| `ACCESS_DENIED` | 403 | 您没有权限执行此操作 |
| `ACCESS_DENIED_PROJECT` | 403 | 您没有访问此项目的权限 |
| `ACCESS_DENIED_FILE_DOWNLOAD` | 403 | 您没有下载该项目文件的权限 |
| `USER_NOT_FOUND` | 404 | 用户不存在 |
| `MEMBER_ALREADY_EXISTS` | 409 | 用户已是该项目成员 |
| `COMMENT_NOT_FOUND` | 404 | 评论不存在 |
| `NOTIFICATION_NOT_FOUND` | 404 | 通知不存在 |
| `REPORT_DRAFT_NOT_FOUND` | 404 | 报告草稿不存在 |
| `REPORT_EXPORT_FAILED` | 500 | 报告导出失败 |
| `RISK_ASSIGNMENT_FAILED` | 500 | 风险分配失败 |
| `RISK_LIFECYCLE_INVALID` | 400 | 无效的风险生命周期变更 |

## 8. 测试覆盖

测试文件: `tests/test_phase_h.py`
- 10 个 Test Class
- 46 个测试用例
- 覆盖所有 H.1–H.10 验收目标
- 端到端集成测试 10 步完整流程

## 9. 数据流

```
用户登录 → jwt token
  → 请求带 Bearer token
    → get_current_user() 验证 token
      → require_project_role("member") 检查成员表
        → 200 OK / 403 Forbidden / 401 Unauthorized
```
