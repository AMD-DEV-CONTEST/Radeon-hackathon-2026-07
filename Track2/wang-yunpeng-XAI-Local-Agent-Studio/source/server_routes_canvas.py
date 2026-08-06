"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_canvas_save(h):
    """POST /api/canvas/save → 保存画布。body: {id|canvas_id, nodes, edges}。

    修复（2026-08-04）：此前只认 `id`，客户端传 `canvas_id` 时会被静默忽略并
    整份写到 "main" —— 返回 200 且 `{"id": "main"}`，调用方以为存好了，实际
    覆盖了公共画布、自己的画布一个字没落。属"静默数据错位"，比报错更危险。
    现同时接受 canvas_id 别名；两者皆缺才回落 main（保持向后兼容）。
    """
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8"))
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {id|canvas_id, nodes, edges}"})
        return
    cid = (data.get("id") or data.get("canvas_id") or "main")
    h._json_response(200, app_store.canvas_save(cid, data.get("nodes"), data.get("edges")))

def _handle_canvas_validate(h):
    """POST /api/canvas/validate → AI 只读评估画布 DAG 可行性。

    支持两种模式：
    1. {nodes, edges} — 校验现有画布
    2. {description} — 从自然语言描述生成 DAG 建议（对话→画布联动）

    返回 {valid, issues[], suggestions[], optimized_dag}。
    """
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8"))
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        description = data.get("description", "")
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {nodes, edges} 或 {description}"})
        return

    # 点 6：从自然语言描述生成 DAG
    if description and not nodes:
        engine = get_engine()
        # 可用类型直接取自执行器的别名表——单一事实来源，杜绝
        # "生成器造得出、执行器认不得" 的词表漂移（2026-08-04）。
        from core.canvas.executor import NODE_TYPE_ALIASES
        allowed_types = ", ".join(sorted(NODE_TYPE_ALIASES))
        prompt = (
            f"根据以下画布变更需求，生成一个工作流 DAG（最多 8 个节点）。\n"
            f"可用节点类型（只能用这些）：{allowed_types}\n\n"
            f"需求：{description}\n\n"
            f"返回严格 JSON：\n"
            f'{{"nodes":[{{"id":"n1","type":"input","label":"输入","config":{{}}}},...],"edges":[{{"source":"n1","target":"n2"}},...]}}\n'
            f"必填：id(n1,n2...), type, label, config（空对象即可）。直接输出 JSON。"
        )
        # 稳健抽取 + 一次严格重试：模型偶发先输出推演文字再给 JSON，
        # 旧的贪婪正则会抓到推演里的 {} 而解析失败，功能直接不可用。
        from core.workflow_gen import generate_dag
        dag = generate_dag(engine, prompt)
        if dag:
            nodes = dag.get("nodes", [])
            edges = dag.get("edges", [])
        if not nodes:
            h._json_response(200, {
                "valid": False,
                "issues": [{"severity": "error", "node": "", "msg": "无法从描述生成 DAG"}],
                "suggestions": [],
                "optimized_dag": None,
            })
            return

    from core.canvas_dsl import canvas_to_plan, detect_cycle_with_edges
    issues: list[dict] = []
    suggestions: list[dict] = []

    # 基础校验
    if not nodes:
        issues.append({"severity": "error", "node": "", "msg": "画布为空，至少需要一个节点"})
    if not edges and len(nodes) > 1:
        issues.append({"severity": "warning", "node": "", "msg": "多个节点未连线，可能无法按预期执行"})

    # 未连线节点检测
    connected = set()
    for e in edges:
        connected.add(e["source"])
        connected.add(e["target"])
    for n in nodes:
        nid = n["id"]
        if nid not in connected and len(nodes) > 1:
            issues.append({"severity": "warning", "node": nid, "msg": f"节点 {nid} 未连线，不会被触发执行"})

    # 环路检测
    node_ids = {n["id"] for n in nodes}
    has_cycle = False
    try:
        plan = canvas_to_plan(nodes, edges)
        if len(plan["execution_plan"]["levels"]) < len(node_ids):
            has_cycle = True
    except Exception:
        has_cycle = True
    if has_cycle:
        issues.append({"severity": "error", "node": "", "msg": "画布存在环路，无法执行"})

    # 建议：无 kb/chart 起点时建议加 input 节点
    if nodes and not any(n.get("type") in ("input", "kb", "chat") for n in nodes):
        suggestions.append({"action": "add_node", "type": "input",
                            "msg": "建议添加一个输入节点作为流程起点",
                            "position": {"x": 40, "y": 40}})

    valid = not any(i["severity"] == "error" for i in issues)
    optimized_dag = None
    if valid and nodes:
        try:
            optimized_dag = canvas_to_plan(nodes, edges)
        except Exception:
            optimized_dag = None
        # 契约修正（2026-08-04）：canvas_to_plan 返回 {dag, execution_plan}，
        # 而消费方（ChatConsole「AI 主动布局」）读的是 optimized_dag.nodes /
        # .edges。此前该字段恒为 undefined，导致"对话自动落 DAG 到画布"从未生效。
        # 这里把节点/边平铺进去，同时保留原有嵌套结构向后兼容。
        if optimized_dag is None:
            optimized_dag = {}
        optimized_dag.setdefault("nodes", nodes)
        optimized_dag.setdefault("edges", edges)

    h._json_response(200, {
        "valid": valid,
        "issues": issues,
        "suggestions": suggestions,
        # 顶层也平铺一份，供不想钻 optimized_dag 的调用方直接使用
        "nodes": nodes,
        "edges": edges,
        "optimized_dag": optimized_dag,
    })

def _handle_canvas_execute(h):
    """POST /api/canvas/execute — SSE 流式执行画布节点。

    Body JSON: { nodeId, session? } 或 { nodes, edges, session? } (DAG 模式)。
    事件类型：status(节点状态变更) / log(执行日志) / done / error / dag_start / dag_progress / dag_done。
    """
    try:
        length = int(h.headers.get("Content-Length", "0"))
        body = json.loads(h.rfile.read(length).decode("utf-8"))
    except Exception:
        h._json_response(400, {"error": "需要 JSON"})
        return

    node_id = body.get("nodeId")
    nodes = body.get("nodes")
    edges = body.get("edges")
    session = body.get("session", "")
    dag_mode = bool(not node_id and nodes)

    engine = None
    try:
        engine = get_engine()
    except Exception as e:
        h._json_response(500, {"error": f"无法获取引擎: {e}"})
        return

    # SSE 头
    # 注意（2026-08-04 修复）：execute_dag/execute_node 返回的是**完整事件列表**，
    # 不是长连接推流。此前发 Connection: keep-alive 且写完不关流，客户端（浏览器
    # 画布"执行"按钮、curl、任何 SSE reader）会一直等后续数据 → 永久转圈。
    # 对齐 /api/workflow/run 的做法：显式 Connection: close + close_connection。
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("Connection", "close")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("X-Accel-Buffering", "no")
    h.end_headers()
    h.close_connection = True

    try:
        from core.canvas.executor import execute_node, execute_dag

        if dag_mode:
            events = execute_dag(engine, nodes, edges, session)
        else:
            node = {"id": node_id, "type": body.get("type") or body.get("kind"),
                    "data": body.get("data", {})}
            events = execute_node(engine, node, session)

        for ev in events:
            h.wfile.write(ev.encode("utf-8"))
        h.wfile.flush()
    except Exception as e:
        from core.canvas.executor import sse_event
        err = sse_event("error", {"message": f"执行引擎异常: {e}"})
        h.wfile.write(err.encode("utf-8"))
        h.wfile.flush()


def _handle_canvas_node_catalog(h):
    """GET /api/canvas/node-catalog — 节点注册表（4 类节点 + 工具实例）。"""
    try:
        from core.canvas.node_catalog import build_catalog
        eng = None
        try:
            eng = get_engine()
        except Exception:
            pass
        h._json_response(200, build_catalog(eng, _CAPABILITIES))
    except Exception as e:
        h._json_response(500, {"error": f"获取节点目录失败: {e}"})


def register(router) -> None:
    router.add("POST", "/api/canvas/save", _handle_canvas_save)
    router.add("POST", "/api/canvas/validate", _handle_canvas_validate)
    router.add("POST", "/api/canvas/execute", _handle_canvas_execute)
    router.add("GET", "/api/canvas/node-catalog", _handle_canvas_node_catalog)
