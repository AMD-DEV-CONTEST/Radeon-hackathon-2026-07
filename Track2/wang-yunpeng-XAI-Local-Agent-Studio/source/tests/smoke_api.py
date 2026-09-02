#!/usr/bin/env python3
"""XAI 后端 API 冒烟测试（无第三方依赖，urllib 实现）。

用法:
    python3 tests/smoke_api.py [base_url]

base_url 默认 http://localhost:8000
"""
import json
import sys
import urllib.request
import urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def _req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode()
            try:
                return r.status, raw, json.loads(raw)
            except Exception:
                return r.status, raw, None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), None


FAILED = False


def check(name: str, cond: bool):
    global FAILED
    print(("PASS " if cond else "FAIL ") + "- " + name)
    if not cond:
        FAILED = True


def main():
    # 1. status
    st, _, d = _req("GET", "/api/status")
    check("GET /api/status -> 200", st == 200)
    check("status 含 xai_engine 字段", bool(d and d.get("xai_engine")))

    # 2. capabilities
    st, _, d = _req("GET", "/api/capabilities")
    check("GET /api/capabilities -> 200", st == 200)
    check("capabilities >= 10 个内核节点", bool(d and len(d.get("capabilities", [])) >= 10))

    # 3. intent (含 kernel 路由)
    st, _, d = _req("POST", "/api/intent", {"text": "帮我写一个 Python 快排函数"})
    check("POST /api/intent -> 200", st == 200)
    check(
        "intent 返回有效 kernel",
        bool(d and d.get("kernel") in ("hermes", "grok_build", "openclaw")),
    )

    # 4. workflow run (SSE，input -> chat -> output)
    st, raw, _ = _req(
        "POST",
        "/api/workflow/run",
        {
            "nodes": [
                {"id": "n1", "type": "input", "data": {"label": "起点"}},
                {"id": "n2", "type": "chat", "data": {"label": "问好", "prompt": "hi"}},
                {"id": "n3", "type": "output", "data": {"label": "输出"}},
            ],
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
        },
    )
    check("POST /api/workflow/run -> 200", st == 200)
    check("workflow 流含 wf_done 完成标记", "wf_done" in raw)

    # 5. plans CRUD
    st, _, _ = _req(
        "POST",
        "/api/plans",
        {
            "title": "smoke-plan",
            "nodes": [
                {"id": "n1", "type": "input", "position": {"x": 1, "y": 1}, "data": {"label": "a", "config": {}}}
            ],
            "edges": [],
        },
    )
    check("POST /api/plans -> 200", st == 200)
    st, _, d = _req("GET", "/api/plans")
    check("GET /api/plans -> 200", st == 200)
    check("plans 返回列表", bool(d and isinstance(d.get("plans"), list)))

    print()
    if FAILED:
        print("SMOKE FAILED")
        sys.exit(1)
    print("SMOKE PASSED")


if __name__ == "__main__":
    main()
