#!/usr/bin/env python3
"""XAI 核心接口有界压测（T1 · 补性能验收）

设计原则：
  - 有界、保守，默认不发大水（避免误伤运行中的实例 / 烧模型配额）。
  - 同时测「廉价读路径」(/api/memory) 与「核心写路径」(/api/chat/send、/api/intent)。
  - 输出 RPS / p50 / p95 / 错误率，作为 六维验收·维度二 的真实证据。

用法：
  python3 scripts/loadtest_core.py                      # 默认保守档
  python3 scripts/loadtest_core.py --chat 20 --chat-c 10 --intent 20 --intent-c 10 --memory 200 --memory-c 30
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

TOKEN = open(os.path.expanduser("~/.xai/.server_token")).read().strip()
BASE = "http://127.0.0.1:8000"
HDR = {"Content-Type": "application/json", "X-Auth-Token": TOKEN}


def _req(method: str, path: str, body: bytes | None):
    t0 = time.time()
    req = urllib.request.Request(BASE + path, data=body, headers=HDR, method=method)
    from urllib.parse import urlencode
    return t0, urllib.request.urlopen(req, timeout=90)


def hit_chat(_):
    try:
        _, r = _req("POST", "/api/chat/send",
                    json.dumps({"text": "ping", "session": "loadtest"}).encode())
        r.read()
        return time.time()  # placeholder, real dt below
    except Exception as e:
        return ("ERR", str(e)[:90])


def hit_chat_timed(_):
    t0 = time.time()
    try:
        req = urllib.request.Request(BASE + "/api/chat/send",
                                     data=json.dumps({"text": "ping", "session": "loadtest"}).encode(),
                                     headers=HDR, method="POST")
        r = urllib.request.urlopen(req, timeout=90)
        r.read()
        return (time.time() - t0) * 1000
    except Exception as e:
        return ("ERR", str(e)[:90])


def hit_intent_timed(_):
    t0 = time.time()
    try:
        req = urllib.request.Request(BASE + "/api/intent",
                                     data=json.dumps({"text": "帮我查一下天气"}).encode(),
                                     headers=HDR, method="POST")
        r = urllib.request.urlopen(req, timeout=90)
        r.read()
        return (time.time() - t0) * 1000
    except Exception as e:
        return ("ERR", str(e)[:90])


def hit_memory_timed(_):
    t0 = time.time()
    try:
        req = urllib.request.Request(BASE + "/api/memory", headers=HDR, method="GET")
        r = urllib.request.urlopen(req, timeout=15)
        r.read()
        return (time.time() - t0) * 1000
    except Exception as e:
        return ("ERR", str(e)[:90])


def run(name: str, fn, n: int, c: int):
    print(f"\n=== {name}: {n} 请求 / {c} 并发 ===")
    errs = 0
    lats: list[float] = []
    with ThreadPoolExecutor(max_workers=c) as ex:
        t0 = time.time()
        for res in ex.map(fn, range(n)):
            if isinstance(res, tuple):
                errs += 1
            else:
                lats.append(res)
        dt = time.time() - t0
    if lats:
        lats.sort()
        p50 = lats[int(len(lats) * 0.5)]
        p95 = lats[int(len(lats) * 0.95)] if len(lats) > 1 else lats[-1]
        print(f"  成功 {len(lats)}/{n}  错误 {errs}  用时 {dt:.2f}s  RPS={n / dt:.1f}")
        print(f"  延迟 p50={p50:.1f}ms  p95={p95:.1f}ms  max={lats[-1]:.1f}ms")
    else:
        print(f"  全部失败 ({errs}) — 检查服务端是否在线 / 令牌是否有效")
    return {"name": name, "n": n, "c": c, "ok": len(lats), "err": errs,
            "rps": round(n / dt, 1) if dt else 0,
            "p50": round(lats[int(len(lats) * 0.5)], 1) if lats else 0,
            "p95": round(p95, 1) if lats else 0}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, default=6)
    ap.add_argument("--chat-c", type=int, default=3)
    ap.add_argument("--intent", type=int, default=6)
    ap.add_argument("--intent-c", type=int, default=3)
    ap.add_argument("--memory", type=int, default=150)
    ap.add_argument("--memory-c", type=int, default=20)
    a = ap.parse_args()

    results = []
    results.append(run("POST /api/chat/send（核心对话，触发模型推理）", hit_chat_timed, a.chat, a.chat_c))
    results.append(run("POST /api/intent（意图识别）", hit_intent_timed, a.intent, a.intent_c))
    results.append(run("GET  /api/memory（廉价读路径）", hit_memory_timed, a.memory, a.memory_c))

    print("\n=== 汇总 ===")
    for r in results:
        print(f"  {r['name']:<48} RPS={r['rps']:<7} p50={r['p50']}ms p95={r['p95']}ms 成功={r['ok']}/{r['n']} 错误={r['err']}")
