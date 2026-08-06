"""Canvas DSL —— 画布 JSON ↔ Plan DSL 双向转换器。

约束：
- DSL 是派生态，不动 SQLite 画布存储。
- 往返转换必须无损：canvas → dsl → canvas 完全一致。
- 不引入新依赖。
"""

from __future__ import annotations

import json
import copy
from typing import Any, Dict, List, Optional
from collections import defaultdict, deque


def canvas_to_plan(nodes: List[dict], edges: List[dict]) -> dict:
    """画布 DAG → AI 可执行的 Plan DSL。

    返回:
      {
        "dag": { "nodes": [...], "edges": [...] },
        "execution_plan": { "levels": [[n1], [n2,n3]], "critical_path": [...] },
        "mermaid": "graph LR\\n  n1-->n2\\n  n2-->n3",
        "stats": { "node_count": 3, "edge_count": 2, "max_depth": 2 }
      }
    """
    nodes_copy = []
    for n in nodes:
        nc = {"id": n["id"], "type": n.get("type", "chat"),
              "label": n.get("data", {}).get("label", "") or n.get("type", ""),
              "config": n.get("data", {}).get("config", {}),
              "deps": []}
        nodes_copy.append(nc)

    id_to_node = {n["id"]: n for n in nodes_copy}
    adj: Dict[str, List[str]] = defaultdict(list)
    indeg: Dict[str, int] = defaultdict(int)
    for e in edges:
        src, tgt = e["source"], e["target"]
        adj[src].append(tgt)
        indeg[tgt] = indeg.get(tgt, 0) + 1
        if src in id_to_node:
            id_to_node[src]["deps"].append(tgt)

    # 拓扑分层
    levels: List[List[str]] = []
    queue = deque([n["id"] for n in nodes_copy if indeg.get(n["id"], 0) == 0])
    visited: set = set()
    while queue:
        level = list(queue)
        levels.append(level)
        next_q = deque()
        for nid in level:
            visited.add(nid)
            for tgt in adj.get(nid, []):
                indeg[tgt] -= 1
                if indeg[tgt] == 0 and tgt not in visited:
                    next_q.append(tgt)
        queue = next_q

    # 遗漏节点（环路）
    for n in nodes_copy:
        if n["id"] not in visited:
            levels.append([n["id"]])

    # 关键路径（取最长）
    critical: List[str] = []
    for level in levels:
        if level:
            critical.append(level[0])

    # Mermaid 生成
    mermaid_lines = ["graph TD"]
    for n in nodes_copy:
        safe_label = n["label"].replace('"', "'")[:30]
        mermaid_lines.append(f'  {n["id"]}["{safe_label}"]')
    for e in edges:
        mermaid_lines.append(f'  {e["source"]} --> {e["target"]}')
    mermaid = "\n".join(mermaid_lines)

    return {
        "dag": {"nodes": nodes_copy, "edges": list(edges)},
        "execution_plan": {
            "levels": levels,
            "critical_path": critical,
        },
        "mermaid": mermaid,
        "stats": {
            "node_count": len(nodes_copy),
            "edge_count": len(edges),
            "max_depth": len(levels),
        }
    }


def plan_to_canvas(plan: dict) -> tuple[List[dict], List[dict]]:
    """Plan DSL → 画布 nodes + edges（往返无损）。

    返回: (nodes, edges) 可直写画布。
    """
    dag = plan.get("dag", {})
    plan_nodes = dag.get("nodes", [])
    plan_edges = dag.get("edges", [])

    nodes = []
    for pn in plan_nodes:
        n = {
            "id": pn["id"],
            "type": pn.get("type", "chat"),
            "position": pn.get("position", {"x": 0, "y": 0}),
            "data": {
                "kind": pn.get("type", "chat"),
                "label": pn.get("label", pn.get("type", "")),
                "config": pn.get("config", {}),
                "status": "idle",
                "nodeId": pn["id"],
            }
        }
        nodes.append(n)

    edges = [{"id": f"e{i}", "source": e["source"], "target": e["target"]}
             for i, e in enumerate(plan_edges)]

    return nodes, edges


def detect_cycle(nodes: List[dict], edges: List[dict],
                new_source: str, new_target: str) -> bool:
    """检测插入 new_source→new_target 后是否形成环路（委托给 detect_cycle_with_edges）。"""
    node_ids = {n["id"] for n in nodes}
    return detect_cycle_with_edges(edges, node_ids, new_source, new_target)


def detect_cycle_with_edges(edges: List[dict], node_ids: set,
                            new_source: str, new_target: str) -> bool:
    """基于边列表做环路检测。

    edges: 现有边列表 [{"source":"A","target":"B"}, ...]
    node_ids: 所有节点 ID 集合
    new_source, new_target: 待插入边

    返回: True = 有环，拒绝插入。
    """
    adj: Dict[str, List[str]] = defaultdict(list)
    all_ids = node_ids | {new_source, new_target}
    for e in edges:
        adj[e["source"]].append(e["target"])
    adj[new_source].append(new_target)

    # 拓扑排序 BFS
    indeg: Dict[str, int] = defaultdict(int)
    for src in adj:
        for tgt in adj[src]:
            indeg[tgt] = indeg.get(tgt, 0) + 1

    queue = deque([nid for nid in all_ids if indeg.get(nid, 0) == 0])
    visited = 0
    while queue:
        nid = queue.popleft()
        visited += 1
        for tgt in adj.get(nid, []):
            indeg[tgt] -= 1
            if indeg[tgt] == 0:
                queue.append(tgt)

    return visited != len(all_ids)
