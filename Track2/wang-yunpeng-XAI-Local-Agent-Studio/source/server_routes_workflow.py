"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_xai import _ACTIVE_QUEUES, _queues_lock, _threading, _diagnose, _emit_event, _record_workflow_run  # import * 会跳过下划线名，需显式导入
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_workflow(h):
    """执行画布工作流：接收 {nodes, edges}，SSE 逐节点流式反馈真实执行。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        body = h.rfile.read(length).decode("utf-8")
        data = json.loads(body)
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        queue = data.get("queue") or "default"
    except Exception:
        h._json_response(400, {"error": "无效请求体，需要 JSON: {\"nodes\":[...],\"edges\":[...]}"})
        return

    if not isinstance(nodes, list) or not isinstance(edges, list):
        h._json_response(400, {"error": "nodes / edges 必须为数组"})
        return

    # 同 queue 名的后一个请求覆盖前一个
    cancel_ev = _threading.Event()
    with _queues_lock:
        if queue in _ACTIVE_QUEUES:
            _ACTIVE_QUEUES[queue]["cancel"].set()
        _ACTIVE_QUEUES[queue] = {"cancel": cancel_ev, "start_ts": time.time()}

    engine = get_engine()
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("Connection", "close")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.end_headers()
    h.close_connection = True
    start_ts = time.time()
    events: list[dict] = []
    # 注入活跃队列列表到 SSE
    with _queues_lock:
        qs = list(_ACTIVE_QUEUES.keys())
    if qs:
        h.wfile.write(f"data: {json.dumps({'type': 'active_queues', 'queues': qs}, ensure_ascii=False)}\n\n".encode("utf-8"))
        h.wfile.flush()

    try:
        for ev in engine.run_workflow(nodes, edges):
            if cancel_ev.is_set():
                yield_ev = {"type": "wf_done", "result": f"队列 {queue} 被新请求覆盖，已取消"}
                line = f"data: {json.dumps(yield_ev, ensure_ascii=False)}\n\n"
                h.wfile.write(line.encode("utf-8"))
                h.wfile.flush()
                h.wfile.write(b"data: [DONE]\n\n")
                h.wfile.flush()
                events.append(yield_ev)
                break
            if ev.get("status") == "error" or ev.get("type") == "error":
                error_msg = str(ev.get("output") or ev.get("error") or "")
                ev["diagnosis"] = _diagnose(error_msg)
            elif ev.get("status") == "done":
                out = str(ev.get("output", ""))
                if any(w in out.lower() for w in ("error", "失败", "超时", "不可用", "不存在", "not found", "command not")):
                    ev["diagnosis"] = _diagnose(out)
            events.append(ev)
            line = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            h.wfile.write(line.encode("utf-8"))
            h.wfile.flush()
            _emit_event(ev)
        h.wfile.write(b"data: [DONE]\n\n")
        h.wfile.flush()
        _record_workflow_run(len(nodes), len(edges), events, start_ts)

    except Exception as e:
        try:
            err = f"data: {json.dumps({'type': 'error', 'error': str(e), 'diagnosis': _diagnose(str(e))}, ensure_ascii=False)}\n\n"
            h.wfile.write(err.encode("utf-8"))
            h.wfile.flush()
        except Exception:
            pass
        _record_workflow_run(len(nodes), len(edges), events, start_ts)
    finally:
        with _queues_lock:
            if _ACTIVE_QUEUES.get(queue, {}).get("cancel") is cancel_ev:
                del _ACTIVE_QUEUES[queue]

def _handle_workflow_from_text(h):
    """POST /api/workflow/from_text → 从自然语言生成工作流 DAG
    
    支持两种模式：
    - 普通模式（stream=false）：返回完整 JSON {ok, dag}
    - 流式模式（stream=true）：SSE 逐节点发射 wf_node_spawn 事件
    """
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8"))
        text = data.get("text", "")
        stream = data.get("stream", False)
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {\"text\": \"...\"}"})
        return
    if not text:
        h._json_response(400, {"error": "text 不能为空"})
        return

    engine = get_engine()
    # 节点类型词表取自执行器别名表（单一事实源），杜绝"生成器造得出、执行器认不得"。
    from core.canvas.executor import NODE_TYPE_ALIASES
    allowed_types = ", ".join(sorted(NODE_TYPE_ALIASES))
    prompt = (
        f"根据以下需求，生成一个工作流 DAG（最多 8 个节点）。\n"
        f"可用节点类型（只能用这些）：{allowed_types}\n\n"
        f"需求：{text}\n\n"
        f"返回严格 JSON：\n"
        f'{{"nodes":[{{"id":"n1","type":"input","label":"输入","config":{{}}}},...],"edges":[{{"source":"n1","target":"n2"}},...]}}\n'
        f"必填：id(n1,n2...), type, label, config（空对象即可）。直接输出 JSON。"
    )
    # 稳健解析 + 一次严格重试（详见 core/workflow_gen.py 头注释）
    from core.workflow_gen import generate_dag_verbose
    dag, raw = generate_dag_verbose(engine, prompt, max_tokens=1500)
    if not dag:
        msg = "模型未返回有效 DAG JSON（已重试一次）"
        if stream:
            h._sse_error(msg, raw[:300])
        else:
            h._json_response(500, {"error": msg, "raw": raw[:300]})
        return

    if stream:
        h._workflow_from_text_sse(dag, text)
    else:
        h._json_response(200, {"ok": True, "dag": dag})

def register(router) -> None:
    router.add("POST", "/api/workflow/run", _handle_workflow)
    router.add("POST", "/api/workflow/from_text", _handle_workflow_from_text)
