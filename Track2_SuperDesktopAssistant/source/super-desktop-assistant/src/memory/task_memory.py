"""
任务内共享记忆（Task Memory，v3 P5：自 `agents/shared_memory.py` 迁入）。

职责：单次任务内的 Agent 上下文存储 —— 供底层 Agent 工具
（get_shared_memory / add_note / add_discovery）协作使用。

与 public_memory 的分工：
- task_memory   → 任务内共享上下文（Agent 槽位、全局笔记、发现），单次任务生命周期
- public_memory → 跨任务持久记忆（快照、经验、结果摘要），带容量与过期

设计原则：
- Allocator 创建和管理任务记忆
- Planner 发现新任务时清空
- 底层 Agent 只能读取和追加（global_notes），不能修改
- 文件/路径/任务要求统一放这里，Agent 通过工具访问

Agent 数量限制：
- 执行 Agent（LLM）: 最多 5 个
- 专用 Agent: image_gen, tts, stt 各 1 个（不占 LLM 配额）
"""
import time
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class AgentSlot:
    """一个底层 Agent 的专属上下文槽位。"""
    agent_id: str = ""
    node_type: str = "llm"          # llm / image_gen / tts / stt
    custom_prompt: str = ""         # Allocator 定制的 prompt
    task_pointer: str = ""          # 指向公共记忆中任务内容的说明
    context_data: dict = field(default_factory=dict)  # Agent 专属附加上下文
    status: str = "idle"            # idle / running / done / failed
    last_result: str = ""           # 上次执行结果（供 Allocator 评估）


class TaskMemory:
    """
    任务内共享记忆管理器（单例，contextvars 隔离）。

    Allocator 通过此对象管理所有 Agent 的上下文。
    底层 Agent 通过工具（get_shared_memory）只读访问。
    """

    def __init__(self):
        # ─── Allocator 写入区 ───
        self.task_id: str = ""
        self.task_description: str = ""
        self.user_input: str = ""
        self.file_paths: dict[str, str] = {}     # name → absolute_path

        # ─── Agent 槽位 ───
        self.agent_slots: dict[str, AgentSlot] = {}
        self._max_llm_agents: int | None = None  # 延迟从 config 读取

        # ─── Agent 追加区（只读访问，agent 可 append） ───
        self.global_notes: list[str] = []
        self.discoveries: list[str] = []          # Agent 发现的要点

        # ─── 统计 ───
        self.created_at: float = time.time()
        self.last_updated: float = time.time()

    # ════════════════════════════════════
    # Allocator 接口
    # ════════════════════════════════════

    def clear(self):
        """Planner 发现新任务时清空全部记忆。"""
        self.task_id = ""
        self.task_description = ""
        self.user_input = ""
        self.file_paths.clear()
        self.agent_slots.clear()
        self.global_notes.clear()
        self.discoveries.clear()
        self.created_at = time.time()
        self.last_updated = time.time()
        logger.info("[MEM] 任务记忆已清空（新任务）")

    def init_task(self, task_id: str, description: str, user_input: str,
                  file_paths: dict[str, str] | None = None):
        """Allocator 初始化任务信息。"""
        self.task_id = task_id
        self.task_description = description
        self.user_input = user_input
        if file_paths:
            self.file_paths.update(file_paths)
        self._touch()
        logger.info(f"[MEM] 任务初始化: {description[:60]}")

    def register_agent(self, node_id: str, node_type: str = "llm") -> AgentSlot | None:
        """Allocator 注册一个底层 Agent 槽位。"""
        if node_type == "llm":
            llm_count = sum(1 for s in self.agent_slots.values() if s.node_type == "llm")
            if llm_count >= self.max_llm_agents:
                logger.warning(f"[MEM] LLM Agent 已达上限 {self.max_llm_agents}，拒绝注册 {node_id}")
                return None

        slot = AgentSlot(agent_id=node_id, node_type=node_type)
        self.agent_slots[node_id] = slot
        self._touch()
        logger.info(f"[MEM] 注册 Agent: {node_id} ({node_type})")
        return slot

    def assign_prompt(self, node_id: str, custom_prompt: str, task_pointer: str = ""):
        """Allocator 给 Agent 分配定制 prompt 和任务指针。"""
        slot = self.agent_slots.get(node_id)
        if not slot:
            slot = self.register_agent(node_id)
            if not slot:
                return
        slot.custom_prompt = custom_prompt
        slot.task_pointer = task_pointer or f"见公共记忆：{self.task_description[:80]}"
        slot.status = "ready"
        slot.context_data.clear()
        self._touch()
        logger.info(f"[MEM] [{node_id}] prompt 已分配 ({len(custom_prompt)} chars)")

    def clear_agent_context(self, node_id: str):
        """Allocator 清空某个 Agent 的专属上下文（准备换新 prompt 重做）。"""
        slot = self.agent_slots.get(node_id)
        if slot:
            slot.context_data.clear()
            slot.custom_prompt = ""
            slot.last_result = ""
            slot.status = "idle"
            self._touch()
            logger.info(f"[MEM] [{node_id}] 上下文已清空，等待新 prompt")

    def mark_done(self, node_id: str, result: str):
        """标记 Agent 执行完成，存储结果供 Allocator 评估。"""
        slot = self.agent_slots.get(node_id)
        if slot:
            slot.status = "done"
            slot.last_result = result[:2000]
            self._touch()

    def mark_failed(self, node_id: str, error: str):
        slot = self.agent_slots.get(node_id)
        if slot:
            slot.status = "failed"
            slot.last_result = error[:500]
            self._touch()

    # ════════════════════════════════════
    # Agent 接口（只读 + 追加）
    # ════════════════════════════════════

    def get_agent_view(self, node_id: str) -> dict:
        """返回某个 Agent 视角的任务记忆（只读）。"""
        slot = self.agent_slots.get(node_id)
        return {
            "agent_id": node_id,
            "task_description": self.task_description,
            "user_input": self.user_input[:3000],
            "file_paths": dict(self.file_paths),
            "custom_prompt": slot.custom_prompt if slot else "",
            "task_pointer": slot.task_pointer if slot else "",
            "global_notes": list(self.global_notes[-20:]),
            "discoveries": list(self.discoveries[-20:]),
            "other_agents": [
                {"id": aid, "type": s.node_type, "status": s.status,
                 "result_preview": s.last_result[:150]}
                for aid, s in self.agent_slots.items()
                if aid != node_id
            ],
        }

    def add_note(self, content: str, prefix: str = ""):
        """Agent 追加一条全局笔记（有数量上限，防内存膨胀）。"""
        note = f"[{prefix}] {content}" if prefix else content
        self.global_notes.append(note)
        # 保留最近 100 条，防止无限增长
        if len(self.global_notes) > 100:
            self.global_notes = self.global_notes[-100:]
        self._touch()

    def add_discovery(self, content: str, agent_id: str = ""):
        """Agent 追加一个发现（有数量上限，防内存膨胀）。"""
        note = f"[{agent_id}] {content}" if agent_id else content
        self.discoveries.append(note)
        # 保留最近 100 条
        if len(self.discoveries) > 100:
            self.discoveries = self.discoveries[-100:]
        self._touch()

    # ─── 查询 ───

    def get_full_snapshot(self) -> dict:
        """Allocator 视角的完整快照（用于决策）。"""
        return {
            "task_id": self.task_id,
            "task_description": self.task_description,
            "user_input": self.user_input[:2000],
            "file_paths": dict(self.file_paths),
            "agents": {
                aid: {
                    "type": s.node_type,
                    "status": s.status,
                    "result": s.last_result[:300],
                }
                for aid, s in self.agent_slots.items()
            },
            "global_notes": list(self.global_notes),
            "discoveries": list(self.discoveries),
        }

    def _touch(self):
        self.last_updated = time.time()

    @property
    def max_llm_agents(self) -> int:
        """从 config 读取 LLM Agent 上限，缓存结果。"""
        if self._max_llm_agents is None:
            try:
                from ..config import get_config
                self._max_llm_agents = get_config().settings.max_llm_agents
            except Exception:
                self._max_llm_agents = 5
        return self._max_llm_agents

    @property
    def llm_agent_count(self) -> int:
        return sum(1 for s in self.agent_slots.values() if s.node_type == "llm")

    @property
    def agent_count(self) -> int:
        return len(self.agent_slots)


# ─── 请求级隔离（contextvars） ───
# 使用 contextvars 确保每个并发请求拥有独立的 TaskMemory 实例，
# 避免多请求间的竞态条件导致任务上下文互相污染。
import contextvars

_request_memory: contextvars.ContextVar[TaskMemory] = contextvars.ContextVar(
    "task_memory", default=None
)


def get_shared_memory() -> TaskMemory:
    """获取当前请求的 TaskMemory 实例。线程安全，自动隔离。"""
    mem = _request_memory.get(None)
    if mem is None:
        mem = TaskMemory()
        _request_memory.set(mem)
    return mem


def reset_shared_memory() -> TaskMemory:
    """为当前请求创建全新的 TaskMemory（新任务开始时调用）。"""
    mem = TaskMemory()
    _request_memory.set(mem)
    return mem


# ─── 向后兼容别名（v1 曾使用 SharedMemory 类名） ───
SharedMemory = TaskMemory
