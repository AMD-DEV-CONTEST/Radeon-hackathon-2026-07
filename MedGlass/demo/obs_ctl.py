#!/usr/bin/env python3
"""Control OBS via obs-websocket v5 (CreateScene/CreateInput/Start/Stop)."""
import asyncio, base64, hashlib, json, sys
import websockets

HOST = "127.0.0.1:4456"
PASSWORD = "medglass-demo"

async def call(ws, req_type, data=None, rid="1"):
    await ws.send(json.dumps({"op": 6, "d": {
        "requestType": req_type, "requestId": rid, "requestData": data or {}}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("op") == 7 and msg.get("d", {}).get("requestId") == rid:
            return msg["d"]

async def main():
    async with websockets.connect(f"ws://{HOST}") as ws:
        hello = json.loads(await ws.recv())
        auth = hello["d"].get("authentication", {})
        ident = {"op": 1, "d": {"rpcVersion": 1}}
        if auth:
            secret = base64.b64encode(
                hashlib.sha256((PASSWORD + auth["salt"]).encode()).digest()).decode()
            auth_str = base64.b64encode(
                hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()
            ident["d"]["authentication"] = auth_str
        await ws.send(json.dumps(ident))
        await ws.recv()
        r = await call(ws, "GetVersion")
        rd = r.get("responseData", {})
        print("connected, obs-websocket", rd.get("obsWebSocketVersion"), "rpc", rd.get("rpcVersion"))

        if "--start" in sys.argv:
            r = await call(ws, "CreateScene", {"sceneName": "Demo"})
            print("CreateScene:", r.get("requestStatus", {}).get("result"), r.get("requestStatus", {}).get("comment") or "")
            r = await call(ws, "CreateInput", {
                "sceneName": "Demo",
                "inputName": "Screen",
                "inputKind": "pipewire-screen-capture-source",
                "inputSettings": {"cursor": True},
            })
            print("CreateInput:", r.get("requestStatus", {}).get("result"), r.get("requestStatus", {}).get("comment") or "")
            r = await call(ws, "SetCurrentProgramScene", {"sceneName": "Demo"})
            print("SetScene:", r.get("requestStatus", {}).get("result"))
            await asyncio.sleep(1)
            r = await call(ws, "StartRecord")
            print("StartRecording:", r.get("requestStatus", {}).get("result"), r.get("requestStatus", {}).get("comment") or "")
            print("RECORDING_STARTED")
        elif "--stop" in sys.argv:
            r = await call(ws, "StopRecord")
            print("StopRecording:", r.get("requestStatus", {}).get("result"), r.get("requestStatus", {}).get("comment") or "")
            print("RECORDING_STOPPED")

asyncio.run(main())
