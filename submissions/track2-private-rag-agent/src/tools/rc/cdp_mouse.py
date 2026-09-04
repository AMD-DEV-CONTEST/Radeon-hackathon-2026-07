# -*- coding: utf-8 -*-
"""CDP 真实鼠标点击/拖动。用法: python cdp_mouse.py <ws_url> click <x> <y> [--db] | drag <x1> <y1> <x2> <y2> <steps>"""
import sys, json, time
import websocket

def main():
    ws_url = sys.argv[1]
    op = sys.argv[2]
    ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
    _id = [0]

    def call(method, params=None):
        _id[0] += 1
        ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == _id[0]:
                return msg.get("result", {})

    call("Input.enable")
    call("Runtime.enable")

    if op == "click":
        x, y = int(sys.argv[3]), int(sys.argv[4])
        db = len(sys.argv) > 5 and sys.argv[5] == "--db"
        call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        time.sleep(0.1)
        call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 2 if db else 1})
        time.sleep(0.05)
        call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 2 if db else 1})
        print(f"clicked {x},{y}")
    elif op == "drag":
        x1, y1, x2, y2 = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
        steps = int(sys.argv[7]) if len(sys.argv) > 7 else 20
        call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x1, "y": y1})
        call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x1, "y": y1, "button": "left", "clickCount": 1})
        for i in range(1, steps + 1):
            x = x1 + (x2 - x1) * i // steps
            y = y1 + (y2 - y1) * i // steps
            call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left", "buttons": 1})
            time.sleep(0.01)
        call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x2, "y": y2, "button": "left", "clickCount": 1})
        print(f"dragged {x1},{y1} -> {x2},{y2}")
    ws.close()

if __name__ == "__main__":
    main()
