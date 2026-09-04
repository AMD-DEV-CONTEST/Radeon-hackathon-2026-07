# -*- coding: utf-8 -*-
"""连接指定 tab 的 CDP 脚本。用法: python cdp_tab.py <ws_url> 'eval js' | txt"""
import sys, json, base64
import urllib.request
import websocket

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def call(ws, method, params=None, _id=[0]):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == _id[0]:
            return msg.get("result", {})

def main():
    ws_url = sys.argv[1]
    op = sys.argv[2]
    expr = sys.argv[3] if len(sys.argv) > 3 else ""
    ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
    try:
        call(ws, "Runtime.enable")
        if op == "eval":
            r = call(ws, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
            v = r.get("result", {})
            if "value" in v:
                print(json.dumps(v["value"], ensure_ascii=False))
            else:
                print(json.dumps(v, ensure_ascii=False))
        elif op == "txt":
            r = call(ws, "Runtime.evaluate", {"expression": "document.body?document.body.innerText:''", "returnByValue": True})
            print(r.get("result", {}).get("value", ""))
        elif op == "shot":
            r = call(ws, "Page.captureScreenshot", {"format": "jpeg", "quality": 70})
            with open(expr, "wb") as f:
                f.write(base64.b64decode(r["data"]))
            print("saved", expr)
    finally:
        ws.close()

if __name__ == "__main__":
    main()
