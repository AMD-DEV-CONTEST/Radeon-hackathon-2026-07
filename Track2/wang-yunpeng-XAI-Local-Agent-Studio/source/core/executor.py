"""XAI V2 工作流执行器

从 engine_xai.py 中抽离 run_workflow 方法到 WorkflowExecutor 类。
保留 Kahn 拓扑排序、层级分组并行调度、guardLevel 三级穿透、
condition 分支跳转、loop 循环等全部原有逻辑，零行为变更。

P0 阶段：engine 实例通过构造函数注入，_wf_node_xxx 方法仍在此实例上。

DSL: wf_node_spawn 支持 AI 扩展节点，默认关闭。
"""
from __future__ import annotations

# ---- 自动生成节点开关（AI 自主扩展画布） ----
ENABLE_AUTO_SPAWN = False  # 设为 True 启用 AI 动态生成节点

import json
import concurrent.futures
from typing import Any, Dict, Generator, List

from .planner import DAGPlanner
from .kernel.workflow import run_wf_node_with_timeout


class WorkflowExecutor:
    """工作流执行器 —— 将 run_workflow 逻辑整体抽离到独立类。"""

    def __init__(self, engine):
        """engine: XAIEngine 实例，提供 _run_wf_node_with_timeout 等回调。"""
        self.engine = engine

    def run(self, nodes: List[dict], edges: List[dict]) -> Generator[Dict[str, Any], None, None]:
        """执行画布工作流：拓扑排序后按节点类型真实执行，逐节点流式反馈。

        入参
          nodes: [{"id","type","label","config":{...}}]
          edges: [{"source","target"}]  source/target 为节点 id
        事件
          wf_start / wf_node(running|done|error) / progress / wf_done / error
        """
        # B1: 读取 settings（execTimeout / defaultModelId / maxConcurrency）
        exec_timeout: float = 120.0
        default_model_id: str = ""
        max_concurrency: int = 5
        try:
            from .app_store import AppStore as _AppStore
            _store = _AppStore()
            exec_timeout = float(_store.settings_get_value("execTimeout") or 120)
            default_model_id = str(_store.settings_get_value("defaultModelId") or "")
            max_concurrency = int(_store.settings_get_value("maxConcurrency") or 5)
        except Exception:
            pass

        yield {"type": "wf_start", "total": len(nodes)}

        if not nodes:
            yield {"type": "error", "error": "工作流为空，请先拖入节点"}
            return

        node_map = {n["id"]: n for n in nodes if n.get("id")}
        indeg = {nid: 0 for nid in node_map}
        adj: Dict[str, List[str]] = {nid: [] for nid in node_map}
        preds: Dict[str, List[str]] = {nid: [] for nid in node_map}
        for e in edges or []:
            s, t = e.get("source"), e.get("target")
            if s in node_map and t in node_map:
                adj[s].append(t)
                preds[t].append(s)
                indeg[t] += 1

        # D2: 拓扑层级分组（用于并行调度）—— 委托给 DAGPlanner
        levels = DAGPlanner.plan(nodes, edges)
        if not levels and node_map:
            yield {
                "type": "wf_node", "nid": "", "status": "error",
                "output": "工作流存在环路，剩余 " + str(len(node_map)) + " 个节点无法执行"
            }

        outputs: Dict[str, dict] = {}
        final_parts: List[str] = []
        skip_set: set = set()  # C2: condition 分支跳转集合
        node_index: int = 0
        total_nodes: int = len(node_map)

        # D2: 按层级并行执行
        for batch in levels:
            # 过滤掉被 condition 跳过的节点
            active = [nid for nid in batch if nid not in skip_set]
            if not active:
                continue

            # 准备每个节点的执行参数
            node_params: Dict[str, tuple] = {}
            for nid in active:
                node = node_map[nid]
                config = node.get("config") or {}
                ntype = node.get("type", "")
                label = node.get("label") or ntype
                upstream = "\n\n".join(
                    (outputs.get(p) or {}).get("value", "") for p in preds.get(nid, []) if outputs.get(p)
                )
                node_params[nid] = (ntype, config, upstream, label)
                node_index += 1
                yield {
                    "type": "wf_node", "node_id": nid, "status": "running",
                    "index": node_index, "total": total_nodes,
                    "label": label, "ntype": ntype,
                }

            # 同层级节点并行执行
            batch_results: Dict[str, tuple] = {}

            def _exec_one(nid: str):
                ntype, config, upstream, label = node_params[nid]
                events: list = []
                out_val = None
                error_val = None

                def _try_run():
                    nonlocal out_val, error_val, events
                    events = []
                    try:
                        gen = run_wf_node_with_timeout(
                            self.engine, ntype, config, upstream, label, exec_timeout,
                        )
                        try:
                            while True:
                                events.append(next(gen))
                        except StopIteration as e:
                            out_val = e.value
                    except Exception as ex:
                        error_val = str(ex)

                # P1-3: 失败自动重试，最多 2 次，指数退避 1s / 2s
                import time as _time
                max_retries = 2
                for retry in range(max_retries + 1):
                    _try_run()
                    if error_val is None:
                        break
                    if retry < max_retries:
                        delay = 1.0 * (2 ** retry)  # 1s, 2s
                        _time.sleep(delay)
                        # 重试时输出覆盖；等待后继续下一轮

                return nid, events, out_val, error_val

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
                futures = {executor.submit(_exec_one, nid): nid for nid in active}
                for future in concurrent.futures.as_completed(futures):
                    nid, events, out_val, error_val = future.result()
                    batch_results[nid] = (events, out_val, error_val)

            # 按原始顺序处理结果（保持输出一致性）
            for nid in active:
                events, out_val, error_val = batch_results[nid]
                node = node_map[nid]
                ntype = node.get("type", "")
                label = node.get("label") or ntype

                # 透传子节点产生的事件
                for ev in events:
                    yield ev

                # C1: 节点失败不中断，设置错误输出
                if error_val is not None:
                    out_val = f"[错误: {error_val}]"
                    outputs[nid] = {"value": out_val, "type": "text", "node": nid}
                    yield {
                        "type": "wf_node", "node_id": nid, "status": "error",
                        "label": label, "ntype": ntype, "output": error_val,
                    }
                    continue

                out_val = out_val or ""
                out_str = str(out_val)
                try:
                    json.loads(out_str)
                    data_type = "json"
                except Exception:
                    data_type = "list" if "\n" in out_str and len(out_str) > 80 else "text"
                outputs[nid] = {"value": out_str, "type": data_type, "node": nid}
                yield {
                    "type": "wf_node", "node_id": nid, "status": "done",
                    "label": label, "ntype": ntype, "output": out_str[:1200],
                    "data_type": data_type,
                }

                # DSL: AI 自主扩展节点（默认关闭，受 ENABLE_AUTO_SPAWN 控制）
                if ENABLE_AUTO_SPAWN and ntype in ("kb", "chat") and out_str:
                    spawn_node = {
                        "type": "wf_node_spawn",
                        "parent_id": nid,
                        "new_node": {
                            "id": f"{nid}_spawn_1",
                            "type": "chat",
                            "label": f"分析: {label[:20]}",
                            "config": {"prompt": f"分析以下内容的关键点\\n{out_str[:200]}"},
                        },
                        "edge": {"source": nid, "target": f"{nid}_spawn_1"},
                        "spawn_reason": f"节点 {label} 完成，AI 建议扩展分析",
                    }
                    yield spawn_node

                if not adj.get(nid) and out_str:
                    final_parts.append(f"### {label}\n{out_str}")

                # C2: condition 分支跳转
                if ntype == "condition":
                    out_stripped = str(out_val).strip()
                    edges_list = adj.get(nid, [])
                    if out_stripped.startswith("True") and len(edges_list) >= 1:
                        # 只沿第一个出边，跳过其他
                        for i, target in enumerate(edges_list):
                            if i != 0:
                                skip_set.add(target)
                    elif out_stripped.startswith("False") and len(edges_list) >= 2:
                        # 只沿第二个出边，跳过其他
                        for i, target in enumerate(edges_list):
                            if i != 1:
                                skip_set.add(target)
                    # 否则所有出边都走（不设置 skip）

        # D3: 环路检测：检查是否有节点未被调度
        scheduled_ids = {nid for batch in levels for nid in batch}
        unscheduled = {nid for nid in node_map if nid not in scheduled_ids}
        if unscheduled:
            yield {
                "type": "wf_node", "nid": "", "status": "error",
                "output": f"工作流存在环路，{len(unscheduled)} 个节点无法执行: {', '.join(sorted(unscheduled))}"
            }

        result = "\n\n".join(final_parts) if final_parts else "工作流已执行完毕（无终端输出节点）。"
        yield {"type": "wf_done", "result": result[:4000]}
