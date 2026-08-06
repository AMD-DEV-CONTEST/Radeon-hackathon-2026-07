#!/usr/bin/env python
"""UnionAgents Launcher — WebSocket gateway client for wuying-01.
Handles task execution + agent spawn from gateway dispatch."""
from __future__ import annotations

import argparse, asyncio, json, logging, os, platform, signal, socket, sys, traceback
from datetime import datetime, timezone
from typing import Any
from base64 import b64encode
import urllib.request

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ImportError:
    print("Missing dependency: pip install websockets"); sys.exit(1)

def now_iso(): return datetime.now(timezone.utc).isoformat()

class GatewayDaemon:
    def __init__(self, gateway_url, machine_name, machine_display, location,
                 reconnect_base=2.0, reconnect_max=60.0, heartbeat_interval=30.0):
        self.gateway_url = gateway_url
        self.machine_name = machine_name
        self.machine_display = machine_display
        self.location = location
        self.reconnect_base = reconnect_base
        self.reconnect_max = reconnect_max
        self.heartbeat_interval = heartbeat_interval
        self._stop = False; self._ws = None
        self._logger = logging.getLogger("launcher.daemon")

    async def run(self):
        self._logger.info("daemon start name=%s display=%s", self.machine_name, self.machine_display)
        attempt = 0
        while not self._stop:
            try: await self._session(); attempt = 0
            except asyncio.CancelledError: break
            except Exception: self._logger.error("session crashed:\n%s", traceback.format_exc())
            if self._stop: break
            attempt += 1
            delay = min(self.reconnect_base ** attempt, self.reconnect_max)
            self._logger.info("reconnect in %.1fs (attempt %d)", delay, attempt)
            await asyncio.sleep(delay)
        self._logger.info("daemon stopped"); return 0

    def shutdown(self): self._stop = True

    async def _login(self):
        user = os.environ.get("GATEWAY_USERNAME", "")
        password = os.environ.get("GATEWAY_PASSWORD", "")
        if not user or not password: return None
        try:
            login_url = self.gateway_url.replace("ws://", "http://").split("/ws/")[0] + "/auth/login"
            payload = json.dumps({"username": user, "password": password}).encode()
            req = urllib.request.Request(login_url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                token = json.loads(r.read()).get("token")
                if token:
                    self._logger.info("login ok token=%s...", token[:16]); return token
        except Exception: self._logger.error("login failed:\n%s", traceback.format_exc())
        return None

    async def _session(self):
        token = await self._login()
        if not token: self._logger.error("no token"); await asyncio.sleep(10); return
        ws_url = f"{self.gateway_url}?token={token}"
        self._ws = await websockets.connect(ws_url, ping_interval=20, ping_timeout=10, close_timeout=5)
        self._logger.info("connected")
        try:
            await self._register()
            await asyncio.gather(self._reader(), self._heartbeat_loop())
        except ConnectionClosed as cc:
            self._logger.warning("closed code=%s", cc.code)
        finally:
            if self._ws: await self._ws.close()
            self._ws = None

    async def _register(self):
        payload = {"type":"register","machine_name":self.machine_name,
            "machine_display":self.machine_display,"location":self.location,
            "hostname":socket.gethostname(),"os":platform.system().lower(),
            "python_version":platform.python_version(),"pid":os.getpid(),
            "agent_type":"reasonix","timestamp":now_iso()}
        await self._send(payload)
        self._logger.info("registered display=%s", self.machine_display)

    async def _reader(self):
        async for raw in self._ws:
            try: msg = json.loads(raw)
            except json.JSONDecodeError: continue
            await self._dispatch(msg)

    async def _dispatch(self, msg):
        mt = msg.get("type","")
        self._logger.info("rx %s keys=%s", mt, list(msg.keys())[:6])
        if mt == "ping": await self._send({"type":"pong","timestamp":now_iso()})
        elif mt == "welcome": self._logger.info("welcome: %s", msg.get("message",""))
        elif mt == "task": await self._handle_task(msg)
        elif mt == "spawn": await self._handle_spawn(msg)
        elif mt == "shutdown": self._logger.info("shutdown requested"); self._stop = True
        elif mt == "error": self._logger.error("gw error: %s", msg.get("message",""))
        else: self._logger.debug("unhandled type=%s", mt)

    async def _handle_task(self, msg):
        tid = msg.get("task_id","?"); ttl = msg.get("title","")
        cmd = msg.get("command",""); cwd = msg.get("cwd")
        self._logger.info("TASK id=%s title=%s cmd=%.120s", tid, ttl, cmd)
        await self._send({"type":"task_ack","task_id":tid,"status":"running","timestamp":now_iso()})
        if not cmd:
            await self._send({"type":"task_result","task_id":tid,"status":"fail","output":"no command","timestamp":now_iso()})
            return
        try:
            proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            out = (stdout+stderr).decode("utf-8","replace")[-4000:]
            st = "pass" if proc.returncode==0 else "fail"
            self._logger.info("TASK done id=%s status=%s exit=%d", tid, st, proc.returncode)
            await self._send({"type":"task_result","task_id":tid,"status":st,"output":out,"exit_code":proc.returncode,"timestamp":now_iso()})
        except asyncio.TimeoutError:
            self._logger.warning("TASK timeout id=%s", tid)
            await self._send({"type":"task_result","task_id":tid,"status":"fail","output":"timeout 300s","timestamp":now_iso()})
        except Exception as e:
            self._logger.error("TASK error id=%s: %s", tid, e)
            await self._send({"type":"task_result","task_id":tid,"status":"fail","output":str(e),"timestamp":now_iso()})

    async def _handle_spawn(self, msg):
        name = msg.get("agent_name","?"); at = msg.get("agent_type","generic")
        self._logger.info("SPAWN name=%s type=%s", name, at)
        await self._send({"type":"spawn_ack","agent_name":name,"agent_type":at,"status":"attempting","timestamp":now_iso()})
        try:
            cmd = msg.get("command","") or ("npx reasonix serve --addr 127.0.0.1:8787" if at=="reasonix" else "echo unknown agent_type")
            proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await asyncio.sleep(1.5)
            if proc.returncode is None:
                self._logger.info("SPAWN ok name=%s pid=%d", name, proc.pid)
                await self._send({"type":"spawn_result","agent_name":name,"agent_type":at,"status":"ok","pid":proc.pid,"timestamp":now_iso()})
            else:
                await self._send({"type":"spawn_result","agent_name":name,"agent_type":at,"status":"fail","timestamp":now_iso()})
        except Exception as e:
            self._logger.error("SPAWN fail name=%s: %s", name, e)
            await self._send({"type":"spawn_result","agent_name":name,"agent_type":at,"status":"fail","error":str(e),"timestamp":now_iso()})

    async def _heartbeat_loop(self):
        while not self._stop:
            await asyncio.sleep(self.heartbeat_interval)
            try: await self._send({"type":"heartbeat","machine_name":self.machine_name,"timestamp":now_iso()})
            except Exception: break

    async def _send(self, payload):
        if self._ws is None: return
        await self._ws.send(json.dumps(payload, ensure_ascii=False))

def build_parser():
    p = argparse.ArgumentParser(description="UnionAgents Launcher")
    p.add_argument("--gateway-url", required=True)
    p.add_argument("--machine-name", default=socket.gethostname())
    p.add_argument("--machine-display", default=socket.gethostname())
    p.add_argument("--location", default="unknown")
    p.add_argument("--log-path", default="launcher.log")
    p.add_argument("--heartbeat-interval", type=float, default=30.0)
    p.add_argument("--reconnect-max", type=float, default=60.0)
    return p

def setup_logging(log_path):
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)])

async def main_async(args):
    d = GatewayDaemon(gateway_url=args.gateway_url, machine_name=args.machine_name,
        machine_display=args.machine_display, location=args.location,
        heartbeat_interval=args.heartbeat_interval, reconnect_max=args.reconnect_max)
    return await d.run()

def main():
    args = build_parser().parse_args()
    setup_logging(args.log_path)
    try: return asyncio.run(main_async(args))
    except KeyboardInterrupt: return 0

if __name__ == "__main__":
    raise SystemExit(main())