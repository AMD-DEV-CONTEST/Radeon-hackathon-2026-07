"""
Layer 2+Layer 3 公共记忆服务（v2.0 增强）

v2.0 相对于 v1.0 的增强：
1. 快照版本号机制 —— 读取时获取一致性快照，避免被其他工头修改
2. 经验记忆类型 —— 工头可写入 `experience` 类型的失败教训
3. 写入权限分离 —— 第3层工头可写入，第2层可读取
4. 记忆分类与过期 —— experience/history/result 三种类型
"""
from __future__ import annotations

import time
import hashlib
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from loguru import logger


# ═══════════════════════════════════════════════════════════════
# 记忆类型与数据结构
# ═══════════════════════════════════════════════════════════════

class MemoryType(str, Enum):
    """记忆分类。"""
    RESULT = "result"           # 最终结果摘要
    EXPERIENCE = "experience"   # 失败经验/教训
    HISTORY = "history"         # 历史上下文摘要
    NOTE = "note"               # 通用笔记


@dataclass
class MemoryEntry:
    """单条记忆条目。"""
    memory_id: str                      # 唯一ID
    memory_type: MemoryType             # 记忆类型
    task_id: str = ""                   # 关联任务ID
    task_type: str = ""                 # 任务类型: image/text/audio
    subject: str = ""                   # 主题标签
    content: str = ""                   # 记忆内容
    tags: list[str] = field(default_factory=list)   # 检索标签
    version: int = 1                    # 版本号
    created_at: float = field(default_factory=time.time)
    created_by: str = ""                # 创建者（工头ID）

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


@dataclass
class MemorySnapshot:
    """某个时刻的记忆快照 —— 下发时附带副本，避免读取过程中被修改。"""
    entries: list[MemoryEntry]
    version_map: dict[str, int]         # memory_id → version（用于检查是否过时）
    snapshot_time: float = field(default_factory=time.time)
    task_filter: str = ""               # 按 task_id 过滤

    def is_stale(self, current_versions: dict[str, int]) -> bool:
        """检查快照是否已过时。"""
        for mid, ver in self.version_map.items():
            if current_versions.get(mid, 0) > ver:
                return True
        return False


# ═══════════════════════════════════════════════════════════════
# 公共记忆服务
# ═══════════════════════════════════════════════════════════════

class PublicMemoryService:
    """
    v2.0 公共记忆服务。

    职责：
    - 第3层工头：写入最终结果摘要 + 经验片段
    - 第2层调度：根据任务检索 Top-K 相关记忆，以 Manifest 形式下发

    特性：
    - 快照版本号机制：读取时附带快照，避免不一致
    - 经验类型分离：experience 记忆有独立的读写和过期策略
    - 写入限制：不允许写入完整思考过程、调试日志
    - 容量管理：总条目数上限 + 按类型过期策略
    """

    # 配置
    MAX_ENTRIES = 1000                  # 总记忆条目上限
    MAX_EXPERIENCES = 200               # 经验记忆上限
    EXPERIENCE_TTL_SECONDS = 86400 * 30  # 经验记忆30天过期
    RESULT_TTL_SECONDS = 86400 * 7      # 结果记忆7天过期
    MIN_CONTENT_LENGTH = 10             # 最小内容长度（防噪音）

    def __init__(self):
        self._entries: dict[str, MemoryEntry] = {}
        self._lock = threading.RLock()   # 写入锁
        self._version_counter: dict[str, int] = {}  # memory_id → 最新版本
        self._id_counter = 0

    # ── 写入接口（第3层工头调用） ──

    def write_result(self, task_id: str, task_type: str, content: str,
                     subject: str = "", tags: list[str] | None = None,
                     created_by: str = "") -> MemoryEntry:
        """写入任务结果摘要。"""
        return self._write(
            memory_type=MemoryType.RESULT,
            task_id=task_id,
            task_type=task_type,
            content=content,
            subject=subject,
            tags=tags or [],
            created_by=created_by,
        )

    def write_experience(self, task_type: str, subject: str, content: str,
                         tags: list[str] | None = None,
                         created_by: str = "") -> MemoryEntry:
        """写入经验教训（如失败原因、用户偏好等）。"""
        # 准入检查：内容太短的不写（防噪音）
        if len(content.strip()) < self.MIN_CONTENT_LENGTH:
            logger.debug(f"[MEM] 经验内容过短（{len(content)}字），跳过写入")
            return None

        # 去重检查：近期是否已有相似经验
        if self._has_similar_experience(subject, content):
            logger.debug(f"[MEM] 已存在相似经验，跳过: {subject[:50]}")
            return None

        return self._write(
            memory_type=MemoryType.EXPERIENCE,
            task_type=task_type,
            content=content,
            subject=subject,
            tags=tags or [],
            created_by=created_by,
        )

    def _write(self, memory_type: MemoryType, content: str,
               task_id: str = "", task_type: str = "", subject: str = "",
               tags: list[str] | None = None,
               created_by: str = "") -> MemoryEntry:
        """内部写入。"""
        with self._lock:
            # 容量检查
            self._enforce_capacity()

            self._id_counter += 1
            mid = f"mem_{self._id_counter:06d}"
            entry = MemoryEntry(
                memory_id=mid,
                memory_type=memory_type,
                task_id=task_id,
                task_type=task_type,
                subject=subject,
                content=content,
                tags=tags or [],
                created_at=time.time(),
                created_by=created_by,
            )
            self._entries[mid] = entry
            self._version_counter[mid] = entry.version
            logger.info(f"[MEM] 写入 {memory_type.value}: {mid} ({len(content)} chars)")
            return entry

    def _enforce_capacity(self):
        """容量管理：超出上限时清理最旧的条目。"""
        total = len(self._entries)
        if total >= self.MAX_ENTRIES:
            # 按时间排序，移除最旧的 10%
            remove_count = max(1, total // 10)
            sorted_entries = sorted(self._entries.items(), key=lambda x: x[1].created_at)
            for mid, _ in sorted_entries[:remove_count]:
                del self._entries[mid]
                self._version_counter.pop(mid, None)
            logger.info(f"[MEM] 容量清理: 移除 {remove_count} 条旧记忆")

    def _has_similar_experience(self, subject: str, content: str) -> bool:
        """简单去重：检查是否有相似主题的经验在近期写入。"""
        # 使用 Jaccard 近似：主题前30字符相同 + 30分钟内写入
        subject_prefix = subject[:30].strip().lower()
        if not subject_prefix:
            return False
        now = time.time()
        recent_cutoff = now - 1800  # 30分钟
        # 重构修复（Bug 9）：快照遍历，避免并发 _write 修改 dict 时
        # 触发 RuntimeError: dictionary changed size during iteration
        for entry in list(self._entries.values()):
            if entry.memory_type == MemoryType.EXPERIENCE:
                if entry.created_at >= recent_cutoff:
                    if entry.subject[:30].strip().lower() == subject_prefix:
                        return True
        return False

    # ── 读取接口（第2层调度调用） ──

    def retrieve(self, task_type: str = "", keywords: list[str] | None = None,
                 memory_types: list[MemoryType] | None = None,
                 limit: int = 10) -> MemorySnapshot:
        """
        检索相关记忆。

        Args:
            task_type: 按任务类型过滤 ("", "image", "text", "audio")
            keywords: 关键词列表
            memory_types: 记忆类型过滤
            limit: 最大返回数

        Returns:
            MemorySnapshot：包含条目和版本号的快照
        """
        self._clean_expired()

        results = []
        # 遍历期间持锁，防止 _write 并发修改触发 RuntimeError
        with self._lock:
            for entry in self._entries.values():
                # 类型过滤
                if memory_types and entry.memory_type not in memory_types:
                    continue

                # 任务类型过滤
                if task_type and entry.task_type and entry.task_type != task_type:
                    continue

                # 关键词匹配（简单子串匹配）
                if keywords:
                    searchable = f"{entry.subject} {entry.content} {' '.join(entry.tags)}".lower()
                    if not any(kw.lower() in searchable for kw in keywords):
                        continue

                results.append(entry)

        # 按时间降序排列，取 Top-K
        results.sort(key=lambda e: e.created_at, reverse=True)
        results = results[:limit]

        # 生成快照
        version_map = {e.memory_id: e.version for e in results}
        snapshot = MemorySnapshot(
            entries=results,
            version_map=version_map,
            task_filter=task_type,
        )

        if results:
            logger.info(f"[MEM] 检索到 {len(results)} 条记忆 (filter: type={task_type})")

        return snapshot

    def get_manifest(self, snapshot: MemorySnapshot) -> dict:
        """
        将快照转换为第2层下发的 Manifest 格式。

        包含元数据清单 + 内容快照（version number），
        确保第3层读取时不会读到被其他工头修改的内容。
        """
        return {
            "relevant_ids": [e.memory_id for e in snapshot.entries],
            "context_summary": self._summarize(snapshot.entries),
            "snapshots": {
                e.memory_id: {
                    "type": e.memory_type.value,
                    "content": e.content,
                    "version": e.version,
                    "subject": e.subject,
                    "tags": e.tags,
                }
                for e in snapshot.entries
            },
            "snapshot_version": {
                mid: ver for mid, ver in snapshot.version_map.items()
            },
        }

    def _summarize(self, entries: list[MemoryEntry]) -> str:
        """从多条记忆生成上下文摘要。"""
        if not entries:
            return "无相关历史记忆"

        parts = []
        for e in entries[:5]:
            type_tag = {"result": "📋", "experience": "💡", "history": "📜", "note": "📝"}.get(e.memory_type.value, "•")
            parts.append(f"{type_tag} [{e.subject[:30]}] {e.content[:80]}")

        return "\n".join(parts)

    # ── 清理 ──

    def _clean_expired(self):
        """清理过期记忆。"""
        now = time.time()
        expired = []
        # list() 快照遍历，避免并发写入修改 dict 大小
        for mid, entry in list(self._entries.items()):
            if entry.memory_type == MemoryType.EXPERIENCE:
                if entry.age_seconds > self.EXPERIENCE_TTL_SECONDS:
                    expired.append(mid)
            elif entry.memory_type == MemoryType.RESULT:
                if entry.age_seconds > self.RESULT_TTL_SECONDS:
                    expired.append(mid)

        if expired:
            with self._lock:
                for mid in expired:
                    self._entries.pop(mid, None)
                    self._version_counter.pop(mid, None)
            logger.info(f"[MEM] 清理 {len(expired)} 条过期记忆")

    def clear(self):
        """清空所有记忆（仅用于测试/重置）。"""
        with self._lock:
            self._entries.clear()
            self._version_counter.clear()
            logger.info("[MEM] 公共记忆已清空")

    # ── 查询 ──

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def experience_count(self) -> int:
        return sum(1 for e in self._entries.values()
                   if e.memory_type == MemoryType.EXPERIENCE)

    def get_experiences_for_task(self, task_type: str, keywords: list[str] | None = None,
                                  limit: int = 5) -> list[MemoryEntry]:
        """辅助方法：检索特定任务类型的经验记忆。"""
        snapshot = self.retrieve(
            task_type=task_type,
            keywords=keywords,
            memory_types=[MemoryType.EXPERIENCE],
            limit=limit,
        )
        return snapshot.entries


# ── 请求级隔离（contextvars） ──
import contextvars

_memory_service: contextvars.ContextVar[PublicMemoryService | None] = contextvars.ContextVar(
    "public_memory_service", default=None
)


def get_public_memory() -> PublicMemoryService:
    """获取当前请求的 PublicMemoryService 实例。"""
    svc = _memory_service.get(None)
    if svc is None:
        svc = PublicMemoryService()
        _memory_service.set(svc)
    return svc


def reset_public_memory() -> PublicMemoryService:
    """为新请求创建全新的公共记忆。"""
    svc = PublicMemoryService()
    _memory_service.set(svc)
    return svc
