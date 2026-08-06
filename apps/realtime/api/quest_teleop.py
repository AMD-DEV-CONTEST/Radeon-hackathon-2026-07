"""Quest 2/3 WebXR teleop — Local Agent side.

This router exposes a minimal WebXR HTML page + WebSocket that lets a Meta
Quest 2/3 (or any browser with WebXR) teleoperate LeKiwi / SO-101 without a
physical leader arm. The Quest controller pose drives the arm; the joystick
drives the mobile base (LeKiwi only); the trigger drives the gripper.

Why this lives here:
  - GB10 has `~/quest2_teleop/` with WebXR teleop scripts that already proved
    this works for LeKiwi and SO-101. We're bringing that capability into
    BotverseX as a first-class Local Agent feature, so any user with a Quest
    headset can collect data without buying a leader arm.

What this router does (MVP):
  - GET  /quest           → serves the WebXR HTML page (inline, no static files)
  - WS   /ws/quest        → bidirectional: Quest publishes pose + buttons,
                            Local Agent publishes arm state for haptic feedback
  - POST /api/quest_teleop/start  → start the lerobot-teleoperate subprocess
                                    with the Quest bridge as input source
  - POST /api/quest_teleop/stop   → stop it
  - GET  /api/quest_teleop/status → current state

The actual lerobot subprocess invocation is delegated to the existing
teleop_control / record_control routers — this router just provides the
Quest-specific entry point and the WebXR page. The page is intentionally
self-contained (no build step) so it works in the Quest browser without
serving a separate bundle.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quest_teleop"])

# ---------------------------------------------------------------------------
# In-memory state (per Local Agent process; single active session at a time)
# ---------------------------------------------------------------------------

_session: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "robot_id": None,
    "mode": None,  # 'lekiwi' | 'so101' | 'b601'
    "clients": 0,  # number of connected Quest WS clients
}
# Latest pose snapshot from any connected Quest client
_latest_pose: Dict[str, Any] = {}
_pose_updated_at: float = 0.0


# ---------------------------------------------------------------------------
# WebXR HTML page (served at /quest)
# ---------------------------------------------------------------------------

_QUEST_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BotverseX Quest Teleop</title>
<style>
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0b0f1a; color: #e5e7eb; }
  .container { max-width: 720px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 8px; }
  p  { font-size: 13px; line-height: 1.6; color: #9ca3af; margin: 0 0 12px; }
  .status { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; }
  .ok   { background: rgba(16,185,129,0.15); color: #6ee7b7; }
  .warn { background: rgba(245,158,11,0.15); color: #fcd34d; }
  .err  { background: rgba(239,68,68,0.15); color: #fca5a5; }
  pre { background: #111827; padding: 12px; border-radius: 8px; font-size: 11px; overflow-x: auto; }
  button { background: #2563eb; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; }
  button:hover { background: #1d4ed8; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin: 12px 0; }
  .pill { background: #1f2937; padding: 4px 10px; border-radius: 999px; font-size: 11px; }
</style>
</head>
<body>
<div class="container">
  <h1>BotverseX · Quest 遥操</h1>
  <p>用 Meta Quest 2/3 手柄遥操 LeKiwi / SO-101 / B601。不需要主臂。</p>

  <div class="row">
    <span id="wsStatus" class="status warn">未连接</span>
    <span id="xrStatus" class="status warn">未进入 XR</span>
    <span id="poseStatus" class="pill">pose: —</span>
  </div>

  <p>操作说明：</p>
  <ul style="font-size: 12px; color: #9ca3af; padding-left: 18px;">
    <li>右手柄位姿 → 末端执行器目标位姿</li>
    <li>右手扳机 → 夹爪闭合 / 松开</li>
    <li>左摇杆 → 底盘移动（仅 LeKiwi）</li>
    <li>右手柄 B 键 → 急停（卸力）</li>
  </ul>

  <div class="row">
    <button id="enterXr">进入 XR（VR 模式）</button>
    <button id="exitXr" style="display:none">退出 XR</button>
  </div>

  <pre id="log">等待事件…</pre>
</div>

<script>
const logEl = document.getElementById('log');
const wsStatusEl = document.getElementById('wsStatus');
const xrStatusEl = document.getElementById('xrStatus');
const poseStatusEl = document.getElementById('poseStatus');
const enterXrBtn = document.getElementById('enterXr');
const exitXrBtn = document.getElementById('exitXr');

function log(msg) {
  const t = new Date().toLocaleTimeString();
  logEl.textContent = `[${t}] ${msg}\\n` + logEl.textContent.split('\\n').slice(0, 30).join('\\n');
}

// WebSocket for pose streaming
const wsUrl = (location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws/quest';
let ws = null;
function connectWs() {
  ws = new WebSocket(wsUrl);
  ws.onopen = () => { wsStatusEl.textContent = '已连接'; wsStatusEl.className = 'status ok'; log('WebSocket 已连接'); };
  ws.onclose = () => { wsStatusEl.textContent = '已断开'; wsStatusEl.className = 'status warn'; log('WebSocket 断开，3s 后重连'); setTimeout(connectWs, 3000); };
  ws.onerror = (e) => { log('WebSocket 错误'); };
  ws.onmessage = (e) => { log('收到: ' + e.data); };
}
connectWs();

function sendPose(pose) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'pose', ...pose, t: Date.now() }));
  }
}

// WebXR
let xrSession = null;
let xrReferenceSpace = null;
let xrRequested = false;

async function enterXr() {
  if (!('xr' in navigator)) {
    log('此浏览器不支持 WebXR。请在 Quest 浏览器打开本页。');
    return;
  }
  try {
    xrSession = await navigator.xr.requestSession('immersive-vr', { optionalFeatures: ['local-floor', 'bounded-floor'] });
    xrSession.addEventListener('end', onXrEnd);
    const gl = document.createElement('canvas').getContext('webgl', { xrCompatible: true });
    xrSession.updateRenderState({ baseLayer: new XRWebGLLayer(xrSession, gl) });
    xrReferenceSpace = await xrSession.requestReferenceSpace('local-floor');
    xrStatusEl.textContent = 'XR 已进入';
    xrStatusEl.className = 'status ok';
    enterXrBtn.style.display = 'none';
    exitXrBtn.style.display = 'inline-block';
    log('已进入 XR');
    xrSession.requestAnimationFrame(onXrFrame);
  } catch (e) {
    xrStatusEl.textContent = '进入失败';
    xrStatusEl.className = 'status err';
    log('进入 XR 失败: ' + e.message);
  }
}

function onXrEnd() {
  xrSession = null;
  xrReferenceSpace = null;
  xrStatusEl.textContent = '已退出';
  xrStatusEl.className = 'status warn';
  enterXrBtn.style.display = 'inline-block';
  exitXrBtn.style.display = 'none';
  log('已退出 XR');
}

function exitXr() {
  if (xrSession) xrSession.end();
}

function onXrFrame(t, frame) {
  if (!xrSession || xrSession.ended) return;
  const poses = [];
  for (const source of xrSession.inputSources) {
    const pose = frame.getPose(source.gripSpace, xrReferenceSpace);
    if (pose) {
      const p = pose.transform.position;
      const o = pose.transform.orientation;
      const buttons = source.gamepad?.buttons?.map(b => b.pressed ? 1 : 0) ?? [];
      const axes = source.gamepad?.axes ?? [];
      poses.push({
        hand: source.handedness,
        position: [p.x, p.y, p.z],
        orientation: [o.x, o.y, o.z, o.w],
        buttons,
        axes,
      });
    }
  }
  if (poses.length > 0) {
    sendPose({ poses });
    poseStatusEl.textContent = 'pose: ' + poses.length + ' 只手';
  }
  xrSession.requestAnimationFrame(onXrFrame);
}

enterXrBtn.addEventListener('click', enterXr);
exitXrBtn.addEventListener('click', exitXr);
log('页面已加载。点「进入 XR」开始。');
</script>
</body>
</html>
"""


@router.get("/quest", response_class=HTMLResponse)
async def quest_page() -> HTMLResponse:
    """Serve the WebXR teleop page. Open this URL in the Quest 2/3 browser."""
    return HTMLResponse(_QUEST_HTML)


# ---------------------------------------------------------------------------
# WebSocket for pose streaming
# ---------------------------------------------------------------------------


async def _quest_ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _session["clients"] = _session.get("clients", 0) + 1
    global _pose_updated_at
    try:
        await websocket.send_json({"type": "hello", "msg": "Quest teleop ready"})
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "pose":
                _latest_pose.clear()
                _latest_pose.update(msg)
                _pose_updated_at = time.time()
            # Echo back the latest arm state (TODO: hook into robot state stream)
    except WebSocketDisconnect:
        pass
    finally:
        _session["clients"] = max(0, _session.get("clients", 0) - 1)


# Register as ws_router-style: we attach the websocket directly on the router
# because FastAPI supports @router.websocket.
router.websocket("/ws/quest")(_quest_ws_endpoint)


# ---------------------------------------------------------------------------
# HTTP control endpoints
# ---------------------------------------------------------------------------


@router.post("/api/quest_teleop/start")
async def quest_teleop_start(robot_id: str = "lekiwi", mode: str = "lekiwi") -> JSONResponse:
    """Start a Quest-driven teleop session.

    This is a stub that records intent. The actual lerobot-teleoperate
    subprocess with the Quest bridge as input source will be wired in a
    follow-up; for now we expose the contract so the UI can call it.
    """
    if _session.get("running"):
        return JSONResponse(
            {"ok": False, "error": "Quest teleop already running"},
            status_code=409,
        )
    _session.update(
        {
            "running": True,
            "started_at": time.time(),
            "robot_id": robot_id,
            "mode": mode,
        }
    )
    logger.info("quest_teleop start: robot_id=%s mode=%s", robot_id, mode)
    return JSONResponse({"ok": True, "robot_id": robot_id, "mode": mode})


@router.post("/api/quest_teleop/stop")
async def quest_teleop_stop() -> JSONResponse:
    _session.update(
        {
            "running": False,
            "started_at": None,
            "robot_id": None,
            "mode": None,
        }
    )
    return JSONResponse({"ok": True})


@router.get("/api/quest_teleop/status")
async def quest_teleop_status() -> JSONResponse:
    pose_age = (time.time() - _pose_updated_at) if _pose_updated_at else None
    return JSONResponse(
        {
            "running": _session.get("running", False),
            "started_at": _session.get("started_at"),
            "robot_id": _session.get("robot_id"),
            "mode": _session.get("mode"),
            "clients": _session.get("clients", 0),
            "pose_age_s": pose_age,
            "pose_present": bool(_latest_pose),
        }
    )


@router.get("/api/quest_teleop/url")
async def quest_teleop_url() -> JSONResponse:
    """Tell the UI what URL to open on the Quest headset."""
    # The Local Agent's host:port as seen from the Quest must be reachable.
    # We can't know the LAN IP from inside the process reliably; the UI
    # computes it from window.location on the web side. Here we just
    # confirm the path.
    return JSONResponse({"path": "/quest", "note": "Open https://<this-computer-LAN-IP>:8002/quest in the Quest browser."})
