"""XAI V2 DAG 规划器

从 engine_xai.py 的 run_workflow 中抽离拓扑排序 + 层级分组逻辑。
Kahn 算法：先计算入度，逐层取出入度为 0 的节点，按字母排序保持输出一致性。
"""

from __future__ import annotations
from typing import Any, Dict, List


class DAGPlanner:
    """DAG 拓扑排序 + 层级分组规划器。"""

    @staticmethod
    def plan(nodes: List[dict], edges: List[dict]) -> List[List[str]]:
        """Kahn 拓扑排序 + 层级分组。

        Args:
            nodes: [{"id","type","label","config":{...}}]
            edges: [{"source","target"}]

        Returns:
            [[nid, nid, ...], [nid, ...], ...]  每层可并行执行的节点 ID 列表
            若存在环路，返回已完成层级 + 未完成标记为空的组（调用方会自行处理）
        """
        if not nodes:
            return []

        node_map: Dict[str, dict] = {n["id"]: n for n in nodes if n.get("id")}
        indeg: Dict[str, int] = {nid: 0 for nid in node_map}
        adj: Dict[str, List[str]] = {nid: [] for nid in node_map}

        for e in edges or []:
            s, t = e.get("source"), e.get("target")
            if s in node_map and t in node_map:
                adj[s].append(t)
                indeg[t] += 1

        levels: List[List[str]] = []
        indeg_copy = dict(indeg)
        remaining: set = set(node_map.keys())

        while remaining:
            batch = sorted([nid for nid in remaining if indeg_copy.get(nid, 0) == 0])
            if not batch:
                # 存在环路：剩余节点无法排入任何层，返回已完成的部分
                break
            levels.append(batch)
            for nid in batch:
                remaining.discard(nid)
                for nxt in adj.get(nid, []):
                    indeg_copy[nxt] = max(0, indeg_copy.get(nxt, 1) - 1)

        return levels
