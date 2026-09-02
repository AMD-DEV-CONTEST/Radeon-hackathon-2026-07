"""
Phase H — Team Collaboration Workspace 数据库 DDL

覆盖表：
  - user_account：用户账户
  - project_member：项目成员与角色
  - comment：多实体评论（任务/风险/报告段落）
  - mention：@提及记录
  - notification：站内通知收件箱
  - report_draft：报告草稿版本
  - report_approval：报告审批记录
  - risk_assignment：风险负责人分配
"""

import hashlib
import os
import sqlite3


PHASE_H_DDL: str = """
-- ============================================================
-- Phase H.1 – 认证与授权
-- ============================================================

CREATE TABLE IF NOT EXISTS user_account (
    id              TEXT PRIMARY KEY,
    username        TEXT    NOT NULL UNIQUE,
    display_name    TEXT    NOT NULL,
    password_hash   TEXT    NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_member (
    id              TEXT PRIMARY KEY,
    project_id      TEXT    NOT NULL,
    user_id         TEXT    NOT NULL,
    role            TEXT    NOT NULL CHECK(role IN ('admin','pm','member','guest')),
    joined_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, user_id),
    FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)   REFERENCES user_account(id) ON DELETE CASCADE
);

-- ============================================================
-- Phase H.2 – 评论与 @提及
-- ============================================================

CREATE TABLE IF NOT EXISTS comment (
    id              TEXT PRIMARY KEY,
    project_id      TEXT    NOT NULL,
    entity_type     TEXT    NOT NULL CHECK(entity_type IN ('task','risk','report_section','report')),
    entity_id       TEXT    NOT NULL,
    author_id       TEXT    NOT NULL,
    parent_id       TEXT,
    body            TEXT    NOT NULL,
    is_resolved     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id)  REFERENCES user_account(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id)  REFERENCES comment(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS mention (
    id              TEXT PRIMARY KEY,
    comment_id      TEXT    NOT NULL,
    mentioned_user_id TEXT  NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (comment_id)        REFERENCES comment(id) ON DELETE CASCADE,
    FOREIGN KEY (mentioned_user_id) REFERENCES user_account(id) ON DELETE CASCADE
);

-- ============================================================
-- Phase H.3 – 通知收件箱
-- ============================================================

CREATE TABLE IF NOT EXISTS notification (
    id              TEXT PRIMARY KEY,
    recipient_id    TEXT    NOT NULL,
    kind            TEXT    NOT NULL CHECK(kind IN (
                        'comment_reply','mention','risk_assigned',
                        'report_approved','report_rejected','task_assigned',
                        'project_invite','doc_changed'
                    )),
    title           TEXT    NOT NULL,
    body            TEXT    NOT NULL DEFAULT '',
    link            TEXT    NOT NULL DEFAULT '',
    is_read         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (recipient_id) REFERENCES user_account(id) ON DELETE CASCADE
);

-- ============================================================
-- Phase H.4 – 报告中心
-- ============================================================

CREATE TABLE IF NOT EXISTS report_draft (
    id              TEXT PRIMARY KEY,
    project_id      TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    content_md      TEXT    NOT NULL DEFAULT '',
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT    NOT NULL DEFAULT 'draft'
                        CHECK(status IN ('draft','submitted','approved','rejected','archived')),
    author_id       TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id)  REFERENCES user_account(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS report_approval (
    id              TEXT PRIMARY KEY,
    report_id       TEXT    NOT NULL,
    approver_id     TEXT    NOT NULL,
    decision        TEXT    NOT NULL CHECK(decision IN ('approved','rejected','request_changes')),
    comment         TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (report_id) REFERENCES report_draft(id) ON DELETE CASCADE,
    FOREIGN KEY (approver_id) REFERENCES user_account(id) ON DELETE CASCADE
);

-- ============================================================
-- Phase H.5 – 风险负责人
-- ============================================================

CREATE TABLE IF NOT EXISTS risk_assignment (
    id              TEXT PRIMARY KEY,
    risk_record_id  TEXT    NOT NULL,
    assigned_to     TEXT    NOT NULL,
    assigned_by     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (assigned_to)    REFERENCES user_account(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by)    REFERENCES user_account(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_comment_entity     ON comment(project_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_comment_author     ON comment(author_id);
CREATE INDEX IF NOT EXISTS idx_notification_recip  ON notification(recipient_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notification_created ON notification(created_at);
CREATE INDEX IF NOT EXISTS idx_report_draft_project ON report_draft(project_id, status);
CREATE INDEX IF NOT EXISTS idx_project_member_lookup ON project_member(project_id, user_id);
CREATE INDEX IF NOT EXISTS idx_risk_assignment_risk ON risk_assignment(risk_record_id);
"""


# ============================================================
# 种子数据 — 演示用户
# ============================================================


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    pk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()
    return salt.hex() + ":" + pk


DEMO_USERS = [
    ("u-admin",  "admin",  "管理员",      "admin123"),
    ("u-pm",     "pm",     "项目经理",    "pm123"),
    ("u-member", "member", "团队成员",    "member123"),
    ("u-guest",  "guest",  "只读访客",    "guest123"),
]


def _make_demo_user_inserts() -> list[str]:
    rows: list[str] = []
    for uid, uname, dname, pwd in DEMO_USERS:
        h = _hash_password(pwd)
        rows.append(
            f"INSERT OR IGNORE INTO user_account(id,username,display_name,password_hash) "
            f"VALUES('{uid}','{uname}','{dname}','{h}');"
        )
    return rows


DEMO_USER_DML: str = "\n".join(_make_demo_user_inserts())


def seed_phase_h_tables(db_path: str) -> None:
    """创建 Phase H 表并插入演示用户。"""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(PHASE_H_DDL)
    conn.executescript(DEMO_USER_DML)
    conn.commit()
    conn.close()
