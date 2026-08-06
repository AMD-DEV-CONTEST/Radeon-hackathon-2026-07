"""
Agent 群聊系统 - SQLite 存储层

镜像 collaboration_system/store.py 的设计模式：
- 每次操作独立连接（WAL + busy timeout）
- JSON 列序列化（json_dumps/json_loads）
- dict 视图而非 Pydantic 实例
- 严格的外键和唯一约束
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from agent_factory.paths import factory_artifact_path, resolve_project_path
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store
from agent_factory.workspace_system import WorkspaceStore

# ===== 常量 =====

SQLITE_BUSY_TIMEOUT_MS = 10000

GROUP_STATUSES = {"draft", "active", "archived"}
MEMBER_RUN_STATUSES = {"queued", "running", "awaiting_approval", "completed", "failed", "cancelled"}
MESSAGE_SPEAKER_TYPES = {"user", "agent", "system"}
MESSAGE_KINDS = {
    "user_message",
    "agent_response",
    "tool_call",
    "tool_result",
    "approval_request",
    "system_notice",
    "progress",
}
CONTEXT_VERSION_KINDS = {"snapshot", "delta"}
WORKSPACE_COMMIT_STATUSES = {"prepared", "files_committed", "context_committed", "completed", "conflict", "aborted"}


# ===== 异常 =====


class AgentGroupStoreError(RuntimeError):
    """存储层错误"""


# ===== Store 类 =====


class AgentGroupStore:
    """Agent 群聊 SQLite 存储"""

    def __init__(self, path: str | Path | None = None):
        self.path = resolve_agent_group_store_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        initialize_sqlite_store(
            self.path,
            self._ensure_schema,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            wal=True,
        )

    # ===== 连接管理 =====

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """每次操作独立连接，自动提交/关闭"""
        conn = connect_sqlite(
            self.path,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            foreign_keys=True,
        )
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


    # ===== Schema 创建与迁移 =====

    def _ensure_schema(self) -> None:
        """确保所有表结构存在"""
        with self._connect() as conn:
            conn.execute("begin immediate")
            # 1. 群聊会话表
            conn.execute("""
                create table if not exists agent_group_sessions (
                    group_id text primary key,
                    title text not null,
                    workspace_id text not null,
                    status text not null,
                    created_at text not null,
                    updated_at text not null,
                    archived_at text
                )
            """)

            # 2. 群聊成员表（唯一约束：group_id + package_id）
            conn.execute("""
                create table if not exists agent_group_members (
                    group_id text not null,
                    package_id text not null,
                    package_session_id text not null,
                    consumed_context_version integer not null default 0,
                    joined_at text not null,
                    primary key (group_id, package_id),
                    foreign key (group_id) references agent_group_sessions(group_id)
                        on delete cascade
                )
            """)

            # 3. 群聊消息表
            conn.execute("""
                create table if not exists agent_group_messages (
                    message_id text primary key,
                    group_id text not null,
                    speaker_type text not null,
                    speaker_package_id text,
                    message_kind text not null,
                    content text not null,
                    context_version integer,
                    reply_to_message_id text,
                    context_references_json text not null default '[]',
                    group_run_id text,
                    event_ref text,
                    created_at text not null,
                    foreign key (group_id) references agent_group_sessions(group_id)
                        on delete cascade
                )
            """)
            # 消息幂等索引（防止重复事件投影）
            conn.execute("""
                create unique index if not exists idx_agent_group_messages_event_ref
                on agent_group_messages(group_id, event_ref)
                where event_ref is not null
            """)

            # 4. 成员运行记录表
            conn.execute("""
                create table if not exists agent_group_member_runs (
                    group_run_id text primary key,
                    group_id text not null,
                    message_id text not null,
                    speaker_package_id text not null,
                    package_session_id text not null,
                    status text not null,
                    base_context_version integer not null,
                    base_workspace_revision integer not null,
                    request_id text,
                    response_message_id text,
                    created_at text not null,
                    updated_at text not null,
                    foreign key (group_id) references agent_group_sessions(group_id)
                        on delete cascade,
                    foreign key (message_id) references agent_group_messages(message_id)
                        on delete cascade
                )
            """)
            _migrate_session_identity_columns(conn)

            # 5. 共享上下文版本表
            conn.execute("""
                create table if not exists agent_group_context_versions (
                    group_id text not null,
                    version integer not null,
                    kind text not null,
                    from_version integer,
                    content text not null,
                    token_count integer not null,
                    created_at text not null,
                    primary key (group_id, version),
                    foreign key (group_id) references agent_group_sessions(group_id)
                        on delete cascade
                )
            """)

            # 6. 工作区版本表
            conn.execute("""
                create table if not exists agent_group_workspace_revisions (
                    group_id text not null,
                    revision integer not null,
                    parent_revision integer,
                    file_manifest_json text not null,
                    created_at text not null,
                    primary key (group_id, revision),
                    foreign key (group_id) references agent_group_sessions(group_id)
                        on delete cascade
                )
            """)

            # 7. 工作区提交事务表
            conn.execute("""
                create table if not exists agent_group_workspace_commits (
                    commit_id text primary key,
                    group_id text not null,
                    group_run_id text not null,
                    source_revision integer not null,
                    target_revision integer,
                    status text not null,
                    conflict_files_json text,
                    created_at text not null,
                    updated_at text not null,
                    foreign key (group_id) references agent_group_sessions(group_id)
                        on delete cascade,
                    foreign key (group_run_id) references agent_group_member_runs(group_run_id)
                        on delete cascade
                )
            """)

            # 8. 成员会话索引（session_id 唯一）
            conn.execute("drop index if exists idx_agent_group_members_conversation")
            conn.execute("""
                create unique index if not exists idx_agent_group_members_session
                on agent_group_members(package_session_id)
            """)
            _ensure_column(conn, "agent_group_members", "consumed_context_version", "integer not null default 0")
            _ensure_column(conn, "agent_group_messages", "context_version", "integer")
            _ensure_column(conn, "agent_group_messages", "reply_to_message_id", "text")
            _ensure_column(conn, "agent_group_messages", "context_references_json", "text not null default '[]'")
            _ensure_column(conn, "agent_group_member_runs", "request_id", "text")
            _ensure_column(conn, "agent_group_sessions", "workspace_id", "text not null default ''")


    # ===== 群聊会话 CRUD =====

    def list_groups(self) -> list[dict[str, Any]]:
        """List group snapshots; frontend state never fabricates absent members or runs."""
        with self._connect() as conn:
            rows = conn.execute("""
                select group_id, title, workspace_id, status, created_at, updated_at, archived_at
                from agent_group_sessions
                order by updated_at desc
            """).fetchall()
            group_ids = [str(row["group_id"]) for row in rows]
        return [self.get_group(group_id) for group_id in group_ids]

    def create_group(self, title: str, workspace_id: str) -> dict[str, Any]:
        """创建新群聊"""
        if not title.strip():
            raise AgentGroupStoreError("title must not be empty")
        normalized_workspace_id = str(workspace_id or "").strip()
        if not normalized_workspace_id:
            raise AgentGroupStoreError("workspace_id must not be empty")

        group_id = uuid4().hex
        now = utc_now_text()

        with self._connect() as conn:
            # 插入群聊会话
            conn.execute("""
                insert into agent_group_sessions (
                    group_id, title, workspace_id, status, created_at, updated_at, archived_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
            """, (group_id, title.strip(), normalized_workspace_id, "draft", now, now, None))

            # 初始化上下文版本 0（空快照）
            conn.execute("""
                insert into agent_group_context_versions
                (group_id, version, kind, from_version, content, token_count, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
            """, (group_id, 0, "snapshot", None, "", 0, now))

            # 初始化工作区版本 0（空 manifest）
            conn.execute("""
                insert into agent_group_workspace_revisions
                (group_id, revision, parent_revision, file_manifest_json, created_at)
                values (?, ?, ?, ?, ?)
            """, (group_id, 0, None, json_dumps({}), now))

        self.group_workspace_revision_root(group_id, 0).mkdir(parents=True, exist_ok=True)

        return self.get_group(group_id)

    def get_group(self, group_id: str) -> dict[str, Any]:
        """获取群聊完整视图（含成员、消息、runs）"""
        with self._connect() as conn:
            # 主记录
            session_row = conn.execute("""
                select group_id, title, workspace_id, status, created_at, updated_at, archived_at
                from agent_group_sessions
                where group_id = ?
            """, (group_id,)).fetchone()

            if session_row is None:
                raise AgentGroupStoreError(f"group not found: {group_id}")

            session = self._session_view(session_row)
            if not str(session.get("workspace_id") or "").strip():
                session["workspace_id"] = self._migrate_legacy_group_workspace(
                    group_id,
                    str(session.get("title") or ""),
                )

            # 成员
            member_rows = conn.execute("""
                select group_id, package_id, package_session_id, consumed_context_version, joined_at
                from agent_group_members
                where group_id = ?
                order by joined_at
            """, (group_id,)).fetchall()
            session["members"] = [self._member_view(r) for r in member_rows]

            # 消息（最近 200 条）
            message_rows = conn.execute("""
                select message_id, group_id, speaker_type, speaker_package_id, message_kind,
                       content, reply_to_message_id, context_references_json, group_run_id, event_ref, created_at
                from agent_group_messages
                where group_id = ?
                order by created_at desc
                limit 200
            """, (group_id,)).fetchall()
            session["messages"] = [self._message_view(r) for r in reversed(message_rows)]

            # 运行记录（最近 50 条）
            run_rows = conn.execute("""
                select group_run_id, group_id, message_id, speaker_package_id, package_session_id,
                       status, base_context_version, base_workspace_revision, request_id, response_message_id,
                       created_at, updated_at
                from agent_group_member_runs
                where group_id = ?
                order by created_at desc
                limit 50
            """, (group_id,)).fetchall()
            session["runs"] = [self._run_view(r) for r in reversed(run_rows)]

            # 当前版本号
            session["current_context_version"] = self._current_context_version(conn, group_id)
            session["current_workspace_revision"] = self._current_workspace_revision(conn, group_id)

            # 工作区资源
            session["workspace_resource"] = {
                "resource_mode": "agent_group",
                "group_id": group_id,
                "workspace_id": session["workspace_id"],
                "workdir": str(self.group_workdir(group_id)),
            }

        return session

    def update_group(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新群聊元数据"""
        now = utc_now_text()
        updates = []
        params = []

        if "title" in payload:
            title = str(payload["title"]).strip()
            if not title:
                raise AgentGroupStoreError("title must not be empty")
            updates.append("title = ?")
            params.append(title)

        if "status" in payload:
            status = str(payload["status"])
            if status not in GROUP_STATUSES:
                raise AgentGroupStoreError(f"invalid status: {status}")
            updates.append("status = ?")
            params.append(status)
            if status == "archived":
                updates.append("archived_at = ?")
                params.append(now)

        if not updates:
            return self.get_group(group_id)

        updates.append("updated_at = ?")
        params.append(now)
        params.append(group_id)

        with self._connect() as conn:
            conn.execute(f"""
                update agent_group_sessions
                set {', '.join(updates)}
                where group_id = ?
            """, params)

        return self.get_group(group_id)

    def delete_group(self, group_id: str) -> dict[str, Any]:
        """删除群聊（级联删除所有关联数据）"""
        result = {"deleted": False, "group_id": group_id, "member_sessions": []}

        with self._connect() as conn:
            # 收集成员 session_id 列表（供调用方清理 runtime sessions）
            member_rows = conn.execute("""
                select package_id, package_session_id from agent_group_members where group_id = ?
            """, (group_id,)).fetchall()
            result["member_sessions"] = [dict(r) for r in member_rows]

            # 删除群聊（外键级联删除其他表）
            cursor = conn.execute("delete from agent_group_sessions where group_id = ?", (group_id,))
            result["deleted"] = cursor.rowcount > 0

        return result

    # ===== 成员管理 =====

    def add_member(self, group_id: str, package_id: str, package_session_id: str) -> dict[str, Any]:
        """添加成员到群聊"""
        now = utc_now_text()
        package_session_id = str(package_session_id or "").strip()
        if not package_session_id:
            raise AgentGroupStoreError("package_session_id must be a real runtime session id")

        with self._connect() as conn:
            try:
                conn.execute("""
                    insert into agent_group_members (group_id, package_id, package_session_id, consumed_context_version, joined_at)
                    values (?, ?, ?, ?, ?)
                """, (group_id, package_id, package_session_id, 0, now))

                conn.execute("""
                    update agent_group_sessions set updated_at = ? where group_id = ?
                """, (now, group_id))
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e):
                    raise AgentGroupStoreError(f"member already exists: {package_id}")
                raise AgentGroupStoreError(f"failed to add member: {e}")

        return self.get_group(group_id)

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select message_id, group_id, speaker_type, speaker_package_id, message_kind,
                       content, reply_to_message_id, context_references_json, group_run_id, event_ref, created_at
                from agent_group_messages where message_id = ?
                """,
                (message_id,),
            ).fetchone()
        return self._message_view(row) if row is not None else None

    def latest_target_package_ids(self, group_id: str) -> list[str]:
        """Return the recipients from the latest public user turn that actually addressed members."""
        with self._connect() as conn:
            source = conn.execute(
                """
                select m.message_id
                from agent_group_messages m
                where m.group_id = ? and m.speaker_type = 'user'
                  and exists (
                    select 1 from agent_group_member_runs r where r.message_id = m.message_id
                  )
                order by m.created_at desc
                limit 1
                """,
                (group_id,),
            ).fetchone()
            if source is None:
                return []
            rows = conn.execute(
                """
                select speaker_package_id
                from agent_group_member_runs
                where message_id = ?
                order by created_at asc
                """,
                (source["message_id"],),
            ).fetchall()
        return [str(row["speaker_package_id"]) for row in rows if str(row["speaker_package_id"] or "").strip()]

    def remove_member(self, group_id: str, package_id: str) -> dict[str, Any]:
        """移除成员（返回其 session_id 供清理）"""
        now = utc_now_text()

        with self._connect() as conn:
            row = conn.execute("""
                select package_session_id from agent_group_members
                where group_id = ? and package_id = ?
            """, (group_id, package_id)).fetchone()

            if row is None:
                raise AgentGroupStoreError(f"member not found: {package_id}")

            session_id = row["package_session_id"]

            conn.execute("""
                delete from agent_group_members where group_id = ? and package_id = ?
            """, (group_id, package_id))

            conn.execute("""
                update agent_group_sessions set updated_at = ? where group_id = ?
            """, (now, group_id))

        result = self.get_group(group_id)
        result["removed_session_id"] = session_id
        return result


    # ===== 消息管理 =====

    def add_user_message(
        self,
        group_id: str,
        content: str,
        client_message_id: str,
        target_package_ids: list[str],
        reply_to_message_id: str | None = None,
        context_references: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """添加用户消息（幂等，基于 client_message_id）"""
        if not content.strip():
            raise AgentGroupStoreError("message content must not be empty")

        now = utc_now_text()

        with self._connect() as conn:
            # 幂等检查：是否已存在相同 client_message_id 的消息
            existing = conn.execute("""
                select message_id from agent_group_messages
                where group_id = ? and event_ref = ?
            """, (group_id, f"user:{client_message_id}")).fetchone()

            if existing:
                # 已存在，返回现有群聊状态
                return self.get_group(group_id)

            # 插入用户消息
            message_id = uuid4().hex
            conn.execute("""
                insert into agent_group_messages
                (message_id, group_id, speaker_type, speaker_package_id, message_kind, content,
                 reply_to_message_id, context_references_json, group_run_id, event_ref, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, group_id, "user", None, "user_message", content.strip(),
                  reply_to_message_id, json_dumps(context_references or []), None, f"user:{client_message_id}", now))

            context_version = self._append_context_delta_conn(
                conn,
                group_id=group_id,
                source_message_id=message_id,
                speaker="user",
                content=content.strip(),
                created_at=now,
            )
            conn.execute(
                "update agent_group_messages set context_version = ? where message_id = ?",
                (context_version, message_id),
            )

            # 为每个目标 Agent 创建 run 记录（状态 queued）
            current_context_version = self._current_context_version(conn, group_id)
            current_workspace_revision = self._current_workspace_revision(conn, group_id)

            for package_id in target_package_ids:
                # 查找成员的 session_id
                member_row = conn.execute("""
                    select package_session_id from agent_group_members
                    where group_id = ? and package_id = ?
                """, (group_id, package_id)).fetchone()

                if member_row is None:
                    # 成员不存在，跳过（前端应该过滤，但后端容错）
                    continue

                package_session_id = member_row["package_session_id"]
                group_run_id = uuid4().hex

                conn.execute("""
                    insert into agent_group_member_runs
                    (group_run_id, group_id, message_id, speaker_package_id, package_session_id,
                     status, base_context_version, base_workspace_revision, request_id, response_message_id,
                     created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (group_run_id, group_id, message_id, package_id, package_session_id,
                      "queued", current_context_version, current_workspace_revision, None, None, now, now))

            # 更新群聊时间戳
            conn.execute("""
                update agent_group_sessions set updated_at = ?, status = 'active'
                where group_id = ?
            """, (now, group_id))

        return self.get_group(group_id)

    def record_agent_message(
        self,
        group_id: str,
        group_run_id: str,
        message_kind: str,
        content: str,
        event_ref: str | None = None,
    ) -> str | None:
        """记录 Agent 消息（工具调用、进度、响应等，幂等）"""
        if message_kind not in MESSAGE_KINDS:
            raise AgentGroupStoreError(f"invalid message_kind: {message_kind}")

        now = utc_now_text()

        with self._connect() as conn:
            # 幂等检查（基于 event_ref）
            if event_ref:
                existing = conn.execute("""
                    select message_id from agent_group_messages
                    where group_id = ? and event_ref = ?
                """, (group_id, event_ref)).fetchone()

                if existing:
                    return str(existing["message_id"])

            # 查找 run 的 speaker
            run_row = conn.execute("""
                select speaker_package_id from agent_group_member_runs where group_run_id = ?
            """, (group_run_id,)).fetchone()

            if run_row is None:
                return None

            speaker_package_id = run_row["speaker_package_id"]
            message_id = uuid4().hex

            conn.execute("""
                insert into agent_group_messages
                (message_id, group_id, speaker_type, speaker_package_id, message_kind, content,
                 group_run_id, event_ref, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, group_id, "agent", speaker_package_id, message_kind, content,
                  group_run_id, event_ref, now))
            if message_kind == "agent_response" and content.strip():
                context_version = self._append_context_delta_conn(
                    conn,
                    group_id=group_id,
                    source_message_id=message_id,
                    speaker=speaker_package_id,
                    content=content.strip(),
                    created_at=now,
                )
                conn.execute(
                    "update agent_group_messages set context_version = ? where message_id = ?",
                    (context_version, message_id),
                )
            return message_id

    # ===== Member Run 管理 =====

    def get_run(self, group_run_id: str) -> dict[str, Any] | None:
        """获取单个 run 记录"""
        with self._connect() as conn:
            row = conn.execute("""
                select group_run_id, group_id, message_id, speaker_package_id, package_session_id,
                       status, base_context_version, base_workspace_revision, request_id, response_message_id,
                       created_at, updated_at
                from agent_group_member_runs
                where group_run_id = ?
            """, (group_run_id,)).fetchone()

            if row is None:
                return None

            return self._run_view(row)

    def update_run(self, group_run_id: str, payload: dict[str, Any]) -> None:
        """更新 run 状态"""
        now = utc_now_text()
        updates = []
        params = []

        if "status" in payload:
            status = str(payload["status"])
            if status not in MEMBER_RUN_STATUSES:
                raise AgentGroupStoreError(f"invalid run status: {status}")
            updates.append("status = ?")
            params.append(status)

        if "response_message_id" in payload:
            updates.append("response_message_id = ?")
            params.append(payload["response_message_id"])

        if "request_id" in payload:
            updates.append("request_id = ?")
            params.append(payload["request_id"])

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(now)
        params.append(group_run_id)

        with self._connect() as conn:
            conn.execute(f"""
                update agent_group_member_runs
                set {', '.join(updates)}
                where group_run_id = ?
            """, params)

    def list_queued_runs(self, group_id: str) -> list[dict[str, Any]]:
        """列出所有 queued 状态的 runs"""
        with self._connect() as conn:
            rows = conn.execute("""
                select group_run_id, group_id, message_id, speaker_package_id, package_session_id,
                       status, base_context_version, base_workspace_revision, request_id, response_message_id,
                       created_at, updated_at
                from agent_group_member_runs
                where group_id = ? and status = 'queued'
                order by created_at
            """, (group_id,)).fetchall()

            return [self._run_view(r) for r in rows]

    def cancel_run(self, group_run_id: str) -> None:
        """取消运行"""
        self.update_run(group_run_id, {"status": "cancelled"})

    def requeue_run(self, group_run_id: str) -> None:
        run = self.get_run(group_run_id)
        if run is None:
            raise AgentGroupStoreError("group run not found")
        if str(run.get("status") or "") not in {"failed", "cancelled"}:
            raise AgentGroupStoreError("only failed or cancelled group runs can be retried")
        self.update_run(group_run_id, {"status": "queued", "request_id": None})


    # ===== 上下文版本管理 =====

    def get_context_version(self, group_id: str, version: int) -> dict[str, Any] | None:
        """获取指定版本的上下文"""
        with self._connect() as conn:
            row = conn.execute("""
                select group_id, version, kind, from_version, content, token_count, created_at
                from agent_group_context_versions
                where group_id = ? and version = ?
            """, (group_id, version)).fetchone()

            if row is None:
                return None

            return self._context_version_view(row)

    def context_versions_after(self, group_id: str, version: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select group_id, version, kind, from_version, content, token_count, created_at
                from agent_group_context_versions
                where group_id = ? and version > ?
                order by version asc
                """,
                (group_id, version),
            ).fetchall()
        return [self._context_version_view(row) for row in rows]

    def member_consumed_context_version(self, group_id: str, package_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                select consumed_context_version from agent_group_members
                where group_id = ? and package_id = ?
                """,
                (group_id, package_id),
            ).fetchone()
        if row is None:
            raise AgentGroupStoreError(f"member not found: {package_id}")
        return int(row["consumed_context_version"] or 0)

    def mark_member_context_consumed(self, group_id: str, package_id: str, version: int) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                update agent_group_members
                set consumed_context_version = max(consumed_context_version, ?)
                where group_id = ? and package_id = ?
                """,
                (version, group_id, package_id),
            )
            if cursor.rowcount != 1:
                raise AgentGroupStoreError(f"member not found: {package_id}")

    def add_context_version(
        self, group_id: str, kind: str, content: str, token_count: int, from_version: int | None = None
    ) -> int:
        """添加新上下文版本（返回版本号）"""
        if kind not in CONTEXT_VERSION_KINDS:
            raise AgentGroupStoreError(f"invalid context version kind: {kind}")

        now = utc_now_text()

        with self._connect() as conn:
            current_version = self._current_context_version(conn, group_id)
            new_version = current_version + 1

            conn.execute("""
                insert into agent_group_context_versions
                (group_id, version, kind, from_version, content, token_count, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
            """, (group_id, new_version, kind, from_version, content, token_count, now))

        return new_version

    def _current_context_version(self, conn: sqlite3.Connection, group_id: str) -> int:
        """获取当前最大版本号"""
        row = conn.execute("""
            select max(version) as max_version from agent_group_context_versions where group_id = ?
        """, (group_id,)).fetchone()
        return row["max_version"] if row and row["max_version"] is not None else 0

    def _append_context_delta_conn(
        self,
        conn: sqlite3.Connection,
        *,
        group_id: str,
        source_message_id: str,
        speaker: str,
        content: str,
        created_at: str,
    ) -> int:
        current_version = self._current_context_version(conn, group_id)
        version = current_version + 1
        delta = json_dumps(
            {
                "source_message_id": source_message_id,
                "speaker": speaker,
                "content": content,
            }
        )
        conn.execute(
            """
            insert into agent_group_context_versions
            (group_id, version, kind, from_version, content, token_count, created_at)
            values (?, ?, 'delta', ?, ?, ?, ?)
            """,
            (group_id, version, current_version, delta, len(content), created_at),
        )
        return version

    # ===== 工作区版本管理 =====

    def get_workspace_revision(self, group_id: str, revision: int) -> dict[str, Any] | None:
        """获取指定 revision"""
        with self._connect() as conn:
            row = conn.execute("""
                select group_id, revision, parent_revision, file_manifest_json, created_at
                from agent_group_workspace_revisions
                where group_id = ? and revision = ?
            """, (group_id, revision)).fetchone()

            if row is None:
                return None

            return self._workspace_revision_view(row)

    def add_workspace_revision(
        self, group_id: str, file_manifest: dict[str, str], parent_revision: int | None
    ) -> int:
        """添加新 workspace revision（返回 revision 号）"""
        now = utc_now_text()

        with self._connect() as conn:
            current_revision = self._current_workspace_revision(conn, group_id)
            new_revision = current_revision + 1

            conn.execute("""
                insert into agent_group_workspace_revisions
                (group_id, revision, parent_revision, file_manifest_json, created_at)
                values (?, ?, ?, ?, ?)
            """, (group_id, new_revision, parent_revision, json_dumps(file_manifest), now))

        return new_revision

    def replace_initial_workspace_manifest(
        self,
        group_id: str,
        file_manifest: dict[str, str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update agent_group_workspace_revisions
                set file_manifest_json = ?
                where group_id = ? and revision = 0
                """,
                (json_dumps(file_manifest), group_id),
            )

    def _current_workspace_revision(self, conn: sqlite3.Connection, group_id: str) -> int:
        """获取当前最大 revision 号"""
        row = conn.execute("""
            select max(revision) as max_revision from agent_group_workspace_revisions where group_id = ?
        """, (group_id,)).fetchone()
        return row["max_revision"] if row and row["max_revision"] is not None else 0

    # ===== 工作区提交事务管理 =====

    def create_workspace_commit(
        self, group_id: str, group_run_id: str, source_revision: int
    ) -> str:
        """创建工作区提交事务（返回 commit_id）"""
        now = utc_now_text()
        commit_id = uuid4().hex

        with self._connect() as conn:
            conn.execute("""
                insert into agent_group_workspace_commits
                (commit_id, group_id, group_run_id, source_revision, target_revision, status,
                 conflict_files_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (commit_id, group_id, group_run_id, source_revision, None, "prepared", None, now, now))

        return commit_id

    def update_workspace_commit(self, commit_id: str, payload: dict[str, Any]) -> None:
        """更新提交事务状态"""
        now = utc_now_text()
        updates = []
        params = []

        if "status" in payload:
            status = str(payload["status"])
            if status not in WORKSPACE_COMMIT_STATUSES:
                raise AgentGroupStoreError(f"invalid commit status: {status}")
            updates.append("status = ?")
            params.append(status)

        if "target_revision" in payload:
            updates.append("target_revision = ?")
            params.append(payload["target_revision"])

        if "conflict_files_json" in payload:
            updates.append("conflict_files_json = ?")
            params.append(payload["conflict_files_json"])

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(now)
        params.append(commit_id)

        with self._connect() as conn:
            conn.execute(f"""
                update agent_group_workspace_commits
                set {', '.join(updates)}
                where commit_id = ?
            """, params)

    def get_workspace_commit(self, commit_id: str) -> dict[str, Any] | None:
        """获取提交事务"""
        with self._connect() as conn:
            row = conn.execute("""
                select commit_id, group_id, group_run_id, source_revision, target_revision, status,
                       conflict_files_json, created_at, updated_at
                from agent_group_workspace_commits
                where commit_id = ?
            """, (commit_id,)).fetchone()

            if row is None:
                return None

            return self._workspace_commit_view(row)

    def list_pending_workspace_commits(self) -> list[dict[str, Any]]:
        """Return unresolved commit journals for deterministic startup recovery."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                select commit_id, group_id, group_run_id, source_revision, target_revision, status,
                       conflict_files_json, created_at, updated_at
                from agent_group_workspace_commits
                where status in ('prepared', 'files_committed', 'context_committed')
                order by created_at asc
                """
            ).fetchall()
        return [self._workspace_commit_view(row) for row in rows]


    # ===== 辅助方法（路径、视图转换） =====

    def group_workspace_root(self, group_id: str) -> Path:
        """群聊事务数据根目录，不是用户共享工作区。"""
        return factory_artifact_path("agent_group", group_id, "workspace")

    def group_workdir(self, group_id: str) -> Path:
        """群聊成员共享的最终工作区根目录。"""
        with self._connect() as conn:
            row = conn.execute(
                "select title, workspace_id from agent_group_sessions where group_id = ?",
                (group_id,),
            ).fetchone()
        if row is None:
            raise AgentGroupStoreError(f"group not found: {group_id}")
        workspace_id = str(row["workspace_id"] or "").strip()
        if not workspace_id:
            workspace_id = self._migrate_legacy_group_workspace(
                group_id,
                str(row["title"] or ""),
            )
        return WorkspaceStore().workdir(workspace_id)

    def group_staging_root(self, group_id: str, group_run_id: str) -> Path:
        """群聊 run staging 目录"""
        return factory_artifact_path("agent_group", group_id, "staging", group_run_id)

    def group_workspace_revision_root(self, group_id: str, revision: int) -> Path:
        """Immutable filesystem snapshot for one committed workspace revision."""
        return self.group_workspace_root(group_id) / "revisions" / str(revision)

    def _migrate_legacy_group_workspace(self, group_id: str, title: str) -> str:
        legacy_workdir = self.group_workspace_root(group_id) / "committed"
        workspace = WorkspaceStore().create(
            title=f"{title.strip() or 'Agent 群聊'} 工作区",
            mode="project",
            root_kind="managed",
            workdir_root=legacy_workdir,
        )
        with self._connect() as conn:
            conn.execute(
                """
                update agent_group_sessions
                set workspace_id = ?
                where group_id = ? and workspace_id = ''
                """,
                (workspace.workspace_id, group_id),
            )
            row = conn.execute(
                "select workspace_id from agent_group_sessions where group_id = ?",
                (group_id,),
            ).fetchone()
        resolved = str(row["workspace_id"] or "").strip() if row is not None else ""
        if resolved != workspace.workspace_id:
            WorkspaceStore().delete(workspace.workspace_id, delete_files=False)
        if not resolved:
            raise AgentGroupStoreError(f"failed to migrate group workspace: {group_id}")
        return resolved

    # ===== 视图转换（Row -> dict） =====

    def _session_view(self, row: sqlite3.Row) -> dict[str, Any]:
        """会话视图"""
        return dict(row)

    def _member_view(self, row: sqlite3.Row) -> dict[str, Any]:
        """成员视图"""
        return dict(row)

    def _message_view(self, row: sqlite3.Row) -> dict[str, Any]:
        """消息视图"""
        data = dict(row)
        data["context_references"] = json_loads(data.pop("context_references_json", "[]"), [])
        return data

    def _run_view(self, row: sqlite3.Row) -> dict[str, Any]:
        """运行记录视图"""
        return dict(row)

    def _context_version_view(self, row: sqlite3.Row) -> dict[str, Any]:
        """上下文版本视图"""
        return dict(row)

    def _workspace_revision_view(self, row: sqlite3.Row) -> dict[str, Any]:
        """工作区版本视图"""
        data = dict(row)
        data["file_manifest"] = json_loads(data.pop("file_manifest_json", "{}"), {})
        return data

    def _workspace_commit_view(self, row: sqlite3.Row) -> dict[str, Any]:
        """工作区提交视图"""
        data = dict(row)
        conflict_json = data.pop("conflict_files_json", None)
        data["conflict_files"] = json_loads(conflict_json, []) if conflict_json else []
        return data


# ===== 模块级辅助函数 =====


def resolve_agent_group_store_path(value: str | Path | None = None) -> Path:
    """解析 store 路径"""
    if value:
        return resolve_project_path(value)
    return factory_artifact_path("agent_group", "store.sqlite")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row["name"]) for row in conn.execute(f"pragma table_info({table})")}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")


def _migrate_session_identity_columns(conn: sqlite3.Connection) -> None:
    """Migrate the abandoned conversation identity schema to runtime session IDs.

    The unified-orchestration prototype renamed these persisted columns to
    ``conversation_id``. The production runtime was subsequently restored to
    package sessions, so existing databases created by that prototype must be
    migrated before any canonical index or query is evaluated.
    """
    for table in ("agent_group_members", "agent_group_member_runs"):
        columns = {str(row["name"]) for row in conn.execute(f"pragma table_info({table})")}
        has_session_id = "package_session_id" in columns
        has_conversation_id = "conversation_id" in columns
        if has_session_id and has_conversation_id:
            raise AgentGroupStoreError(
                f"ambiguous agent-group session identity schema in {table}"
            )
        if has_session_id:
            continue
        if not has_conversation_id:
            raise AgentGroupStoreError(
                f"agent-group session identity column is missing from {table}"
            )
        conn.execute(
            f"alter table {table} rename column conversation_id to package_session_id"
        )


def utc_now_text() -> str:
    """当前 UTC 时间的 ISO 8601 字符串"""
    return datetime.now(timezone.utc).isoformat()


def json_dumps(value: Any) -> str:
    """JSON 序列化（确保 ASCII 不转义，key 排序）"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, default: Any = None) -> Any:
    """JSON 反序列化（安全回退）"""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
