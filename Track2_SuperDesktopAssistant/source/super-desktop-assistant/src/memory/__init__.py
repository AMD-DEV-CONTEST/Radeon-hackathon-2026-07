"""
记忆层统一接口（v3 P5）：

- task_memory   → 任务内共享上下文（Agent 槽位、全局笔记、发现），供工具 get_shared_memory 使用
- public_memory → 跨任务持久记忆（快照、经验、结果摘要），带容量与过期
"""

from .public_memory import (
    PublicMemoryService,
    MemoryEntry,
    MemorySnapshot,
    MemoryType,
    get_public_memory,
    reset_public_memory,
)
from .task_memory import (
    TaskMemory,
    AgentSlot,
    SharedMemory,
    get_shared_memory,
    reset_shared_memory,
)

__all__ = [
    "PublicMemoryService",
    "MemoryEntry",
    "MemorySnapshot",
    "MemoryType",
    "get_public_memory",
    "reset_public_memory",
    "TaskMemory",
    "AgentSlot",
    "SharedMemory",
    "get_shared_memory",
    "reset_shared_memory",
]
