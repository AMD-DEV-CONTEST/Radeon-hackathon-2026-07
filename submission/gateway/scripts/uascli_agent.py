#!/usr/bin/env python3
"""
UAS CLI Agent Bridge — binds an agent to Gateway WSS for P2P chat.
Usage:
  AGENT_ID=hermes GATEWAY_PASSWORD=xxx python3 uascli_agent.py [--echo]
  
  --echo     Auto-reply mode (echoes messages back)
  --bridge   Bridge mode: writes incoming to /tmp/uascli_{AGENT_ID}_in.json,
             reads response from /tmp/uascli_{AGENT_ID}_out.json
"""
import json
import os
import sys
import time
import threading
import ssl
import traceback

import websocket

# ── Config ──────────────────────────────────────
AGENT_ID = os.environ.get("AGENT_ID", "hermes")
AGENT_NAME = os.environ.get("AGENT_NAME", AGENT_ID)
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://111.228.42.18:8001")
GATEWAY_WS_URL = os.environ.get("GATEWAY_WS_URL", "wss://111.228.42.18:3389")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "")
MODE = "echo" if "--echo" in sys.argv else "bridge" if "--bridge" in sys.argv else "echo"
IN_FILE = f"/tmp/uascli_{AGENT_ID}_in.json"
OUT_FILE = f"/tmp/uascli_{AGENT_ID}_out.json"

# ── Auth ────────────────────────────────────────
def login():
    """Login to Gateway, return token."""
    resp = requests_post(f"{GATEWAY_URL}/auth/login", {
        "username": "admin",
        "password": GATEWAY_PASSWORD
    })
    token = resp.get("token")
    if not token:
        print(f"[FATAL] Login failed: {resp}", file=sys.stderr)
        sys.exit(1)
    print(f"[AUTH] Logged in, token={token[:16]}...")
    return token

def requests_post(url, data):
    """Minimal HTTP POST without external deps."""
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        try:
            return json.loads(body)
        except:
            return {"error": body}
    except Exception as e:
        return {"error": str(e)}

# ── Response handling ───────────────────────────
def build_reply(agent_id, reply_to, content):
    """Build a chat:reply message."""
    return json.dumps({
        "type": "chat:reply",
        "reply_to": reply_to,
        "from_agent": agent_id,
        "content": content
    })

def handle_message(ws, msg):
    """Handle incoming message from Gateway."""
    agent_id = AGENT_ID
    
    if msg.get("type") == "chat:receive":
        from_client = msg.get("from", "unknown")
        content = msg.get("content", "")
        print(f"[CHAT] {from_client} → {agent_id}: {content}")
        
        if MODE == "echo":
            reply = build_reply(agent_id, from_client, f"[{agent_id}] echo: {content}")
            ws.send(reply)
            print(f"[REPLY] {agent_id} → {from_client}: echo sent")
        
        elif MODE == "bridge":
            # Write incoming message to bridge file
            bridge_msg = {
                "type": "chat:receive",
                "from": from_client,
                "agent_id": agent_id,
                "content": content,
                "timestamp": time.time()
            }
            with open(IN_FILE, "w") as f:
                json.dump(bridge_msg, f, indent=2)
            print(f"[BRIDGE] Written to {IN_FILE}")
            
            # Wait for response file
            reply_content = wait_for_response(agent_id, from_client)
            if reply_content:
                reply = build_reply(agent_id, from_client, reply_content)
                ws.send(reply)
                print(f"[REPLY] {agent_id} → {from_client}: sent")
    
    elif msg.get("type") == "task:dispatch":
        print(f"[TASK] Received: {json.dumps(msg, indent=2)[:500]}")
    
    else:
        print(f"[MSG] {msg}")

def wait_for_response(agent_id, from_client, timeout=30):
    """Poll for response file."""
    deadline = time.time() + timeout
    last_mtime = 0
    # Clean up any stale out file
    if os.path.exists(OUT_FILE):
        os.remove(OUT_FILE)
    
    while time.time() < deadline:
        if os.path.exists(OUT_FILE):
            try:
                mtime = os.path.getmtime(OUT_FILE)
                if mtime > last_mtime:
                    time.sleep(0.1)  # Let writer finish
                    with open(OUT_FILE) as f:
                        resp = json.load(f)
                    if resp.get("agent_id") == agent_id and resp.get("reply_to") == from_client:
                        os.remove(OUT_FILE)
                        return resp.get("content")
            except (json.JSONDecodeError, KeyError, OSError):
                pass
        time.sleep(0.5)
    
    print(f"[BRIDGE] No response for {from_client} in {timeout}s, sending timeout")
    return f"[{agent_id}] No response (timeout)"

# ── WebSocket ───────────────────────────────────
def on_message(ws, message):
    try:
        msg = json.loads(message)
        handle_message(ws, msg)
    except json.JSONDecodeError:
        print(f"[RAW] {message[:200]}")

def on_error(ws, error):
    print(f"[WARN] WS error: {error}", file=sys.stderr)

def on_close(ws, close_status_code, close_msg):
    print(f"[WS] Closed: code={close_status_code} msg={close_msg}")

def on_open(ws):
    print(f"[WS] Connected to Gateway as agent '{AGENT_ID}'")
    if MODE == "bridge":
        print(f"[BRIDGE] In: {IN_FILE}  Out: {OUT_FILE}")

def run_ws(token):
    """Connect to Gateway WSS and run event loop."""
    ws_path = f"/agents/{AGENT_ID}/output?token={token}"
    ws_url = GATEWAY_WS_URL + ws_path
    print(f"[WS] Connecting to {ws_url}")
    
    ws = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    
    # TLS: accept self-signed
    ws.run_forever(
        sslopt={"cert_reqs": ssl.CERT_NONE},
        ping_interval=30,
        ping_timeout=10,
    )

# ── Main ────────────────────────────────────────
def main():
    print(f"=== UAS CLI Agent: {AGENT_ID} (mode={MODE}) ===")
    
    if not GATEWAY_PASSWORD:
        print("[FATAL] GATEWAY_PASSWORD not set", file=sys.stderr)
        sys.exit(1)
    
    token = login()
    
    # Clean up old bridge files
    for f in [IN_FILE, OUT_FILE]:
        if os.path.exists(f):
            os.remove(f)
    
    # Connect and run (reconnect on disconnect)
    while True:
        try:
            run_ws(token)
            print("[WS] Disconnected, reconnecting in 3s...")
            time.sleep(3)
        except KeyboardInterrupt:
            print("\n[BYE]")
            break
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    main()
