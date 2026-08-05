import json
import sqlite3
import threading
import time
import uuid
import logging

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, parent_id TEXT, type TEXT, trigger TEXT,
    status TEXT, summary TEXT, started_at INTEGER, ended_at INTEGER
);
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, seq INTEGER,
    kind TEXT, content_json TEXT, ts INTEGER
);
CREATE TABLE IF NOT EXISTS cluster_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_json TEXT, updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT, tool_name TEXT, args_json TEXT,
    risk_level TEXT, status TEXT, result_json TEXT, ts INTEGER
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT, tool_name TEXT, args_json TEXT,
    risk_level TEXT, dry_run_json TEXT,
    status TEXT, decided_by TEXT, decided_at INTEGER, ts INTEGER
);
CREATE TABLE IF NOT EXISTS risk_rules (
    id          TEXT PRIMARY KEY,
    tool_name   TEXT NOT NULL,
    match_json  TEXT,
    tier        TEXT NOT NULL,
    autonomous  INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    priority    INTEGER NOT NULL DEFAULT 0,
    updated_at  INTEGER,
    updated_by  TEXT
);
-- M5 知识库: runbooks 表 (§14 / §17)
-- source: manual(手写) / agent_generated(agent回写, 需审核)
-- status: approved(已审核可用) / pending_review(待审核) / rejected(审核拒绝)
-- embedding: BLOB 存向量 (bge-small 512维 float32), NULL=未编码
CREATE TABLE IF NOT EXISTS runbooks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    tags        TEXT,                 -- 逗号分隔标签, 如 "hdfs,datanode,oom"
    source      TEXT NOT NULL DEFAULT 'manual',  -- manual / agent_generated
    status      TEXT NOT NULL DEFAULT 'approved', -- approved / pending_review / rejected
    session_id  TEXT,                 -- agent 回写时关联的 fix session
    confidence  REAL DEFAULT 1.0,     -- agent 回写的置信度 (0-1)
    embedding   BLOB,                 -- 向量 (float32 数组), NULL=未编码
    created_at  INTEGER,
    updated_at  INTEGER,
    updated_by  TEXT
);
-- FTS5 全文检索 (BM25 兆底, 不依赖 sqlite-vec)
CREATE VIRTUAL TABLE IF NOT EXISTS runbooks_fts USING fts5(
    title, content, tags,
    content='runbooks', content_rowid='rowid',
    tokenize='unicode61'
);
-- 触发器: runbooks 增删改时同步 FTS
CREATE TRIGGER IF NOT EXISTS runbooks_ai AFTER INSERT ON runbooks BEGIN
    INSERT INTO runbooks_fts(rowid, title, content, tags)
    VALUES (new.rowid, new.title, new.content, COALESCE(new.tags, ''));
END;
CREATE TRIGGER IF NOT EXISTS runbooks_ad AFTER DELETE ON runbooks BEGIN
    INSERT INTO runbooks_fts(runbooks_fts, rowid, title, content, tags)
    VALUES ('delete', old.rowid, old.title, old.content, COALESCE(old.tags, ''));
END;
CREATE TRIGGER IF NOT EXISTS runbooks_au AFTER UPDATE ON runbooks BEGIN
    INSERT INTO runbooks_fts(runbooks_fts, rowid, title, content, tags)
    VALUES ('delete', old.rowid, old.title, old.content, COALESCE(old.tags, ''));
    INSERT INTO runbooks_fts(rowid, title, content, tags)
    VALUES (new.rowid, new.title, new.content, COALESCE(new.tags, ''));
END;
-- M6: 对话式运维
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '新对话',
    created_at  INTEGER,
    updated_at  INTEGER
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              TEXT PRIMARY KEY,
    chat_session_id TEXT,                      -- 关联的 chat session
    user_msg        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending', -- pending / processing / done / error
    session_id      TEXT,                      -- 关联的 agent session (ReAct 思考链)
    reply           TEXT,
    role            TEXT NOT NULL DEFAULT 'user',
    created_at      INTEGER,
    processed_at    INTEGER
);
"""

# 默认风险规则种子数据 (§21.3 — 首启若空则灌入)
_DEFAULT_RISK_RULES = [
    ("rule_get_service_status", "get_service_status", None, "low",      1, 1, 0),
    ("rule_get_alerts",         "get_alerts",         None, "low",      1, 1, 0),
    ("rule_get_metrics",       "get_metrics",        None, "low",      1, 1, 0),
    ("rule_read_logs",         "read_logs",          None, "low",      1, 1, 0),
    ("rule_search_kb",         "search_kb",          None, "low",      1, 1, 0),
    ("rule_hdfs_admin",        "hdfs_admin",         None, "low",      1, 1, 0),
    ("rule_restart_service",   "restart_service",    None, "recover",  1, 1, 0),
    ("rule_edit_remote_config","edit_remote_config", None, "reversible", 1, 1, 0),
    ("rule_write_runbook",    "write_runbook",      None, "low",      1, 1, 0),
    ("rule_diagnose_node",    "diagnose_node",      None, "low",      1, 1, 0),
    ("rule_file_ops",         "file_ops",           None, "medium",   1, 1, 0),
    # fail-closed 默认: 未知工具一律不可逆 + 不自动
    ("rule_default",           "*",                  None, "irreversible", 0, 1, -1),
]

# 默认 runbook 种子数据 (M5 — 首启若空则灌入)
_DEFAULT_RUNBOOKS = [
    {
        "id": "rb_datanode_oom",
        "title": "DataNode OOM 崩溃修复",
        "content": (
            "症状: DataNode 进程因 OOM 退出, CM 显示角色状态 DOWN。"
            "排查步骤: 1. read_logs(service=DataNode, filter=OOM) 确认 OutOfMemoryError "
            "2. get_metrics(metric=memory, node=<对应节点>) 查看内存使用 "
            "3. 检查 HADOOP_DATANODE_HEAPSIZE 或 hadoop-env.sh 中 JAVA_HEAP_MAX "
            "修复: 通过 edit_remote_config 调大 DataNode 堆内存至 8192MB (原默认 1000MB) "
            "重启: restart_service(service=DataNode) via CM API commands/start "
            "验证: get_service_status(service=DataNode) + hdfs_admin(action=report) 查看 Live Datanodes"
        ),
        "tags": "hdfs,datanode,oom,memory",
        "source": "manual",
    },
    {
        "id": "rb_namenode_gc",
        "title": "NameNode GC overhead 导致服务卡顿",
        "content": (
            "症状: NameNode 响应慢, RPC 延迟高, 日志出现 GC overhead limit exceeded。"
            "排查: 1. read_logs(service=NameNode, filter=GC) 确认 GC 频率 "
            "2. get_metrics(metric=java_procs, node=<NN节点>) 查看进程 "
            "3. hdfs_admin(action=report) 查看文件数和小文件比例 "
            "原因: 堆内存不足 / 小文件过多 / GC 策略不当 "
            "修复: edit_remote_config 调大 NameNode 堆内存 (如 -Xmx32g), 启用 G1GC (-XX:+UseG1GC) "
            "注意: NameNode 是核心服务, 重启判高危, 需走审批 (supervised) 或 attempt 节流 (autonomous)"
        ),
        "tags": "hdfs,namenode,gc,memory",
        "source": "manual",
    },
    {
        "id": "rb_nodemanager_down",
        "title": "YARN NodeManager 掉线",
        "content": (
            "症状: NodeManager 心跳丢失, YARN 显示节点 UNHEALTHY。"
            "排查: 1. get_service_status(service=NodeManager, node=<节点>) 确认状态 "
            "2. read_logs(service=NodeManager, filter=ERROR) 查错误日志 "
            "3. get_metrics(metric=disk, node=<节点>) 检查 nodemanager.local-dirs 磁盘 "
            "常见原因: OOM / 磁盘满 / 网络不通 "
            "修复: 磁盘满则清理, OOM 则调堆内存, 否则 restart_service(service=NodeManager) "
            "验证: get_service_status 确认 RUNNING + HEALTHY"
        ),
        "tags": "yarn,nodemanager,down,disk,oom",
        "source": "manual",
    },
    {
        "id": "rb_disk_full",
        "title": "HDFS 磁盘满处理",
        "content": (
            "症状: 写入失败, 日志报 No space left on device。"
            "排查: 1. get_metrics(metric=disk, node=<节点>) 用 df -h 确认 "
            "2. hdfs_admin(action=du, path=/) 查看各目录占用 "
            "修复: 清理临时文件/日志 (yarn logs / tmp 文件), 必要时扩容 "
            "注意: 不要直接删 HDFS 数据块, 用 hdfs balancer 重平衡 "
            "预防: 配置 dfs.datanode.du.reserved 预留空间"
        ),
        "tags": "hdfs,disk,full,space",
        "source": "manual",
    },
    {
        "id": "rb_zk_timeout",
        "title": "ZooKeeper 连接超时排查",
        "content": (
            "症状: 依赖 ZK 的服务(HBase/HiveMetaStore)报 SessionExpired。"
            "排查: 1. get_service_status(service=ZooKeeper) 确认集群状态 "
            "2. read_logs(service=ZooKeeper, filter=ERROR) 查异常 "
            "3. get_metrics(metric=cpu, node=<ZK节点>) 检查资源 "
            "原因: ZK 进程异常 / 网络 / sessionTimeout 过小 / 客户端连接过多 "
            "修复: restart_service(service=ZooKeeper) 重启异常节点, 调大 tickTime/sessionTimeout "
            "验证: echo ruok | nc <zk_host> 2181 返回 imok"
        ),
        "tags": "zookeeper,timeout,session",
        "source": "manual",
    },
    {
        "id": "rb_namenode_sigterm",
        "title": "NameNode 进程被 SIGTERM 终止",
        "content": (
            "症状: NameNode 进程突然消失, 日志末尾无明显错误, 可能有 SIGTERM 痕迹。"
            "排查: 1. read_logs(service=NameNode, filter=SIGTERM) 查终止信号 "
            "2. get_metrics(metric=java_procs, node=<NN节点>) 确认进程不在 (jps) "
            "3. search_kb 查已知模式排除 OOM/GC "
            "4. 检查是否人为操作 (运维/脚本误杀) "
            "修复: restart_service(service=NameNode) via CM API commands/start "
            "验证: get_service_status(service=NameNode) 确认 RUNNING + GOOD "
            "hdfs_admin(action=report) 确认集群健康 "
            "注意: NameNode 重启后需等待 exit safe mode, 期间不可写"
        ),
        "tags": "hdfs,namenode,sigterm,restart",
        "source": "agent_generated",
    },
]


class Store:
    """SQLite 存储 — 线程安全 (RLock 保护所有 conn 操作)"""

    def __init__(self, db_path: str):
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.executescript(
            "CREATE INDEX IF NOT EXISTS idx_events_session "
            "ON session_events(session_id, seq);"
            "CREATE INDEX IF NOT EXISTS idx_audit_session "
            "ON audit_log(session_id);"
            "CREATE INDEX IF NOT EXISTS idx_audit_tool "
            "ON audit_log(tool_name, ts);"
            "CREATE INDEX IF NOT EXISTS idx_approvals_session "
            "ON approvals(session_id);"
            "CREATE INDEX IF NOT EXISTS idx_approvals_status "
            "ON approvals(status);"
            "CREATE INDEX IF NOT EXISTS idx_risk_rules_tool "
            "ON risk_rules(tool_name, enabled, priority DESC);"
            "CREATE INDEX IF NOT EXISTS idx_runbooks_status "
            "ON runbooks(status, source);"
            "CREATE INDEX IF NOT EXISTS idx_runbooks_tags "
            "ON runbooks(tags);"
            "CREATE INDEX IF NOT EXISTS idx_chat_status "
            "ON chat_messages(status, created_at);"
        )
        self._seed_risk_rules()
        self._seed_runbooks()
        self._migrate_chat()
        self.conn.commit()

    def _migrate_chat(self):
        """M6 migration: chat_messages 加 role + chat_session_id 列"""
        try:
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(chat_messages)").fetchall()]
            if "role" not in cols:
                self.conn.execute(
                    "ALTER TABLE chat_messages ADD COLUMN role TEXT NOT NULL DEFAULT 'user'"
                )
                logger.info("Migrated chat_messages: added 'role' column")
            if "chat_session_id" not in cols:
                self.conn.execute(
                    "ALTER TABLE chat_messages ADD COLUMN chat_session_id TEXT"
                )
                logger.info("Migrated chat_messages: added 'chat_session_id' column")
        except Exception as e:
            logger.warning(f"chat migration skipped: {e}")

    @property
    def lock(self):
        return self._lock

    # ---- session ----

    def create_session(self, session_type="fix", parent_id=None, trigger=""):
        sid = str(uuid.uuid4())[:8]
        now = int(time.time())
        with self._lock:
            self.conn.execute(
                "INSERT INTO sessions(id,parent_id,type,trigger,status,started_at) VALUES(?,?,?,?,?,?)",
                (sid, parent_id, session_type, trigger, "running", now),
            )
            self.conn.commit()
        return sid

    def log_event(self, session_id: str, seq: int, kind: str, content: dict):
        with self._lock:
            self.conn.execute(
                "INSERT INTO session_events(session_id,seq,kind,content_json,ts) VALUES(?,?,?,?,?)",
                (session_id, seq, kind, json.dumps(content, ensure_ascii=False), int(time.time())),
            )
            self.conn.commit()

    def finish_session(self, session_id: str, summary: str, status="done"):
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET status=?, summary=?, ended_at=? WHERE id=?",
                (status, summary, int(time.time()), session_id),
            )
            self.conn.commit()

    def get_recent_session_summaries(self, limit: int = 5, minutes: int = 10) -> list:
        """Get recent session summaries (auto + fix) within time window for inspection context."""
        cutoff = int(time.time()) - minutes * 60
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, type, trigger, summary, started_at, ended_at "
                "FROM sessions WHERE type IN ('auto','fix') AND status='done' "
                "AND started_at >= ? "
                "ORDER BY started_at DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r[0],
                "type": r[1] or "",
                "trigger": r[2] or "",
                "summary": (r[3] or "")[:200],
                "started_at": r[4],
                "ended_at": r[5] or 0,
            })
        return result

    def save_state_card(self, snapshot: dict):
        with self._lock:
            self.conn.execute(
                "INSERT INTO cluster_state(snapshot_json, updated_at) VALUES(?,?)",
                (json.dumps(snapshot, ensure_ascii=False), int(time.time())),
            )
            self.conn.commit()

    def get_latest_state_card(self) -> dict:
        with self._lock:
            row = self.conn.execute(
                "SELECT snapshot_json FROM cluster_state ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except Exception:
                pass
        return {}

    # ---- risk_rules CRUD (§21.3) ----

    def _seed_risk_rules(self):
        """首启若空则灌入默认规则"""
        count = self.conn.execute("SELECT COUNT(*) FROM risk_rules").fetchone()[0]
        if count > 0:
            return
        for rid, tool, match_json, tier, auto, enabled, pri in _DEFAULT_RISK_RULES:
            self.conn.execute(
                "INSERT INTO risk_rules(id,tool_name,match_json,tier,autonomous,"
                "enabled,priority,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?)",
                (rid, tool, match_json, tier, auto, enabled, pri,
                 int(time.time()), "seed"),
            )
        logger.info(f"Seeded {len(_DEFAULT_RISK_RULES)} default risk_rules")

    def get_risk_rules(self, enabled_only=False):
        """获取所有风险规则"""
        sql = "SELECT id,tool_name,match_json,tier,autonomous,enabled,priority,updated_at,updated_by FROM risk_rules"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY priority DESC, tool_name"
        with self._lock:
            rows = self.conn.execute(sql).fetchall()
        return [
            {"id": r[0], "tool_name": r[1],
             "match_json": json.loads(r[2]) if r[2] else None,
             "tier": r[3], "autonomous": bool(r[4]),
             "enabled": bool(r[5]), "priority": r[6],
             "updated_at": r[7] or 0, "updated_by": r[8] or ""}
            for r in rows
        ]

    def upsert_risk_rule(self, rule: dict):
        """插入或更新风险规则"""
        rid = rule.get("id") or str(uuid.uuid4())[:8]
        match_json = json.dumps(rule["match_json"], ensure_ascii=False) if rule.get("match_json") else None
        # §21.3 UI 护栏: irreversible 档禁止 autonomous=1
        autonomous = 0 if rule.get("tier") == "irreversible" else (1 if rule.get("autonomous") else 0)
        with self._lock:
            self.conn.execute(
                "INSERT INTO risk_rules(id,tool_name,match_json,tier,autonomous,"
                "enabled,priority,updated_at,updated_by) "
                "VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "tool_name=excluded.tool_name, match_json=excluded.match_json, "
                "tier=excluded.tier, autonomous=excluded.autonomous, "
                "enabled=excluded.enabled, priority=excluded.priority, "
                "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (rid, rule["tool_name"], match_json, rule["tier"],
                 autonomous, 1 if rule.get("enabled", True) else 0,
                 rule.get("priority", 0), int(time.time()),
                 rule.get("updated_by", "web-user"))
            )
            self.conn.commit()
        return rid

    def delete_risk_rule(self, rule_id: str):
        """删除风险规则"""
        with self._lock:
            self.conn.execute("DELETE FROM risk_rules WHERE id=?", (rule_id,))
            self.conn.commit()

    # ---- audit_log 查询 (供 §21.5 attempt 节流) ----

    def count_audit_attempts(self, tool_name, target, window_sec=600):
        """统计观察窗口内某 (tool, target) 的已执行次数, 供 attempt 节流"""
        cutoff = int(time.time()) - window_sec
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE tool_name=? AND status='executed' AND ts>? "
                "AND json_extract(args_json, '$.service')=?",
                (tool_name, cutoff, target)
            ).fetchone()
            last_ts_row = self.conn.execute(
                "SELECT MAX(ts) FROM audit_log "
                "WHERE tool_name=? AND status='executed' "
                "AND json_extract(args_json, '$.service')=?",
                (tool_name, target)
            ).fetchone()
        count = row[0] if row else 0
        last_ts = last_ts_row[0] if last_ts_row and last_ts_row[0] else 0
        return count, last_ts

    # ---- runbooks CRUD (M5 知识库) ----

    def _seed_runbooks(self):
        """首启若 runbooks 表空则灌入默认知识库"""
        count = self.conn.execute("SELECT COUNT(*) FROM runbooks").fetchone()[0]
        if count > 0:
            return
        now = int(time.time())
        for rb in _DEFAULT_RUNBOOKS:
            self.conn.execute(
                "INSERT INTO runbooks(id,title,content,tags,source,status,"
                "confidence,created_at,updated_at,updated_by) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (rb["id"], rb["title"], rb["content"], rb.get("tags", ""),
                 rb.get("source", "manual"), "approved", 1.0,
                 now, now, "seed"),
            )
        # FTS 同步 (触发器在 INSERT 时已自动同步, 但 content 表外部表模式需手动重建一次)
        self.conn.execute(
            "INSERT INTO runbooks_fts(runbooks_fts) VALUES('rebuild');"
        )
        logger.info(f"Seeded {len(_DEFAULT_RUNBOOKS)} default runbooks")

    def get_runbooks(self, status=None, source=None, keyword=None):
        """查询 runbooks 列表 (不返回 embedding, 减少传输)

        Args:
            status: approved / pending_review / rejected, None=全部
            source: manual / agent_generated, None=全部
            keyword: 关键词过滤 (title/content/tags 模糊匹配)
        """
        sql = ("SELECT id,title,content,tags,source,status,session_id,"
               "confidence,created_at,updated_at,updated_by FROM runbooks")
        conditions = []
        params = []
        if status:
            conditions.append("status=?")
            params.append(status)
        if source:
            conditions.append("source=?")
            params.append(source)
        if keyword:
            conditions.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [
            {"id": r[0], "title": r[1], "content": r[2], "tags": r[3] or "",
             "source": r[4], "status": r[5], "session_id": r[6] or "",
             "confidence": r[7], "created_at": r[8], "updated_at": r[9],
             "updated_by": r[10] or ""}
            for r in rows
        ]

    def get_runbook(self, rb_id: str) -> dict:
        """获取单个 runbook (含 embedding)"""
        with self._lock:
            row = self.conn.execute(
                "SELECT id,title,content,tags,source,status,session_id,"
                "confidence,embedding,created_at,updated_at,updated_by "
                "FROM runbooks WHERE id=?", (rb_id,)
            ).fetchone()
        if not row:
            return {}
        return {
            "id": row[0], "title": row[1], "content": row[2], "tags": row[3] or "",
            "source": row[4], "status": row[5], "session_id": row[6] or "",
            "confidence": row[7], "embedding": row[8],
            "created_at": row[9], "updated_at": row[10], "updated_by": row[11] or "",
        }

    def upsert_runbook(self, rb: dict) -> str:
        """插入或更新 runbook (不更新 embedding, 由 kb.py 单独编码)"""
        rid = rb.get("id") or f"rb_{uuid.uuid4().hex[:8]}"
        now = int(time.time())
        with self._lock:
            # ON CONFLICT 更新 (embedding 不在此更新, 避免覆盖)
            self.conn.execute(
                "INSERT INTO runbooks(id,title,content,tags,source,status,"
                "session_id,confidence,created_at,updated_at,updated_by) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, content=excluded.content, "
                "tags=excluded.tags, source=excluded.source, "
                "status=excluded.status, session_id=excluded.session_id, "
                "confidence=excluded.confidence, "
                "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (rid, rb["title"], rb["content"], rb.get("tags", ""),
                 rb.get("source", "manual"), rb.get("status", "approved"),
                 rb.get("session_id", ""), rb.get("confidence", 1.0),
                 now, now, rb.get("updated_by", "web-user"))
            )
            self.conn.commit()
        return rid

    def delete_runbook(self, rb_id: str):
        """删除 runbook (FTS 触发器自动同步)"""
        with self._lock:
            self.conn.execute("DELETE FROM runbooks WHERE id=?", (rb_id,))
            self.conn.commit()

    def update_runbook_embedding(self, rb_id: str, embedding_blob: bytes):
        """更新 runbook 向量 (由 kb.py 编码后调用)"""
        with self._lock:
            self.conn.execute(
                "UPDATE runbooks SET embedding=? WHERE id=?",
                (embedding_blob, rb_id)
            )
            self.conn.commit()

    def review_runbook(self, rb_id: str, status: str, reviewer: str = "web-user"):
        """审核 runbook: pending_review -> approved / rejected"""
        now = int(time.time())
        with self._lock:
            self.conn.execute(
                "UPDATE runbooks SET status=?, updated_at=?, updated_by=? WHERE id=?",
                (status, now, reviewer, rb_id)
            )
            self.conn.commit()

    def search_runbooks_fts(self, query: str, limit: int = 5) -> list:
        """FTS5 全文检索 (BM25), 返回匹配的 runbooks (仅 approved)

        Args:
            query: 搜索词 (支持空格分词)
            limit: 返回条数上限
        Returns:
            list of dict: {id, title, content, tags, score}
        """
        if not query.strip():
            return []
        # FTS5 查询: 用 OR 连接各词, 匹配 title/content/tags
        words = [w for w in query.split() if w]
        if not words:
            return []
        # 构建 FTS5 查询表达式 (每个词加 *, 前缀匹配)
        fts_query = " OR ".join(f'"{w}"*' for w in words)
        sql = (
            "SELECT r.id, r.title, r.content, r.tags, r.source, "
            "bm25(runbooks_fts) as score "
            "FROM runbooks_fts f JOIN runbooks r ON r.rowid = f.rowid "
            "WHERE runbooks_fts MATCH ? AND r.status='approved' "
            "ORDER BY score ASC LIMIT ?"
        )
        with self._lock:
            try:
                rows = self.conn.execute(sql, (fts_query, limit)).fetchall()
            except Exception as e:
                logger.warning(f"FTS search failed ({e}), fallback to LIKE")
                # FTS 出错则退回 LIKE 模糊匹配
                kw = f"%{query}%"
                rows = self.conn.execute(
                    "SELECT id, title, content, tags, source, 0 as score "
                    "FROM runbooks WHERE status='approved' "
                    "AND (title LIKE ? OR content LIKE ? OR tags LIKE ?) "
                    "LIMIT ?", (kw, kw, kw, limit)
                ).fetchall()
        return [
            {"id": r[0], "title": r[1], "content": r[2], "tags": r[3] or "",
             "source": r[4], "score": r[5]}
            for r in rows
        ]

    def get_runbooks_for_embedding(self) -> list:
        """获取所有需要重新编码向量的 runbooks (embedding IS NULL 且 status=approved)"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, title, content, tags FROM runbooks "
                "WHERE embedding IS NULL AND status='approved'"
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "content": r[2], "tags": r[3] or ""}
            for r in rows
        ]

    def get_all_runbook_embeddings(self) -> list:
        """获取所有已编码的 runbook 向量 (供向量检索)"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, title, content, tags, embedding FROM runbooks "
                "WHERE embedding IS NOT NULL AND status='approved'"
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "content": r[2], "tags": r[3] or "",
             "embedding": r[4]}
            for r in rows
        ]

    # ---- chat_sessions + chat_messages (多 session 对话式运维) ----

    def create_chat_session(self, title: str = "New Chat") -> dict:
        """创建新的 chat session"""
        sid = str(uuid.uuid4())[:8]
        now = int(time.time())
        with self._lock:
            self.conn.execute(
                "INSERT INTO chat_sessions(id,title,created_at,updated_at) "
                "VALUES(?,?,?,?)",
                (sid, title, now, now),
            )
            self.conn.commit()
        return {"id": sid, "title": title, "created_at": now, "updated_at": now}

    def get_chat_sessions(self) -> list:
        """获取所有 chat sessions (按 updated_at 倒序)"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT s.id, s.title, s.created_at, s.updated_at, "
                "(SELECT COUNT(*) FROM chat_messages WHERE chat_session_id=s.id) AS msg_count "
                "FROM chat_sessions s ORDER BY s.updated_at DESC"
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "created_at": r[2],
             "updated_at": r[3], "msg_count": r[4]}
            for r in rows
        ]

    def delete_chat_session(self, sid: str):
        """删除 chat session 及其所有消息"""
        with self._lock:
            self.conn.execute(
                "DELETE FROM chat_messages WHERE chat_session_id=?", (sid,))
            self.conn.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
            self.conn.commit()

    def rename_chat_session(self, sid: str, title: str):
        with self._lock:
            self.conn.execute(
                "UPDATE chat_sessions SET title=?, updated_at=? WHERE id=?",
                (title, int(time.time()), sid),
            )
            self.conn.commit()

    def create_chat_message(self, user_msg: str, chat_session_id: str = None) -> str:
        """用户提交聊天消息, 返回 msg_id"""
        msg_id = str(uuid.uuid4())[:8]
        now = int(time.time())
        with self._lock:
            self.conn.execute(
                "INSERT INTO chat_messages(id,chat_session_id,user_msg,status,role,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (msg_id, chat_session_id, user_msg, "pending", "user", now),
            )
            if chat_session_id:
                self.conn.execute(
                    "UPDATE chat_sessions SET updated_at=? WHERE id=?",
                    (now, chat_session_id),
                )
            self.conn.commit()
        return msg_id

    def get_pending_chat_messages(self, limit: int = 1) -> list:
        """获取 pending 状态的聊天消息 (FIFO)"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, user_msg, chat_session_id FROM chat_messages "
                "WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"id": r[0], "user_msg": r[1], "chat_session_id": r[2]} for r in rows]

    def mark_chat_processing(self, msg_id: str, agent_session_id: str):
        """标记消息为 processing, 关联 agent session_id"""
        with self._lock:
            self.conn.execute(
                "UPDATE chat_messages SET status='processing', session_id=?, "
                "processed_at=? WHERE id=?",
                (agent_session_id, int(time.time()), msg_id),
            )
            self.conn.commit()

    def finish_chat_message(self, msg_id: str, reply: str, status: str = "done"):
        """消息处理完成, 写入回复"""
        with self._lock:
            self.conn.execute(
                "UPDATE chat_messages SET status=?, reply=? WHERE id=?",
                (status, reply, msg_id),
            )
            self.conn.execute(
                "UPDATE chat_sessions SET updated_at=? WHERE id IN "
                "(SELECT chat_session_id FROM chat_messages WHERE id=?)",
                (int(time.time()), msg_id),
            )
            self.conn.commit()

    def get_chat_history_by_session(self, chat_session_id: str, limit: int = 20) -> list:
        """获取指定 chat session 的历史 (正序, 供多轮上下文拼接)
        返回 [{role, content}, ...], 只含已完成的 user+assistant 消息"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT user_msg, reply FROM chat_messages "
                "WHERE chat_session_id=? AND status='done' "
                "ORDER BY created_at DESC LIMIT ?",
                (chat_session_id, limit),
            ).fetchall()
        rows = list(reversed(rows))
        history = []
        for r in rows:
            history.append({"role": "user", "content": r[0]})
            if r[1]:
                history.append({"role": "assistant", "content": r[1]})
        return history

    def get_chat_messages_by_session(self, chat_session_id: str) -> list:
        """获取指定 chat session 的所有消息 (正序, 供前端展示)"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, user_msg, status, session_id, reply, role, "
                "created_at, processed_at FROM chat_messages "
                "WHERE chat_session_id=? ORDER BY created_at ASC",
                (chat_session_id,),
            ).fetchall()
        return [
            {"id": r[0], "user_msg": r[1], "status": r[2],
             "session_id": r[3] or "", "reply": r[4] or "",
             "role": r[5], "created_at": r[6], "processed_at": r[7] or 0}
            for r in rows
        ]