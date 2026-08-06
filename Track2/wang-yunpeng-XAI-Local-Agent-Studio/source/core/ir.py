"""XAI V2 中间表示（IR）类型定义

V2 架构内核：纯数据流（IR → Planner → Executor）。
P0 阶段使用 TypedDict（最小改动），后续升级为 Pydantic。
"""

from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, TypedDict


class WorkflowNode(TypedDict, total=False):
    """工作流节点"""
    id: str
    type: str          # 节点类型: chat / condition / loop / batch / exec / ...
    label: str
    config: Dict[str, Any]


class WorkflowEdge(TypedDict, total=False):
    """工作流边"""
    source: str
    target: str


class NodeResult(TypedDict, total=False):
    """节点执行结果"""
    node_id: str
    status: Literal["running", "done", "error", "skipped"]
    output: str
    error: Optional[str]
    duration_ms: float
