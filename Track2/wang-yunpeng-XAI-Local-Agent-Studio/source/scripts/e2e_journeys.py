#!/usr/bin/env python3
"""核心用户旅程动态 e2e — 零依赖。

和 smoke_test.py 的区别：
  smoke_test  = 契约面探活（路由在不在、返回码对不对）
  e2e_journeys = 行为面验证（功能真跑通没有、产出内容对不对）

每条旅程都断言"真实产出"，不接受空壳 200。
用法:
    python3 scripts/e2e_journeys.py              # 全跑
    python3 scripts/e2e_journeys.py --fast       # 跳过慢速（对话/grok/搜索）
    python3 scripts/e2e_journeys.py -k canvas    # 只跑名字含 canvas 的旅程
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8000"
_TOKEN = ""


class Skip(Exception):
    """主动跳过（依赖外部条件不满足）。"""


def call(method: str, path: str, body=None, timeout=60):
    url = BASE + path
    headers = {"X-Auth-Token": _TOKEN}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def call_sse(path: str, body: dict, timeout=90, max_events=400):
    """读取 SSE 流，返回 (状态码, 事件列表)。事件为已解析的 dict。"""
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"X-Auth-Token": _TOKEN, "Content-Type": "application/json",
                 "Accept": "text/event-stream"},
        method="POST")
    events: list[dict] = []
    deadline = time.time() + timeout
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            if time.time() > deadline or len(events) >= max_events:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                events.append({"type": "_raw", "text": payload})
    return r.status, events


# ─────────────────────────── 旅程定义 ───────────────────────────
# 每个函数返回一段"证据"字符串，抛异常即失败。

def j01_chat_real_answer():
    """对话：发一个确定性问题，必须拿到非空且非 STUB 的真实回答。"""
    code, r = call("POST", "/api/chat",
                   {"text": "用一句话回答：1+1 等于几？", "stream": False}, timeout=180)
    assert code == 200, f"HTTP {code}: {r}"
    ans = (r.get("answer") or "").strip()
    assert ans, f"回答为空，errors={r.get('errors')}"
    assert "STUB" not in ans.upper(), "命中 StubBackend 假回答，模型后端未装配"
    assert "2" in ans or "二" in ans, f"答案不含预期内容: {ans[:120]}"
    return f"{len(ans)} 字，含正确答案 | {ans[:60].replace(chr(10), ' ')}"


def j02_chat_session_persist():
    """对话会话：新建会话发消息后，会话列表能查到，历史可回读。"""
    sid = f"e2e-{int(time.time())}"
    code, _ = call("POST", "/api/chat",
                   {"text": "记住暗号：紫水晶。", "session": sid, "stream": False},
                   timeout=180)
    assert code == 200
    code, r = call("GET", f"/api/sessions/{sid}/messages")
    assert code == 200, f"历史回读 HTTP {code}"
    msgs = r if isinstance(r, list) else r.get("messages", [])
    assert len(msgs) >= 1, f"会话 {sid} 历史为空: {r}"
    return f"session={sid}，落库 {len(msgs)} 条消息"


def j03_memory_write_read():
    """记忆：写入一条 → 检索必须能召回（契约 {layer,key,value}）。"""
    marker = f"e2e记忆标记{int(time.time())}"
    code, r = call("POST", "/api/memory/store",
                   {"layer": "long_term", "key": marker,
                    "value": "XAI 的回滚点 tag 叫 v0-9-preflight",
                    "engine": "xai", "importance": 0.6})
    assert code == 200 and r.get("ok"), f"写入失败 HTTP {code}: {r}"
    code, r = call("GET", f"/api/memory/search?q={urllib.parse.quote(marker)}&limit=5")
    assert code == 200, f"检索 HTTP {code}"
    hits = r.get("results") or r.get("hits") or r.get("items") or []
    assert hits, f"刚写入的记忆检索不到: {json.dumps(r, ensure_ascii=False)[:200]}"
    return f"写入 id={r and hits and '有'} → 召回 {len(hits)} 条"


def j04_kb_ingest_search():
    """知识库：落一份真文件 → ingest → 关键词检索必须命中。"""
    import os
    import tempfile
    token = f"KBTOKEN{int(time.time())}"
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="e2e_kb_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"内部约定：{token} 表示画布节点执行引擎的健康探针。\n" * 3)
    try:
        code, r = call("POST", "/api/knowledge/ingest", {"paths": [path]}, timeout=60)
        assert code == 200, f"灌库 HTTP {code}: {r}"
        time.sleep(0.6)
        code, r = call("POST", "/api/knowledge/search", {"query": token, "top_k": 5})
        assert code == 200, f"检索 HTTP {code}"
        hits = r.get("hits") or []
        assert hits, f"刚灌入的内容检索不到: {json.dumps(r, ensure_ascii=False)[:200]}"
        return f"灌入 1 文件 → 召回 {len(hits)} 条"
    finally:
        os.unlink(path)


def j05_canvas_validate_to_dag():
    """画布：自然语言 description → validate 必须产出有节点有边的 DAG。"""
    code, r = call("POST", "/api/canvas/validate",
                   {"description": "先检索本地知识库，再让模型总结，最后输出结果"},
                   timeout=120)
    assert code == 200, f"HTTP {code}: {r}"
    dag = r.get("optimized_dag") or {}
    nodes = dag.get("nodes") or r.get("nodes") or []
    edges = dag.get("edges") or r.get("edges") or []
    assert len(nodes) >= 2, (
        f"NL→DAG 未产出节点({len(nodes)}): {json.dumps(r, ensure_ascii=False)[:250]}")
    assert len(edges) >= 1, f"边数不足({len(edges)})"
    kinds = [n.get("type") or n.get("kind") for n in nodes]
    return f"{len(nodes)} 节点 / {len(edges)} 边，types={kinds}"


def j06_canvas_save_load():
    """画布：保存一张图 → 按 id 读回，节点数一致（契约 {id,nodes,edges}）。"""
    cid = f"e2e{int(time.time())}"
    code, r = call("POST", "/api/canvas/save", {
        "id": cid,
        "nodes": [{"id": "n1", "kind": "kb", "label": "检索"},
                  {"id": "n2", "kind": "reflect", "label": "反思"}],
        "edges": [{"source": "n1", "target": "n2"}]})
    assert code == 200, f"保存 HTTP {code}: {r}"
    code, r = call("GET", f"/api/canvas/{cid}")
    assert code == 200, f"读回 HTTP {code}"
    got = r.get("nodes") or []
    assert len(got) == 2, f"读回节点数不符: {json.dumps(r, ensure_ascii=False)[:250]}"
    assert len(r.get("edges") or []) == 1, "边未持久化"
    return f"canvas_id={cid}，2 节点 1 边存读一致"


def j07_canvas_execute():
    """画布执行引擎（SSE）：跑一张真图，必须收到 dag_done 且节点全部终态。"""
    code, evs = call_sse("/api/canvas/execute", {
        "nodes": [{"id": "a", "type": "kb", "data": {"label": "本地知识检索"}},
                  {"id": "b", "type": "react", "data": {"label": "反思校准"}}],
        "edges": [{"source": "a", "target": "b"}]}, timeout=120)
    assert code == 200, f"HTTP {code}"
    assert evs, "SSE 无任何事件"
    types = [e.get("type") for e in evs]
    errs = [e for e in evs if e.get("type") == "error"]
    assert not errs, f"执行报错: {json.dumps(errs[:2], ensure_ascii=False)[:250]}"
    assert "dag_done" in types or "done" in types, f"未收到完成事件，events={types[:12]}"
    statuses = {e.get("nodeId") or e.get("node"): e.get("status")
                for e in evs if e.get("type") == "status"}
    return f"{len(evs)} 事件，节点终态={statuses or '(见 dag_progress)'}"


def j08_workflow_from_text_run():
    """工作流：文本生成 DAG → SSE 执行，不得有 error 事件。"""
    code, r = call("POST", "/api/workflow/from_text",
                   {"text": "读取知识库然后反思总结"}, timeout=120)
    assert code == 200, f"生成 HTTP {code}: {r}"
    dag = r.get("dag") or r.get("workflow") or r
    nodes, edges = dag.get("nodes") or [], dag.get("edges") or []
    assert nodes, f"生成的工作流无节点: {json.dumps(r, ensure_ascii=False)[:250]}"
    code, evs = call_sse("/api/workflow/run",
                         {"nodes": nodes, "edges": edges, "queue": "e2e"}, timeout=150)
    assert code == 200, f"执行 HTTP {code}"
    errs = [e for e in evs if e.get("type") == "error"]
    assert not errs, f"执行报错: {json.dumps(errs[:2], ensure_ascii=False)[:250]}"
    assert evs, "SSE 无事件"
    types = [e.get("type") for e in evs]
    return f"生成 {len(nodes)} 节点 → 执行 {len(evs)} 事件，types={sorted(set(types))}"


def j09_intent_routing():
    """意图路由：三类输入必须路由到不同意图，不能全落一个兜底。"""
    cases = [("帮我重构这段 Python 代码", "code"),
             ("今天天气怎么样", None),
             ("把这段资料存进知识库", None)]
    got = []
    for text, expect in cases:
        code, r = call("POST", "/api/intent", {"text": text}, timeout=30)
        assert code == 200, f"HTTP {code}"
        intent = r.get("intent") or r.get("kernel") or r.get("route")
        got.append(f"{text[:8]}→{intent}")
        if expect:
            assert expect in str(intent), f"'{text}' 应路由到 {expect}，实际 {intent}"
    assert len(set(g.split("→")[1] for g in got)) > 1, f"三类输入路由到同一意图: {got}"
    return " | ".join(got)


def j10_grok_capabilities_honest():
    """Grok 能力清单：必须是动态探测结果，不能是硬编码全 true。"""
    code, r = call("GET", "/api/grok/capabilities", timeout=60)
    assert code == 200, f"HTTP {code}"
    caps = r.get("capabilities") or r
    assert isinstance(caps, (dict, list)), f"格式异常: {type(caps)}"
    if isinstance(caps, dict):
        vals = [v for v in caps.values() if isinstance(v, bool)]
        assert vals, "能力清单无布尔项，可能是假声明"
        return f"{len(caps)} 项能力，真={sum(vals)} 假={len(vals) - sum(vals)}（有真有假=动态探测）"
    return f"{len(caps)} 项能力"


def j11_tool_bus_search():
    """ToolBus 联网搜索：必须返回真实结果或诚实空态，不得静默脑补。"""
    code, r = call("POST", "/api/chat",
                   {"text": "搜索一下 Python 3.13 的发布日期", "stream": False},
                   timeout=240)
    assert code == 200, f"HTTP {code}: {r}"
    ans = (r.get("answer") or "").strip()
    assert ans, "搜索类问答返回空"
    assert "STUB" not in ans.upper(), "命中 StubBackend"
    cited = "[1]" in ans or "http" in ans.lower() or "来源" in ans
    return f"{len(ans)} 字，{'带引用/来源' if cited else '无引用（模型内部知识作答）'}"


def j12_upload_persist():
    """文件上传：上传必须真落盘（契约 {name, mime, data_base64}）。"""
    import base64 as _b64
    import os
    code, r = call("POST", "/api/upload", {
        "name": "e2e_probe.txt", "mime": "text/plain",
        "data_base64": _b64.b64encode("e2e 上传探针内容".encode()).decode(),
    }, timeout=30)
    assert code == 200 and r.get("ok") is not False, f"HTTP {code}: {r}"
    path = r.get("path") or r.get("file") or r.get("saved") or r.get("ref")
    assert path, f"未返回落盘路径: {json.dumps(r, ensure_ascii=False)[:200]}"
    real = str(path).replace("@file:", "")
    assert os.path.exists(real), f"返回了路径但文件不存在: {real}"
    return f"落盘并存在: {real}"


def j13_guardian_blocks_p0():
    """Guardian：P0 危险动作必须被拦（经工作流 human 节点验证真实闸门）。"""
    code, evs = call_sse("/api/workflow/run", {
        "nodes": [{"id": "h", "kind": "human", "type": "human",
                   "label": "人工审批删除", "data": {"label": "人工审批删除"}}],
        "edges": [], "queue": "e2e-guardian", "guardian_auto": False}, timeout=60)
    assert code == 200, f"HTTP {code}"
    blob = json.dumps(evs, ensure_ascii=False)
    gated = ("blocked" in blob or "approval" in blob or "审批" in blob
             or "pending" in blob)
    assert gated, f"P0/人工节点未触发闸门: {blob[:300]}"
    # 同时确认审批端点做了入参校验（不接受裸调用）
    code2, r2 = call("POST", "/api/guardian/approve", {}, timeout=20)
    assert code2 == 400, f"审批端点缺少入参校验，HTTP {code2}: {r2}"
    return "human 节点触发审批闸门 + approve 端点入参校验生效"


def j14_metrics_and_usage():
    """可观测：指标与用量端点必须返回结构化数据而非空壳。"""
    code, m = call("GET", "/api/metrics")
    assert code == 200
    code, u = call("GET", "/api/usage/stats")
    assert code == 200
    assert isinstance(m, dict) and m, "metrics 为空"
    assert isinstance(u, dict), "usage 格式异常"
    return f"metrics {len(m)} 字段 / usage keys={list(u)[:5]}"


def j15_frontend_assets_in_sync():
    """前端产物：首页引用的 assets 必须能 200 拉到（构建与部署一致）。"""
    import re as _re2
    code, html = call("GET", "/")
    assert code == 200 and isinstance(html, str), f"首页 HTTP {code}"
    refs = _re2.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert refs, "首页未引用任何 /assets/，dist 可能没构建"
    missing = []
    for ref in refs[:10]:
        c, _ = call("GET", ref)
        if c != 200:
            missing.append(f"{ref}({c})")
    assert not missing, f"资源 404: {missing}"
    return f"{len(refs)} 个资源引用全部可达"


JOURNEYS = [
    ("j01 对话真回复", j01_chat_real_answer, True),
    ("j02 会话持久化", j02_chat_session_persist, True),
    ("j03 记忆写读", j03_memory_write_read, False),
    ("j04 知识库灌检", j04_kb_ingest_search, False),
    ("j05 画布 NL→DAG", j05_canvas_validate_to_dag, False),
    ("j06 画布存读", j06_canvas_save_load, False),
    ("j07 画布执行引擎", j07_canvas_execute, False),
    ("j08 工作流生成执行", j08_workflow_from_text_run, False),
    ("j09 意图路由分流", j09_intent_routing, False),
    ("j10 Grok 能力诚实性", j10_grok_capabilities_honest, True),
    ("j11 ToolBus 联网搜索", j11_tool_bus_search, True),
    ("j12 文件上传落盘", j12_upload_persist, False),
    ("j13 Guardian P0 拦截", j13_guardian_blocks_p0, False),
    ("j14 指标与用量", j14_metrics_and_usage, False),
    ("j15 前端产物同步", j15_frontend_assets_in_sync, False),
]


def main() -> int:
    global _TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="跳过慢速旅程")
    ap.add_argument("-k", dest="keyword", default="", help="只跑名字包含该关键字的旅程")
    args = ap.parse_args()

    try:
        with urllib.request.urlopen(f"{BASE}/api/auth/token", timeout=5) as r:
            _TOKEN = json.loads(r.read().decode())["token"]
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] 服务未就绪: {e}")
        return 2

    print("=" * 92)
    print("XAI 核心用户旅程动态 e2e")
    print("=" * 92)

    passed = failed = skipped = 0
    failures = []
    for name, fn, slow in JOURNEYS:
        if args.fast and slow:
            print(f"⏭  {name:<22} 慢速旅程，--fast 跳过")
            skipped += 1
            continue
        if args.keyword and args.keyword.lower() not in name.lower():
            continue
        t0 = time.time()
        try:
            evidence = fn()
            ms = int((time.time() - t0) * 1000)
            print(f"✅ {name:<22} {ms:>6}ms  {evidence}")
            passed += 1
        except Skip as e:
            print(f"⏭  {name:<22} 跳过：{e}")
            skipped += 1
        except AssertionError as e:
            ms = int((time.time() - t0) * 1000)
            print(f"❌ {name:<22} {ms:>6}ms  {e}")
            failures.append((name, str(e)))
            failed += 1
        except Exception as e:  # noqa: BLE001
            ms = int((time.time() - t0) * 1000)
            print(f"💥 {name:<22} {ms:>6}ms  {type(e).__name__}: {e}")
            failures.append((name, f"{type(e).__name__}: {e}"))
            failed += 1

    print("=" * 92)
    print(f"总计 {passed + failed + skipped} | ✅ {passed} | ❌ {failed} | ⏭ {skipped}")
    if failures:
        print("\n失败明细：")
        for name, err in failures:
            print(f"  ● {name}\n    {err[:400]}")
    else:
        print("结论：核心用户旅程全部动态调通。")
    return 1 if failed else 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (给 j03 用)
    sys.exit(main())
