"""
任务 DAG（有向无环图）定义。

规划 Agent 产出 JSON → 解析为 TaskDAG →
Executor 按拓扑序并行执行。
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    """DAG 节点类型 —— 对应不同的执行 Agent。"""
    LLM = "llm"               # 纯文本推理
    VISION = "vision"         # 图片分析
    STT = "stt"               # 语音转文字
    TTS = "tts"               # 文字转语音
    IMAGE_GEN = "image_gen"   # 文生图
    IMAGE_EDIT = "image_edit" # 图片编辑


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"       # 因前置节点失败而跳过


@dataclass
class DAGNode:
    """DAG 中的一个任务节点。"""
    id: str
    type: NodeType
    prompt: str                          # 给执行 Agent 的指令
    depends_on: list[str] = field(default_factory=list)  # 依赖的节点 ID
    context_vars: dict[str, str] = field(default_factory=dict)  # 上下文变量引用

    # ── v2.0 新增字段 ──
    reset_context: bool = False          # 是否需要在执行前清空上下文
    timeout_override: float | None = None  # 按节点覆盖超时（None 则按类型默认）

    # 运行时填充
    status: NodeStatus = NodeStatus.PENDING
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "prompt": self.prompt,
            "depends_on": self.depends_on,
            "context_vars": self.context_vars,
            "reset_context": self.reset_context,          # M4 修复：补全被丢弃的字段
            "timeout_override": self.timeout_override,    # （UI/序列化 round-trip 不再丢失）
        }


@dataclass
class TaskDAG:
    """完整的任务 DAG。"""
    task_id: str
    description: str
    nodes: list[DAGNode]
    user_inputs: dict[str, Any] = field(default_factory=dict)  # 用户上传的文件等

    @classmethod
    def from_json(cls, json_str: str) -> "TaskDAG":
        """从规划 Agent 输出的 JSON 字符串解析 DAG。"""
        # 清理 markdown 包裹和非法字符
        cleaned = json_str.strip()
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # I1 修复：与主路径一致，复用 planner 的多策略修复
            # （避免直接调用方在尾逗号/代码块等场景下解析失败）
            from ..agents.planner import _repair_json
            repaired = _repair_json(cleaned)
            data = json.loads(repaired)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskDAG":
        """从已解析并验证的字典构建 DAG（跳过 JSON 解析步骤）。

        当 parse_and_validate 已经对 JSON 进行了多策略修复后，
        使用此方法避免重复解析原始（可能仍有问题）的 JSON 字符串。
        """
        nodes = []
        for node_data in data.get("nodes", []):
            nodes.append(DAGNode(
                id=node_data["id"],
                type=NodeType(node_data["type"]),
                prompt=node_data.get("prompt", ""),
                depends_on=node_data.get("depends_on", []),
                context_vars=node_data.get("context_vars", {}),
                reset_context=node_data.get("reset_context", False),
                timeout_override=node_data.get("timeout_override"),
            ))

        return cls(
            task_id=data.get("task_id", "unknown"),
            description=data.get("description", ""),
            nodes=nodes,
            user_inputs=data.get("user_inputs", {}),
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "nodes": [n.to_dict() for n in self.nodes],
            "user_inputs": self.user_inputs,
        }

    def node_by_id(self, node_id: str) -> DAGNode | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_ready_nodes(self) -> list[DAGNode]:
        """获取所有依赖已满足、可以立即执行的节点。"""
        node_index = {n.id: n for n in self.nodes}
        ready = []
        for node in self.nodes:
            if node.status != NodeStatus.PENDING:
                continue
            if all(
                (dep_node := node_index.get(dep)) and dep_node.status == NodeStatus.DONE
                for dep in node.depends_on
            ):
                ready.append(node)
        return ready

    def any_failed(self) -> bool:
        return any(n.status == NodeStatus.FAILED for n in self.nodes)

    def all_done(self) -> bool:
        return all(n.status in (NodeStatus.DONE, NodeStatus.SKIPPED) for n in self.nodes)

    def summary(self) -> str:
        """可读的任务摘要。"""
        lines = [f"📋 {self.description}"]
        for node in self.nodes:
            emoji = {
                NodeType.LLM: "💬", NodeType.VISION: "👁️",
                NodeType.STT: "🎤", NodeType.TTS: "🔊",
                NodeType.IMAGE_GEN: "🎨", NodeType.IMAGE_EDIT: "✏️",
            }.get(node.type, "❓")

            status_icon = {
                NodeStatus.PENDING: "⏳", NodeStatus.RUNNING: "🔄",
                NodeStatus.DONE: "✅", NodeStatus.FAILED: "❌",
                NodeStatus.SKIPPED: "⏭️",
            }.get(node.status, "❓")

            deps = f" ← {', '.join(node.depends_on)}" if node.depends_on else ""
            lines.append(f"  {status_icon} {emoji} [{node.id}] {node.prompt[:50]}{deps}")
        return "\n".join(lines)
