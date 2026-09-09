"""
[v3 P5 兼容层] 任务内共享记忆已迁移至 `src/memory/task_memory.py`。

本模块仅重导出，保持 v1 代码引用（llm_agent / executor / tools / main）正常；
P7 退役清理时将删除本文件并更新引用。
"""
from ..memory.task_memory import (
    TaskMemory,
    AgentSlot,
    SharedMemory,
    get_shared_memory,
    reset_shared_memory,
)

__all__ = [
    "TaskMemory",
    "AgentSlot",
    "SharedMemory",
    "get_shared_memory",
    "reset_shared_memory",
]
