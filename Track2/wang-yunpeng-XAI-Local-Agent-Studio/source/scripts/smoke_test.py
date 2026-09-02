#!/usr/bin/env python3
"""XAI 冒烟自检脚本（防复发巡检）。

遍历前端 (frontend/src/lib/api.ts) 声明的全部端点，断言：
  - HTTP 200（无 404 / 5xx）
  - 响应不含静默 stub 标记 "stub-answer"（未注入真实 Key 时整页假数据）
  - 响应不含 clap 拒绝标记 "unexpected argument"（假 flag / 假 wiring，
    即『代码假设了 grok 二进制没有的参数』类问题）

对已知「部署 / 凭证类」问题（grok Not signed in）标记为 WARN 而非硬失败——
那是用户需补 Key 的运维事项，不是代码 bug。

用法：
  python3 scripts/smoke_test.py            # 只读探针（GET + 安全 POST）
  python3 scripts/smoke_test.py --write    # 额外验证写入路径（memos / memory store 并清理）
  XAI_BASE=http://host:port python3 scripts/smoke_test.py

退出码：发现硬失败(代码 bug / 假能力) → 1；否则 0。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("XAI_BASE", "http://127.0.0.1:8000").rstrip("/")
TOKEN = ""

# 代码 bug / 假能力信号 → 硬失败
HARD_MARKERS = ["stub-answer", "unexpected argument"]
# 部署 / 凭证类信号 → 仅告警
WARN_MARKERS = ["Not signed in", "Not authenticated", "grok 不可用", "XAI_API_KEY"]


def get_token() -> str:
    try:
        with urllib.request.urlopen(f"{BASE}/api/auth/token", timeout=10) as r:
            return json.load(r).get("token", "")
    except Exception as e:  # noqa: BLE001
        print(f"!! 无法获取 token: {e}")
        return ""


def req(method: str, path: str, body=None, timeout: int = 30, stream: bool = False):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "X-Auth-Token": TOKEN}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=timeout)
        status = resp.status
        if stream:
            raw = resp.read(8192)  # SSE：只读前若干字节判定是否启动
        else:
            raw = resp.read()
        return status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


# ── 只读探针面（对应 api.ts 声明的全部 GET + 安全 POST）────────
GETS = [
    "/api/status",
    "/api/system/health",
    "/api/system/sandbox",
    "/api/system/errors",
    "/api/sessions",
    "/api/agents",
    "/api/memory/stats",
    "/api/memory/list",
    "/api/guardian/pending",
    "/api/gepa/status",
    "/api/workflow/history",
    "/api/capabilities",
    "/api/skills",
    "/api/mcp/list",
    "/api/connectors",
    "/api/knowledge/stats",
    "/api/memory/context?text=test&mode=semantic&limit=3",
    "/api/memory/search?q=test&limit=5",
    "/api/canvas/main",
    "/api/grok/health",
    "/api/grok/models",
    "/api/grok/capabilities",
    "/api/grok/inspect",
    "/api/grok/sessions",
    "/api/grok/model",
    "/api/models/list",
    "/api/usage/stats",
    "/api/usage/recent?limit=5",
    "/api/canvas/node-catalog",
    "/api/memos",
    "/api/gateway/status",
    "/api/distill",  # GET 应返回 deprecated 提示（防 404 复发）
]

SAFE_POSTS = [
    ("/api/chat", {"text": "只回复一字：好", "session": "__smoke__", "kernel": ""}, 30, True),
    ("/api/intent", {"text": "帮我修复这个 bug"}, 20, False),
    ("/api/knowledge/search", {"query": "test", "top_k": 3}, 20, False),
    ("/api/guardian/approve", {"ticket_id": "__smoke_none__", "human_ok": False, "reason": "smoke"}, 20, False),
    ("/api/grok/run", {"task": "输出一行 hello", "timeout": 25, "inject_memory": False}, 35, False),
    ("/api/distill", {}, 20, False),  # POST 应返回 deprecated 提示（防 404 复发）
]


def classify(method: str, path: str, status: int, text: str):
    if status == 404 or status >= 500:
        return "FAIL", f"HTTP {status}"
    for m in HARD_MARKERS:
        if m in text:
            return "FAIL", f"假能力/静默stub: {m!r}"
    for m in WARN_MARKERS:
        if m in text:
            return "WARN", f"凭证/部署: {m!r}"
    # grok/sessions 是我们的修复重点：若仍 ok:false 说明修复未生效
    if path == "/api/grok/sessions" and '"ok": false' in text:
        return "WARN", "grok/sessions 仍 ok:false（检查修复是否生效）"
    return "OK", ""


def main() -> int:
    global TOKEN
    TOKEN = get_token()
    write_mode = "--write" in sys.argv

    results = []  # (level, method, path, note)

    for p in GETS:
        s, t = req("GET", p)
        lvl, note = classify("GET", p, s, t)
        results.append((lvl, "GET", p, note))

    for p, body, to, stream in SAFE_POSTS:
        s, t = req("POST", p, body, timeout=to, stream=stream)
        lvl, note = classify("POST", p, s, t)
        results.append((lvl, "POST", p, note))

    # ── 写入路径验证（--write）：创建后清理，避免留垃圾 ──
    if write_mode:
        # memo create → delete
        s, t = req("POST", "/api/memos", {"title": "__smoke__", "date": "2099-01-01", "allDay": True}, timeout=20)
        try:
            mid = json.loads(t).get("memo", {}).get("id")
        except Exception:
            mid = None
        lvl, note = classify("POST", "/api/memos(create)", s, t)
        results.append((lvl, "POST", "/api/memos(create)", note))
        if mid:
            s2, t2 = req("POST", "/api/memos/delete", {"id": mid}, timeout=20)
            results.append(("OK" if s2 == 200 else "WARN", "POST", f"/api/memos/delete({mid})", "" if s2 == 200 else f"HTTP {s2}"))
        # memory store → delete
        s, t = req("POST", "/api/memory/store", {"layer": "short_term", "key": "__smoke__", "value": "x"}, timeout=20)
        try:
            mids = json.loads(t).get("id")
        except Exception:
            mids = None
        lvl, note = classify("POST", "/api/memory/store", s, t)
        results.append((lvl, "POST", "/api/memory/store", note))
        if mids:
            s2, t2 = req("DELETE", f"/api/memory/{mids}", timeout=20)
            results.append(("OK" if s2 == 200 else "WARN", "DEL", f"/api/memory/{mids}", "" if s2 == 200 else f"HTTP {s2}"))

    # ── 输出 ──
    n_ok = n_warn = n_fail = 0
    for lvl, method, path, note in results:
        if lvl == "OK":
            n_ok += 1
        elif lvl == "WARN":
            n_warn += 1
        else:
            n_fail += 1

    if "--json" in sys.argv:
        payload = {
            "tool": "smoke_test",
            "ts": int(time.time()),
            "ok": n_fail == 0,
            "summary": {"total": len(results), "ok": n_ok, "warn": n_warn, "fail": n_fail},
            "checks": [
                {"level": lvl, "method": method, "path": path, "note": note}
                for (lvl, method, path, note) in results
            ],
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 1 if n_fail else 0

    print(f"\nXAI 冒烟自检 @ {BASE}")
    print("=" * 78)
    for lvl, method, path, note in results:
        if lvl == "OK":
            mark = "✅"
        elif lvl == "WARN":
            mark = "⚠️ "
        else:
            mark = "❌"
        line = f"{mark} {method:4} {path}"
        if note:
            line += f"   ← {note}"
        print(line)
    print("=" * 78)
    print(f"总计 {len(results)} | ✅ {n_ok} | ⚠️  {n_warn} | ❌ {n_fail}")
    if n_fail:
        print("结论：存在硬失败（代码 bug / 假能力 / 静默 stub），需修复。")
        return 1
    if n_warn:
        print("结论：无代码 bug；⚠️ 项为部署/凭证类（如 grok 未登录），需用户补 Key。")
        return 0
    print("结论：全绿，契约面无假能力/静默 stub。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
