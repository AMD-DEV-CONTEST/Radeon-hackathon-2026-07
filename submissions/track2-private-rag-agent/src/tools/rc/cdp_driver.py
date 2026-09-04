# -*- coding: utf-8 -*-
"""CDP 浏览器驱动 —— 通过 Edge 调试端口 9223 操控浏览器。

用法：
  python cdp_driver.py nav <url>          # 导航到 URL
  python cdp_driver.py shot <out.png>     # 截图当前页
  python cdp_driver.py eval '<js>'        # 执行 JS 并打印结果
  python cdp_driver.py dump               # 输出可访问性树（文本）
  python cdp_driver.py txt                # 输出 body 文本
"""
import sys, time, json, base64, os
import urllib.request
import websocket

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WS_TABS = os.environ.get("CDP_PORT") and f"http://127.0.0.1:{os.environ['CDP_PORT']}/json/list" or "http://127.0.0.1:9222/json/list"

def get_tab():
    tabs = json.load(urllib.request.urlopen(WS_TABS, timeout=10))
    # 挑一个非 about:blank 的 page tab，优先 AMD 域名
    for t in tabs:
        if t.get("type") == "page":
            u = t.get("url", "")
            if "developer.amd.com" in u or "radeon" in u:
                return t["webSocketDebuggerUrl"], u
    for t in tabs:
        if t.get("type") == "page" and "about:blank" not in t.get("url", ""):
            return t["webSocketDebuggerUrl"], t.get("url", "")
    return tabs[0]["webSocketDebuggerUrl"], tabs[0].get("url", "")

class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(
            ws_url, timeout=90, enable_multithread=True, suppress_origin=True)
        self._id = 0
    def call(self, method, params=None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                return msg.get("result", {})
    def close(self):
        try: self.ws.close()
        except Exception: pass

def main():
    args = sys.argv[1:]
    ws_url, cur = get_tab()
    c = CDP(ws_url)
    try:
        c.call("Page.enable")
        c.call("Runtime.enable")
        if args and args[0] == "nav":
            c.call("Page.navigate", {"url": args[1]})
            time.sleep(8)
            print("navigated ->", args[1])
        elif args and args[0] == "shot":
            c.call("Page.captureScreenshot", {"format": "jpeg", "quality": 70})
            time.sleep(1)
            # 用缓存拿结果不行，直接重新截图
            res = c.call("Page.captureScreenshot", {"format": "jpeg", "quality": 70})
            with open(args[1], "wb") as f:
                f.write(base64.b64decode(res["data"]))
            print("saved", args[1])
        elif args and args[0] == "eval":
            expr = args[1]
            res = c.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
            if res.get("exceptionDetails"):
                print("EXC:", json.dumps(res["exceptionDetails"].get("text", ""), ensure_ascii=False)[:500])
            print(json.dumps(res.get("result", {}), ensure_ascii=False)[:4000])
        elif args and args[0] == "txt":
            res = c.call("Runtime.evaluate", {
                "expression": "document.body ? document.body.innerText : ''",
                "returnByValue": True})
            v = res.get("result", {}).get("value", "")
            print(v[:4000])
        elif args and args[0] == "url":
            res = c.call("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
            print(res.get("result", {}).get("value", ""))
        else:
            print("current:", cur)
    finally:
        c.close()

if __name__ == "__main__":
    main()
