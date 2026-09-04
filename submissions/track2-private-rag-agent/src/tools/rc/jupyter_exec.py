# -*- coding: utf-8 -*-
"""在 Radeon Cloud JupyterLab 实例上执行命令（通过 Jupyter kernel websocket）。

用法：
  python tools/rc/jupyter_exec.py "import torch; print(torch.cuda.is_available())"
  python tools/rc/jupyter_exec.py --code "!rocminfo | head -20" --timeout 180
"""
import argparse
import base64
import json
import sys
import time
import uuid

import websocket

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://developer.amd.com.cn/radeon/instances/u-7102-1179e4d5"
TOKEN = "amd-oneclick"
COOKIE_PATH = "tools/rc/rc_cookies.txt"


def _session_cookie():
    raw = open(COOKIE_PATH, encoding="utf-8").read().strip()
    return "session=" + raw.split("session=")[1].split(";")[0]


def _http_json(method, path, payload=None):
    import urllib.request
    session = _session_cookie()
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Cookie": session,
    })
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def execute(code, timeout=120, kernel_id=None):
    """在实例上执行一段 Python 代码，返回 (stdout, stderr, error)。"""
    session = _session_cookie()
    # 1. 启动 kernel（未指定时）
    if kernel_id is None:
        spec = _http_json("POST", f"/api/kernels?token={TOKEN}",
                          {"name": "python3"})
        kernel_id = spec["id"]
    # 2. 连 websocket
    ws_url = (BASE.replace("https://", "wss://") +
              f"/api/kernels/{kernel_id}/channels?token={TOKEN}")
    ws = websocket.create_connection(
        ws_url, timeout=timeout, suppress_origin=True, header=[
            "Cookie: " + session,
            "Origin: https://developer.amd.com.cn",
        ])
    # 3. 发 execute_request
    msg_id = str(uuid.uuid4())
    msg = {
        "header": {"msg_id": msg_id, "username": "", "session": str(uuid.uuid4()),
                   "msg_type": "execute_request", "version": "5.3"},
        "parent_header": {}, "metadata": {},
        "content": {"code": code, "silent": False, "store_history": False,
                    "user_expressions": {}, "allow_stdin": False,
                    "stop_on_error": True},
        "channel": "shell", "buffers": [],
    }
    ws.send(json.dumps(msg))
    out = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            break
        except Exception:
            break
        try:
            ev = json.loads(raw)
        except Exception:
            continue
        if ev.get("parent_header", {}).get("msg_id") != msg_id:
            continue
        content = ev.get("content", {})
        if ev.get("msg_type") == "stream":
            out.append(("stdout" if content.get("name") == "stdout" else "stderr",
                        content.get("text", "")))
        elif ev.get("msg_type") == "execute_result":
            data = content.get("data", {})
            out.append(("result", data.get("text/plain", "")))
        elif ev.get("msg_type") == "error":
            out.append(("error", "\n".join(content.get("traceback", []))[-2000:]))
        elif ev.get("msg_type") == "status" and content.get("execution_state") == "idle":
            break
    try:
        ws.close()
    except Exception:
        pass
    stdout = "".join(t for k, t in out if k == "stdout")
    stderr = "".join(t for k, t in out if k == "stderr")
    errors = [t for k, t in out if k == "error"]
    return stdout, stderr, "\n".join(errors), kernel_id


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("code", nargs="?", default=None)
    ap.add_argument("--code", dest="code_opt", default=None)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--kernel", default=None)
    args = ap.parse_args()
    code = args.code or args.code_opt
    if not code:
        print(__doc__)
        sys.exit(1)
    stdout, stderr, err, kid = execute(code, timeout=args.timeout,
                                       kernel_id=args.kernel)
    print("=== STDOUT ===")
    print(stdout)
    if stderr:
        print("=== STDERR ===")
        print(stderr[-2000:])
    if err:
        print("=== ERROR ===")
        print(err[-2000:])
    print(f"=== kernel={kid} ===")
