# -*- coding: utf-8 -*-
"""CDP 原生键盘输入 + 点击。用法: python cdp_type.py <ws_url> select <css> type <text>"""
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

    call("Runtime.enable")
    call("Page.enable")
    call("Input.enable")

    if op == "select":
        sel = sys.argv[3]
        r = call("Runtime.evaluate", {"expression": f"""
            (function(){{
              var el=document.querySelector({json.dumps(sel)});
              if(!el) return false;
              el.focus();
              el.click();
              return true;
            }})()
        """, "returnByValue": True})
        print("selected:", r.get("result", {}).get("value"))
    elif op == "type":
        text = sys.argv[3]
        # 先全选清空
        call("Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": 2, "key": "a", "code": "KeyA"})
        call("Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": 2, "key": "a", "code": "KeyA"})
        time.sleep(0.2)
        call("Input.insertText", {"text": text})
        print("typed:", text)
    elif op == "key":
        # 回车
        call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter"})
        call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter"})
        print("pressed Enter")
    ws.close()

if __name__ == "__main__":
    main()
