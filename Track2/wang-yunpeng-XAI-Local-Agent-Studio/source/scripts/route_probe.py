#!/usr/bin/env python3
"""全路由探活探针 — 零依赖。

用法:
    python3 scripts/route_probe.py            # 只探 GET
    python3 scripts/route_probe.py --post     # 连 POST 一起探（幂等安全的那些）

输出: 路由健康矩阵（状态码 / 耗时 / 是否 JSON），并按问题分级汇总。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000"
ROOT = Path(__file__).resolve().parent.parent


def get_token() -> str:
    with urllib.request.urlopen(f"{BASE}/api/auth/token", timeout=5) as r:
        return json.loads(r.read().decode())["token"]


def collect_router_routes() -> list[tuple[str, str]]:
    """从 server_routes_*.py 抽取 router.add 注册的路由。"""
    pat = re.compile(r'router\.add\(\s*"([A-Z]+)"\s*,\s*"([^"]+)"')
    out: set[tuple[str, str]] = set()
    for f in sorted(ROOT.glob("server_routes_*.py")):
        for m in pat.finditer(f.read_text(encoding="utf-8")):
            out.add((m.group(1), m.group(2)))
    return sorted(out)


def collect_legacy_get() -> list[tuple[str, str]]:
    """从 server_xai.py 的 do_GET 抽取 legacy 分支路径。"""
    src = ROOT.joinpath("server_xai.py").read_text(encoding="utf-8")
    start = src.find("def do_GET")
    end = src.find("\n    def ", start + 10)
    body = src[start:end if end > 0 else len(src)]
    out: set[tuple[str, str]] = set()
    for m in re.finditer(r'path == "(/api/[^"]*)"', body):
        out.add(("GET", m.group(1)))
    for m in re.finditer(r'path\.startswith\("(/api/[^"]*)"\)', body):
        p = m.group(1)
        if p.endswith("/"):
            continue  # 需要动态 id，单独处理
        out.add(("GET", p))
    return sorted(out)


# 需要动态参数的路由 → 提供安全样例
PARAM_SAMPLES = {
    "/api/memory/search": "/api/memory/search?q=test&limit=3",
    "/api/memory/context": "/api/memory/context?text=test",
    "/api/canvas": "/api/canvas/main",
    "/api/events/stream": None,  # SSE 长连接，跳过
    "/api/open": None,           # 会拉起外部程序，跳过
}

# 幂等安全的 POST（不产生破坏性副作用）
SAFE_POST = {
    "/api/canvas/validate": {"text": "读文件然后总结"},
    "/api/intent": {"text": "你好"},
}


def probe(method: str, path: str, token: str, body=None, timeout=12):
    url = BASE + path
    data = None
    headers = {"X-Auth-Token": token}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(4096)
            ms = int((time.time() - t0) * 1000)
            is_json = False
            try:
                json.loads(raw.decode("utf-8", "replace"))
                is_json = True
            except Exception:
                pass
            return r.status, ms, is_json, ""
    except urllib.error.HTTPError as e:
        ms = int((time.time() - t0) * 1000)
        detail = e.read(300).decode("utf-8", "replace").replace("\n", " ")[:160]
        return e.code, ms, False, detail
    except Exception as e:  # noqa: BLE001
        ms = int((time.time() - t0) * 1000)
        return 0, ms, False, f"{type(e).__name__}: {e}"[:160]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true", help="同时探测幂等安全的 POST")
    args = ap.parse_args()

    try:
        token = get_token()
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] 拿不到 token，服务可能没起: {e}")
        return 2

    router = collect_router_routes()
    legacy = collect_legacy_get()
    legacy_only = [r for r in legacy if r not in set(router)]
    overlap = [r for r in legacy if r in set(router)]

    print(f"router 注册: {len(router)} 条 | legacy GET: {len(legacy)} 条 "
          f"(其中 {len(overlap)} 条与 router 重叠)")
    if overlap:
        print(f"  重叠(legacy 死分支): {', '.join(p for _, p in overlap)}")
    print()

    rows, skipped = [], []
    targets = [(m, p, "router") for m, p in router if m == "GET"]
    targets += [(m, p, "legacy") for m, p in legacy_only]

    for method, path, src in sorted(targets, key=lambda x: x[1]):
        if path in PARAM_SAMPLES:
            sample = PARAM_SAMPLES[path]
            if sample is None:
                skipped.append((path, "长连接/副作用，主动跳过"))
                continue
            path_to_call = sample
        else:
            path_to_call = path
        code, ms, is_json, detail = probe(method, path_to_call, token)
        rows.append((src, method, path, code, ms, is_json, detail))

    if args.post:
        for path, body in SAFE_POST.items():
            code, ms, is_json, detail = probe("POST", path, token, body)
            rows.append(("router", "POST", path, code, ms, is_json, detail))

    print(f"{'来源':<7} {'方法':<5} {'路径':<38} {'码':<5} {'ms':>6}  说明")
    print("-" * 110)
    bad = []
    for src, method, path, code, ms, is_json, detail in rows:
        flag = "" if 200 <= code < 300 else "  <<<"
        if not (200 <= code < 300):
            bad.append((path, code, detail))
        print(f"{src:<7} {method:<5} {path:<38} {code:<5} {ms:>6}  "
              f"{'json' if is_json else '':<5}{detail}{flag}")

    for path, why in skipped:
        print(f"{'skip':<7} {'GET':<5} {path:<38} {'-':<5} {'-':>6}  {why}")

    print("-" * 110)
    ok = len(rows) - len(bad)
    print(f"合计 {len(rows)} 条：{ok} 通过 / {len(bad)} 异常 / {len(skipped)} 跳过")
    if bad:
        print("\n异常清单:")
        for path, code, detail in bad:
            print(f"  [{code}] {path}  {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
