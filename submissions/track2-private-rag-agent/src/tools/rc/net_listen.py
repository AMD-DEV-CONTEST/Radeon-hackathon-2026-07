# -*- coding: utf-8 -*-
"""监听页面网络请求，捕获 launch API 响应。用法: python net_listen.py <ws_url> <pattern> [out.json]"""
import sys, json, threading
import websocket

def main():
    ws_url, pattern = sys.argv[1], sys.argv[2]
    out_file = sys.argv[3] if len(sys.argv) > 3 else None
    ws = websocket.create_connection(ws_url, timeout=120, suppress_origin=True)
    reqs = {}  # requestId -> method/url
    captured = []

    def send(method, params=None, _id=[0]):
        _id[0] += 1
        ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
        return _id[0]

    def recv_loop(timeout):
        ws.settimeout(timeout)
        while True:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                return
            m = msg.get("method", "")
            if m == "Network.requestWillBeSent":
                reqs[msg["params"]["requestId"]] = msg["params"]["request"]
            elif m == "Network.responseReceived" and pattern in (msg["params"].get("response", {}).get("url", "")):
                rid = msg["params"]["requestId"]
                req = reqs.get(rid, {})
                captured.append({
                    "method": req.get("method"),
                    "url": req.get("url"),
                    "status": msg["params"]["response"].get("status"),
                    "postData": req.get("postData", ""),
                })
                # 抓 body
                body = ws.send(json.dumps({"id": 9999, "method": "Network.getResponseBody", "params": {"requestId": rid}}))
            elif msg.get("id") == 9999 and "result" in msg:
                captured[-1]["body"] = msg["result"].get("body", "")[:2000]
                if out_file:
                    with open(out_file, "w", encoding="utf-8") as f:
                        json.dump(captured, f, ensure_ascii=False, indent=1)
                    print("saved", out_file)
                else:
                    print(json.dumps(captured, ensure_ascii=False, indent=1))

    send("Network.enable")
    send("Page.enable")
    send("Runtime.enable")
    print("listening for", pattern, "Ctrl+C to stop")
    recv_loop(180)

if __name__ == "__main__":
    main()
