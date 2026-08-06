"""兼容薄适配层 —— 多 Agent 编排能力已收编至 core/kernel/workflow.py（Phase D 双 DAG 合并）。

本文件不再承载独立 DAG 引擎，仅保留对外符号与旧 API（Orchestrator.graph.add /
topo_order / run_pipeline / run_collaborative）以兼容历史 import 与既有测试；
真实实现全部委托 core.kernel.workflow.CollaborativeOrchestrator（单一事实源）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .kernel.workflow import CollaborativeOrchestrator, OrchestratorNode


@dataclass
class Node:
    id: str
    kind: str                 # agent | model | skill | kb | human | reflect | code | branch
    payload: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


class Graph:
    """原 orchestrator.Graph 的轻量容器（节点表），保留 .add(...) 旧 API。"""

    def __init__(self):
        self.nodes: dict = {}

    def add(self, node: Node) -> None:
        self.nodes[node.id] = node


class Orchestrator:
    """对外兼容包装：暴露旧 API，执行委托 CollaborativeOrchestrator。"""

    def __init__(self, mode: str = "pipeline"):
        assert mode in ("pipeline", "collaborative"), "mode 仅支持 pipeline/collaborative"
        self.mode = mode
        self.graph = Graph()
        self._inner = CollaborativeOrchestrator(mode)

    def _sync(self) -> None:
        self._inner.nodes = {
            nid: OrchestratorNode(n.id, n.kind, n.payload, n.depends_on)
            for nid, n in self.graph.nodes.items()
        }

    def topo_order(self) -> list:
        self._sync()
        return self._inner.topo_order()

    def run_pipeline(self, exec_fn: Callable[[Node, dict], str]) -> dict:
        self._sync()
        return self._inner.run_pipeline(lambda node, ctx: exec_fn(node, ctx))

    def run_collaborative(self, topic: str, agents: list,
                          round_fn: Callable[[str, str, list], str],
                          rounds: int = 2) -> list:
        return self._inner.run_collaborative(topic, agents, round_fn, rounds)
