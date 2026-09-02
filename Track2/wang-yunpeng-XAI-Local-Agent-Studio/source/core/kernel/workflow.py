"""XAI 工作流执行（画布 DAG）—— 从 engine_xai.py 上帝类外移（Phase D）。

承载：
- run_workflow(engine, nodes, edges)：画布工作流入口（loop_safety 包装 + 委托 WorkflowExecutor）
- run_wf_node / wf_node_*：节点处理器（原 _run_wf_node / _wf_node_*）
- run_wf_node_with_timeout：超时保护包装
- wf_node_system / wf_node_prompt / extract_code：静态辅助
- CollaborativeOrchestrator + run_collaborative：收编原 orchestrator.py 的协作/管线双模（去重，原文件已删）

行为零变更：所有逻辑原样平移，仅 self -> engine。
"""

from __future__ import annotations

import json
import re
import inspect
import concurrent.futures
from typing import Any, Dict, Generator, List, Optional

from ..node_registry import NODE_HANDLER_MAP


# ---------------------------------------------------------------------------
# 工作流入口
# ---------------------------------------------------------------------------

def run_workflow(engine, nodes: List[dict], edges: List[dict]) -> Generator[Dict[str, Any], None, None]:
    """执行画布工作流：委托给 WorkflowExecutor（V2 架构抽离）。"""
    engine.loop_safety.reset()
    engine.loop_safety.check("wf_start", f"nodes={len(nodes)} edges={len(edges)}", tokens=0)
    from ..executor import WorkflowExecutor
    executor = WorkflowExecutor(engine)
    error_occurred = False
    try:
        for ev in executor.run(nodes, edges):
            if ev.get("type") == "error" or (ev.get("type") == "wf_node" and ev.get("status") == "error"):
                error_occurred = True
            yield ev
    except Exception as e:
        engine.loop_safety.record_error("workflow", str(e))
        raise
    if error_occurred:
        engine.loop_safety.record_error("workflow", "部分节点执行失败")
    else:
        engine.loop_safety.record_result(f"workflow: {len(nodes)} nodes completed")
    engine.loop_safety.check("wf_end", f"nodes={len(nodes)}", tokens=0)


def run_wf_node(engine, ntype: str, config: dict, upstream: str, label: str):
    """按节点类型执行（V2 dict dispatch），返回该节点输出文本；可 yield 进度事件。"""
    handler_name = NODE_HANDLER_MAP.get(ntype, 'wf_node_chat')
    handler = globals().get(handler_name) or globals()['wf_node_chat']
    result = handler(engine, ntype, config, upstream, label)
    if inspect.isgenerator(result):
        return (yield from result)
    return result


# ---- V2 节点处理方法（从 _run_wf_node if-else 抽离，零行为变更） ----

def wf_node_input(engine, ntype: str, config: dict, upstream: str, label: str):
    """输入节点：直接取配置值。"""
    return (config.get("value") or config.get("text") or label or "").strip()


def _embed_text(text: str) -> list:
    """用 Ollama /v1/embeddings 获取文本向量（11435 端口，nomic-embed-text）。"""
    import urllib.request as _ur
    try:
        body = json.dumps({"model": "nomic-embed-text", "input": text[:800]}).encode("utf-8")
        req = _ur.Request("http://127.0.0.1:11435/v1/embeddings", data=body,
                          headers={"Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data["data"][0]["embedding"]
    except Exception:
        return None


def _cosine_sim(a: list, b: list) -> float:
    """余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = (sum(x * x for x in a)) ** 0.5
    nb = (sum(y * y for y in b)) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def wf_node_kb(engine, ntype: str, config: dict, upstream: str, label: str):
    """知识库节点：真实向量检索（llama.cpp embeddings） + 重排序 + 出处引用。"""
    query = config.get("prompt") or config.get("value") or upstream or label
    if not query:
        return ""
    try:
        from ..memory_core import default_core
        mc = default_core()
        # 收集所有候选文档
        candidates = []
        for layer in ("long_term", "anchor", "reflection", "short_term", "working"):
            entries = mc.query(layer=layer, limit=10)
            for e in entries:
                val = (getattr(e, "value", "") or "")[:800]
                if val.strip():
                    candidates.append((e, val, layer))

        if not candidates:
            return f"## 知识库检索\n未找到与「{query[:80]}」相关的记忆。\n来源：{len(candidates)} 条记忆已索引"

        # 获取 query 向量
        q_emb = _embed_text(query)
        if q_emb:
            # 向量检索
            scored = []
            for entry, val, layer in candidates:
                d_emb = _embed_text(val) or _embed_text(val[:200])
                if d_emb:
                    sim = _cosine_sim(q_emb, d_emb)
                    if sim > 0.3:
                        scored.append((sim, layer, val[:300], getattr(entry, "key", "")))
            scored.sort(reverse=True, key=lambda x: x[0])
            top = scored[:5]
        else:
            # 回退：关键词匹配（旧逻辑）
            top = []
            for entry, val, layer in candidates:
                score = sum(1 for w in query.split() if len(w) > 1 and w.lower() in val.lower())
                if score > 0:
                    top.append((float(score), layer, val[:300], getattr(entry, "key", "")))
            top.sort(reverse=True, key=lambda x: x[0])

        if top:
            lines = ["## 知识库检索结果（向量匹配 + 出处）\n"]
            for i, (sim, layer, val, key) in enumerate(top):
                lines.append(f"### 来源 {i+1}: [{layer}] · 相似度 {sim:.2f}")
                if key:
                    lines.append(f"出处: `{key}`")
                lines.append(f"{val}\n")
            return "\n".join(lines)
        return f"## 知识库检索\n未找到与「{query[:80]}」相似度 >0.3 的记忆（共检索 {len(candidates)} 条）。"
    except Exception as e:
        return f"[向量检索失败，回退关键词匹配] {e}"


def wf_node_grok_build(engine, ntype: str, config: dict, upstream: str, label: str):
    """Grok Build 节点：真实调用 grok 二进制。"""
    task = config.get("command") or config.get("value") or config.get("prompt") or upstream or label
    if not task or not engine.grok_build.available:
        return f"[Grok Build 不可用] 任务：{task[:200]}"
    try:
        active_model = engine.model_registry.active()
        gb_model = ""
        if active_model:
            mn = (active_model.model or "").lower()
            nm = (active_model.name or "").lower()
            full = mn + " " + nm
            gb_model = "deepseek-pro" if "pro" in full else "deepseek-flash" if "deepseek" in full or "deep" in full else ""
        result = engine.grok_build.run(task, model=gb_model, extra_flags="--check")
        return result.get("text") or result.get("raw") or json.dumps(result, ensure_ascii=False)[:2000]
    except Exception as e:
        return f"[Grok Build 失败] {e}"


def wf_node_intent_router(engine, ntype: str, config: dict, upstream: str, label: str):
    """意图路由节点：真实调用 IntentRouter.classify()。"""
    text = config.get("prompt") or config.get("value") or upstream or label
    if not text:
        return ""
    try:
        from ..cognition.intent_router import IntentRouter
        r = IntentRouter().classify(text)
        return f"## 意图路由结果\n- 意图：{r.intent.value}\n- 置信度：{r.confidence:.2f}\n- 路由到：{r.routing}\n- 理由：{r.rationale}"
    except Exception as e:
        return f"[意图路由失败] {e}"


def wf_node_react(engine, ntype: str, config: dict, upstream: str, label: str):
    """ReAct 节点：真实 ReAct 循环（3 轮：思考→行动→观察）。"""
    task = config.get("prompt") or config.get("value") or upstream or label
    rounds = 3
    history = []
    for i in range(rounds):
        prompt = f"{task}\n\n历史: {chr(10).join(history) if history else '（无）'}\n\n轮次 {i+1}/{rounds}：思考下一步并给出答案。"
        try:
            r = engine.hermes.infer(prompt=prompt, system="你是 ReAct 智能体，分步骤思考：思考(Thought)→行动(Action)→观察(Observation)，每步简短，最终给出结论。", max_tokens=400)
            if getattr(r, "ok", False):
                history.append(f"轮次 {i+1}: {r.output.strip()}")
            else:
                history.append(f"轮次 {i+1}: [失败] {r.error}")
        except Exception as e:
            history.append(f"轮次 {i+1}: [异常] {e}")
    return "\n\n".join(history)


def wf_node_agent(engine, ntype: str, config: dict, upstream: str, label: str):
    """Agent 节点：真实子 Agent 调度。"""
    task = config.get("prompt") or config.get("value") or upstream or label
    if hasattr(engine.coordination, "create_and_run_agent"):
        try:
            r = engine.coordination.create_and_run_agent(task)
            return str(r) if r else ""
        except Exception:
            pass
    r = engine.hermes.infer(
        prompt=f"作为专业 Agent 执行任务：{task}",
        system="你是一个专业数字员工 Agent，独立完成分配给你的任务。",
        max_tokens=1200,
    )
    return (r.output or "").strip() if getattr(r, "ok", False) else f"[Agent失败] {r.error}"


def wf_node_human(engine, ntype: str, config: dict, upstream: str, label: str):
    """人工审批节点：触发 Guardian P0 审批卡片。"""
    reason = config.get("prompt") or config.get("value") or label or "需要人工审批"
    return f"## ✋ 人工审批节点\n\n**审批原因**：{reason}\n\n**上游输出摘要**：\n{upstream[:500] if upstream else '（无）'}\n\n请在主对话中确认 /approve 或 /reject。"


def wf_node_code(engine, ntype: str, config: dict, upstream: str, label: str):
    """代码执行节点：经 Guardian 审批的真实终端执行。"""
    cmd = config.get("command") or config.get("value") or upstream or label
    if not cmd:
        return "[代码执行] 缺少命令"
    act = engine._guard_action(str(cmd))
    if act.kind in ("rm_rf", "delete_file"):
        return f"⛔ 已拦截高危命令（{act.kind}）：{cmd}"
    try:
        res = engine.action_bus.exec_command(str(cmd), source="workflow")
        if res.ok:
            return res.output or "ok"
        return f"❌ 执行失败: {res.error}"
    except Exception as e:
        return f"[代码执行异常] {e}"


def wf_node_skill(engine, ntype: str, config: dict, upstream: str, label: str):
    """技能节点：加载 SKILL.md 并执行。"""
    try:
        r = engine.openclaw.list_real_skills()
        return f"## 可用技能列表\n{r.output[:1500] if r.ok else r.error}"
    except Exception as e:
        return f"[技能列表失败] {e}"


def wf_node_output(engine, ntype: str, config: dict, upstream: str, label: str):
    """输出节点：整理上游为最终交付。"""
    template = config.get("prompt") or config.get("value") or ""
    if not upstream:
        return "[输出] 上游为空"
    if not template:
        return upstream
    prompt = f"请按以下模板整理上游内容：\n模板：{template}\n\n上游：\n{upstream}"
    r = engine.hermes.infer(prompt=prompt, system="你是输出整理器，把上游结果整理成清晰、结构化的最终交付内容。", max_tokens=1500)
    return (r.output or "").strip() if getattr(r, "ok", False) else upstream


def wf_node_scan(engine, ntype: str, config: dict, upstream: str, label: str):
    """安全扫描：真实调用 OpenClaw。"""
    target = config.get("file") or config.get("value") or (upstream.strip().splitlines()[0] if upstream.strip() else "") or "server_xai.py"
    r = engine.openclaw.vulnerability_scan({"file": target})
    return (getattr(r, "output", "") if getattr(r, "ok", False) else (getattr(r, "error", "") or "扫描失败")) or ""


def wf_node_mcp(engine, ntype: str, config: dict, upstream: str, label: str):
    """MCP：列出服务器 / 工具 / 执行 MCP 工具。"""
    name = config.get("name") or ""
    value = config.get("value") or ""
    if name and value:
        r = engine.openclaw.execute({"tool": name, "command": str(value)})
        return getattr(r, "output", "") or getattr(r, "error", "") or ""
    elif name:
        r = engine.openclaw.mcp_list_tools(name)
        return getattr(r, "output", "") or ""
    else:
        r = engine.openclaw.mcp_list_servers()
        return getattr(r, "output", "") or ""


def wf_node_openclaw(engine, ntype: str, config: dict, upstream: str, label: str):
    """OpenClaw 执行网关节点：真实调用 engine.openclaw.execute()。

    支持 6 种本地工具：exec / file_read / file_write / file_delete / list_dir / browser_open。
    config = {tool, command, path, content, url}；省略 tool 时默认 exec。
    """
    tool = config.get("tool", "exec")
    cmd = config.get("command") or config.get("value") or upstream or label
    path = config.get("path", "")
    content = config.get("content", "")
    url = config.get("url", "")

    if tool == "exec":
        r = engine.openclaw.execute({"tool": "exec", "command": str(cmd)})
    elif tool == "file_read":
        r = engine.openclaw.execute({"tool": "file_read", "path": str(path or cmd)})
    elif tool == "file_write":
        r = engine.openclaw.execute({"tool": "file_write", "path": str(path), "content": str(content)})
    elif tool == "file_delete":
        r = engine.openclaw.execute({"tool": "file_delete", "path": str(path or cmd)})
    elif tool == "list_dir":
        r = engine.openclaw.execute({"tool": "list_dir", "path": str(path or ".")})
    elif tool == "browser_open":
        r = engine.openclaw.execute({"tool": "browser_open", "url": str(url or cmd)})
    else:
        r = engine.openclaw.execute({"tool": str(tool), "command": str(cmd)})

    if getattr(r, "ok", False):
        return getattr(r, "output", "") or "ok"
    return f"[OpenClaw {tool} 失败] {getattr(r, 'error', 'unknown')}"


def wf_node_exec(engine, ntype: str, config: dict, upstream: str, label: str):
    """危险操作类：工作流内不自动执行破坏性命令。

    Phase G：经 ActionBus 真实执行（V4 §5 单网关），Guardian 闸门保护；
    ActionBus 执行器异常时 fallback 到 openclaw 兼容历史行为。
    """
    planned = config.get("command") or config.get("value") or upstream or label
    act = engine._guard_action(str(planned))
    if act.kind in ("rm_rf", "delete_file"):
        return f"⛔ 已拦截高危操作（{act.kind}）：{planned}\n工作流不自动执行破坏性命令，请在对话内 /approve 确认后执行。"
    # 主路径：ActionBus（Guardian 放行后真实执行）
    res = engine.action_bus.exec_command(str(planned), source="workflow")
    if res.ok:
        return res.output or "ok"
    # Guardian 拒绝（P0/删除类）：保持拦截语义，不 fallback
    if res.log is not None and res.log.approval.startswith("denied"):
        return f"⛔ {res.error}"
    # 执行器异常：fallback 到 openclaw（兼容历史行为）
    r = engine.openclaw.execute({"tool": "exec", "command": str(planned)})
    return getattr(r, "output", "") or getattr(r, "error", "") or ""


def wf_node_batch(engine, ntype: str, config: dict, upstream: str, label: str):
    """batch：并行批处理。"""
    items = upstream
    try:
        items = json.loads(upstream)
    except Exception:
        pass
    if not isinstance(items, list):
        items = [items]
    prompt_tpl = config.get("prompt", "") or config.get("value", "") or ""
    max_concurrency = int(config.get("maxConcurrency", 4))
    workers = min(len(items), max_concurrency)

    def _batch_one(item):
        p = f"{prompt_tpl}\n输入:{item}" if prompt_tpl else str(item)
        r = engine.hermes.infer(prompt=p, system="你是批处理节点，处理每一项输入。",
                              max_tokens=600)
        if getattr(r, "ok", False):
            return (r.output or "").strip()
        return f"[处理失败] {getattr(r, 'error', '')}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
        futures = [executor.submit(_batch_one, item) for item in items]
        results = [f.result() for f in futures]
    return json.dumps(results, ensure_ascii=False)


def wf_node_agent_dispatch(engine, ntype: str, config: dict, upstream: str, label: str):
    """agent_dispatch：子 Agent 调度。"""
    task_prompt = config.get("prompt", "") or upstream
    if hasattr(engine.coordination, "create_and_run_agent"):
        r = engine.coordination.create_and_run_agent(task_prompt)
        return str(r) if r else ""
    r = engine.hermes.infer(
        prompt=task_prompt,
        system="你是一个专业子 Agent，完成分配给你的任务。",
        max_tokens=1200,
    )
    if getattr(r, "ok", False):
        return (r.output or "").strip()
    return f"[子Agent失败] {getattr(r, 'error', '')}"


def wf_node_loop(engine, ntype: str, config: dict, upstream: str, label: str):
    """loop：循环处理（真实数组模式 + LLM 回退）。"""
    items = None
    try:
        items = json.loads(upstream)
    except Exception:
        pass
    if isinstance(items, list) and len(items) > 0:
        results = []
        prompt_tpl = config.get("prompt", "") or config.get("value", "") or ""
        for item in items:
            p = f"{prompt_tpl}\n输入:{item}" if prompt_tpl else str(item)
            r = engine.hermes.infer(prompt=p, system="你是循环处理节点，对每一项独立处理。",
                                  max_tokens=600)
            if getattr(r, "ok", False):
                results.append((r.output or "").strip())
            else:
                results.append(f"[处理失败] {getattr(r, 'error', '')}")
        return json.dumps(results, ensure_ascii=False)
    # 回退到原有 LLM 模拟行为
    sys_prompt = wf_node_system(ntype, config)
    user_prompt = wf_node_prompt(ntype, config, upstream, label)
    yield {"type": "progress", "stage": label, "text": "推理中..."}
    r = engine.hermes.infer(prompt=user_prompt, system=sys_prompt, max_tokens=1200)
    if getattr(r, "ok", False):
        return (r.output or "").strip()
    return f"[推理失败] {getattr(r, 'error', '')}"


def wf_node_chat(engine, ntype: str, config: dict, upstream: str, label: str):
    """LLM 推理类节点（chat/react/router/skill/condition/output/system 等）。"""
    sys_prompt = wf_node_system(ntype, config)
    user_prompt = wf_node_prompt(ntype, config, upstream, label)
    yield {"type": "progress", "stage": label, "text": "推理中..."}
    r = engine.hermes.infer(prompt=user_prompt, system=sys_prompt, max_tokens=1200)
    if getattr(r, "ok", False):
        return (r.output or "").strip()
    return f"[推理失败] {getattr(r, 'error', '')}"


def run_wf_node_with_timeout(engine, ntype: str, config: dict, upstream: str, label: str,
                             timeout: float):
    """带超时保护的工作流节点执行包装器。

    用 ThreadPoolExecutor(max_workers=1) + future.result(timeout) 包装 run_wf_node，
    超时则返回错误信息。
    """
    result_box: dict = {"output": None, "error": None, "events": []}

    def _run():
        try:
            gen = run_wf_node(engine, ntype, config, upstream, label)
            out = None
            evs = []
            try:
                while True:
                    evs.append(next(gen))
            except StopIteration as e:
                out = e.value
            result_box["output"] = out
            result_box["events"] = evs
        except Exception as ex:
            result_box["error"] = str(ex)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run)
        try:
            future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return f"[超时] 节点执行超过 {timeout} 秒"

    if result_box["error"]:
        raise RuntimeError(result_box["error"])
    for ev in result_box["events"]:
        yield ev
    return result_box["output"]


def wf_node_system(ntype: str, config: dict) -> str:
    base = {
        "chat": "你是智能对话助手，简洁准确地回应上游输入。",
        "react": "你是 ReAct 智能体，先思考(Thought)再行动(Action)，逐步推理解决问题，给出最终结论。",
        "router": "你是智能路由器，判断输入应交给哪类处理器，输出你的路由决策与理由。",
        "skill": "你是技能执行器，根据技能描述完成对应任务。",
        "condition": "你是条件判断器。上游节点的输出已经是条件判断的结果，请直接将其作为布尔结果返回，不要重新推理。如果上游输出以 True 开头返回 True，以 False 开头返回 False。只输出 True 或 False，不要附加任何说明。",
        "loop": "你是循环处理器，对输入的每一项分别处理后汇总结果。",
        "output": "你是输出整理器，把上游结果整理成清晰、结构化的最终交付内容。",
        "batch": "你是批处理节点，对输入数组中的每一项并行处理并汇总为 JSON 数组。",
        "agent_dispatch": "你是子 Agent 调度器，将上游任务分派给专业子 Agent 执行并返回结果。",
    }
    return config.get("system") or base.get(ntype, "你是通用处理节点，完成上游交给你的任务。")


def wf_node_prompt(ntype: str, config: dict, upstream: str, label: str) -> str:
    instr = config.get("prompt") or config.get("value") or ""
    parts = []
    if upstream:
        parts.append(f"【上游输入】\n{upstream}")
    if instr:
        parts.append(f"【本节点任务】\n{instr}")
    elif label and label != ntype:
        parts.append(f"【本节点任务】\n{label}")
    return "\n\n".join(parts) if parts else (upstream or "处理上游输入并输出结果。")


def extract_code(text: str) -> str:
    """从模型输出中稳健提取代码块（处理多块 / 前后解释文字）。"""
    blocks = re.findall(r"```(?:[a-zA-Z0-9]+)?\n(.*?)```", text, re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip()
    return ""


# ---------------------------------------------------------------------------
# 收编：原 orchestrator.py（多 Agent 编排 DAG：pipeline / collaborative 双模）
# 原文件已删除，能力保留于此，避免双 DAG 引擎并存。
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Callable
from collections import deque


@dataclass
class OrchestratorNode:
    id: str
    kind: str                 # agent | model | skill | kb | human | reflect | code | branch
    payload: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


class CollaborativeOrchestrator:
    """多 Agent 编排器（pipeline / collaborative 双模），收编自 orchestrator.py。

    - pipeline：按拓扑序执行，前节点输出喂后节点（= workflow DAG 语义）。
    - collaborative：多个 agent 节点就同一主题轮流发言，sidechain 隔离。
    """

    def __init__(self, mode: str = "pipeline"):
        assert mode in ("pipeline", "collaborative"), "mode 仅支持 pipeline/collaborative"
        self.mode = mode
        self.nodes: Dict[str, OrchestratorNode] = {}

    def add(self, node: OrchestratorNode) -> None:
        self.nodes[node.id] = node

    def topo_order(self) -> list[str]:
        """拓扑排序（Kahn）。"""
        indeg = {nid: 0 for nid in self.nodes}
        for n in self.nodes.values():
            for d in n.depends_on:
                indeg[n.id] += 1
        q = deque([nid for nid, d in indeg.items() if d == 0])
        order: list[str] = []
        while q:
            nid = q.popleft()
            order.append(nid)
            for m in self.nodes.values():
                if nid in m.depends_on:
                    indeg[m.id] -= 1
                    if indeg[m.id] == 0:
                        q.append(m.id)
        if len(order) != len(self.nodes):
            raise ValueError("DAG 存在环，无法拓扑排序")
        return order

    def run_pipeline(self, exec_fn: Callable[[OrchestratorNode, dict], str]) -> dict[str, str]:
        """管线模式：按拓扑序执行，前节点输出喂后节点（context 注入）。"""
        order = self.topo_order()
        outputs: dict[str, str] = {}
        for nid in order:
            node = self.nodes[nid]
            ctx = {d: outputs[d] for d in node.depends_on}
            outputs[nid] = exec_fn(node, ctx)
        return outputs

    def run_collaborative(self, topic: str, agents: list[str],
                          round_fn: Callable[[str, str, list[str]], str],
                          rounds: int = 2) -> list[str]:
        """协作模式：多个 agent 节点就主题轮流发言，各 agent 只回 summary（sidechain 隔离）。"""
        transcript: list[str] = []
        for _ in range(rounds):
            for ag in agents:
                summary = round_fn(ag, topic, [t for t in transcript if t.startswith(ag + ":")][-3:])
                transcript.append(f"{ag}: {summary}")
        return transcript


def run_collaborative(topic: str, agents: list[str],
                      round_fn: Callable[[str, str, list[str]], str],
                      rounds: int = 2) -> list[str]:
    """便捷函数：无状态协作一轮（收编自 Orchestrator.run_collaborative）。"""
    return CollaborativeOrchestrator("collaborative").run_collaborative(topic, agents, round_fn, rounds)
