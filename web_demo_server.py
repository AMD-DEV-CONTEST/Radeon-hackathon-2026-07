#!/usr/bin/env python3
"""Web demo server: real-time Genesis simulator rendering + SmolVLA inference.

Architecture
------------
- Main thread:    Genesis GPU scene + VLA model + episode sim loop
- Flask thread:   HTTP server (daemon) serving the web UI and JPEG frame streams
- Frame buffer:   thread-safe ``latest_world_jpg`` / ``latest_wrist_jpg`` — the sim
                  loop writes them and Flask reads them
- Command queue:  the web UI pushes (pick_object, seed, task_string) tuples; the
                  sim loop pops and runs them as full closed-loop episodes

Three language instructions (from the training dataset, must match exactly):
  1. "pick the gear and place it in the blue box"
  2. "pick the hex nut and place it in the red box"
  3. "pick the bolt and place it in the green box"

Usage:
    python web_demo_server.py --port 8765 [--checkpoint ...] [--dataset-id ...]

Then open http://<server-ip>:8765 in a browser (or use an SSH tunnel:
    ssh -L 8765:localhost:8765 root@<ip> -p <port>
and open http://localhost:8765).
"""

from __future__ import annotations

# -- CRITICAL: set offline + cache env BEFORE any HF/transformers imports --
import os
os.environ.setdefault("HF_HOME", "/persistent/track3-robot/cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import argparse
import json
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
import torch

# -- project root (for industrial_pick imports) ---------------------------
# Auto-detect: the script lives either:
#   a) next to build_scene.py (server: .../industrial_pick/web_demo_server.py)
#   b) one level above src/industrial_pick/ (local: .../submission/web_demo_server.py)
_SCRIPT_DIR = Path(__file__).resolve().parent
if (_SCRIPT_DIR / "build_scene.py").exists():
    _PACKAGE_DIR = _SCRIPT_DIR                    # case a — script is inside the package
elif (_SCRIPT_DIR / "src" / "industrial_pick" / "build_scene.py").exists():
    _PACKAGE_DIR = _SCRIPT_DIR / "src" / "industrial_pick"  # case b
else:
    raise FileNotFoundError(
        f"Cannot find build_scene.py. Script directory: {_SCRIPT_DIR}. "
        f"Place this script inside the industrial_pick package directory."
    )
if str(_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_DIR))

import genesis as gs
from flask import Flask, Response, jsonify, request

from build_scene import build_scene
from grasp_demo import TaskSpec, check_success
from randomize import EnvRandomizer, RandomizationConfig
from scene_config import BOX_DISPLAY_NAMES, SORT_TARGET

# ── constants (mirror eval_policy.py) ───────────────────────────────────
CONTROL_FPS = 100
FPS = 30

OBJECT_DISPLAY_NAMES = {
    "gear": "gear",
    "nut": "hex nut",
    "bolt": "bolt",
}

# These three strings are the exact language instructions from the training dataset.
PRESET_COMMANDS = [
    ("gear", "pick the gear and place it in the blue box"),
    ("nut", "pick the hex nut and place it in the red box"),
    ("bolt", "pick the bolt and place it in the green box"),
]

# When --fixed-demo is active, each part uses a verified successful seed
# instead of a random one.  Seeds chosen from 19 curated successes (demo_package_v2)
# with preference for multi-verified and fast-finishing episodes.
FIXED_DEMO_SEEDS = {
    "gear": 2003,   # 4/4 career success (3× verified + latest rerun), 242-248 frames
    "bolt": 2014,   # fast success, 198-207 frames
    "nut":  2007,   # succeeded in latest rerun (239f); nut is the hardest part, very few seeds work
}

_FIXED_DEMO = False  # set by --fixed-demo CLI flag


def task_description(pick_object: str) -> str:
    name = OBJECT_DISPLAY_NAMES.get(pick_object, pick_object)
    box = BOX_DISPLAY_NAMES[SORT_TARGET[pick_object]]
    return f"pick the {name} and place it in the {box}"


def _to_np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


# ── VLA Policy Runner (minimal clone of eval_policy.PolicyRunner) ──────
class PolicyRunner:
    def __init__(self, checkpoint: str, dataset_id: str, device: torch.device):
        from lerobot.configs.types import FeatureType
        from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
        from lerobot.datasets.utils import dataset_to_policy_features
        from lerobot.policies.factory import make_pre_post_processors
        from lerobot.policies.smolvla.configuration_smolvla import SmolVLAConfig
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

        self.device = device
        dm = LeRobotDatasetMetadata(dataset_id)
        ft = dataset_to_policy_features(dm.features)
        of = {k: v for k, v in ft.items() if v.type is FeatureType.ACTION}
        inf = {k: v for k, v in ft.items() if k not in of}
        ckpt = Path(checkpoint)
        scfg = json.loads((ckpt / "config.json").read_text()) if (ckpt / "config.json").exists() else {}
        cs = scfg.get("chunk_size", 50)
        cfg = SmolVLAConfig(input_features=inf, output_features=of, chunk_size=cs, n_action_steps=cs)
        # Override vlm_model_name to local path — server has no internet access.
        cfg.vlm_model_name = '/persistent/track3-robot/models/SmolVLM2-500M-Video-Instruct'
        try:
            self.policy = SmolVLAPolicy.from_pretrained(
                str(ckpt), config=cfg, strict=False, local_files_only=True)
            print(f"[web-demo] SmolVLA loaded via from_pretrained from {ckpt}")
        except Exception as e:
            print(f"[web-demo] from_pretrained failed ({e}), loading manually ...")
            from safetensors.torch import load_file
            self.policy = SmolVLAPolicy(cfg)
            self.policy.load_state_dict(load_file(str(ckpt / "model.safetensors")), strict=False)
            print(f"[web-demo] SmolVLA loaded manually from {ckpt}")
        self.policy.eval().to(device)
        self.pre, self.post = make_pre_post_processors(cfg, dataset_stats=dm.stats)
        print(f"[web-demo] SmolVLA ready (chunk_size={cs}, device={device})")

    def predict(self, state: np.ndarray, imgs: dict[str, np.ndarray], task: str) -> np.ndarray:
        obs = {
            "observation.state": torch.from_numpy(state).unsqueeze(0).float().to(self.device),
            "task": [task],
        }
        for k, img in imgs.items():
            obs[k] = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float().to(self.device) / 255.0
        with torch.no_grad():
            obs = self.pre(obs)
            for k, v in list(obs.items()):
                if isinstance(v, torch.Tensor) and v.device != self.device:
                    obs[k] = v.to(self.device)
            raw = self.policy.select_action(obs)
            raw = self.post(raw)
        acts = raw["action"] if isinstance(raw, dict) else raw
        acts = acts.detach().cpu().numpy()
        if acts.ndim == 3:
            acts = acts[0]
        elif acts.ndim == 1:
            acts = acts[np.newaxis, :]
        return acts


# ── demo state (shared between main thread and Flask thread) ────────────
class DemoState:
    def __init__(self):
        self.lock = threading.Lock()
        self.world_jpg: bytes | None = None
        self.wrist_jpg: bytes | None = None
        self.status: str = "idle"        # idle | running | done
        self.status_msg: str = "Ready. Select a command and press Run."
        self.last_result: dict | None = None
        self.command_queue: queue.Queue = queue.Queue()
        self.episode_count: int = 0
        self.current_frame: int = 0
        self.total_frames: int = 0

    def set_frames(self, world_jpg: bytes, wrist_jpg: bytes):
        with self.lock:
            self.world_jpg = world_jpg
            self.wrist_jpg = wrist_jpg

    def set_status(self, status: str, msg: str = ""):
        with self.lock:
            self.status = status
            if msg:
                self.status_msg = msg

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "status": self.status,
                "status_msg": self.status_msg,
                "result": self.last_result,
                "episode_count": self.episode_count,
                "current_frame": self.current_frame,
                "total_frames": self.total_frames,
            }


# ── Flask app ───────────────────────────────────────────────────────────
state = DemoState()
app = Flask(__name__)


@app.route("/")
def index():
    return _HTML


@app.route("/world.jpg")
def world_frame():
    with state.lock:
        jpg = state.world_jpg
    if jpg is None:
        return Response(status=204)
    return Response(jpg, mimetype="image/jpeg",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.route("/wrist.jpg")
def wrist_frame():
    with state.lock:
        jpg = state.wrist_jpg
    if jpg is None:
        return Response(status=204)
    return Response(jpg, mimetype="image/jpeg",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.route("/api/status")
def api_status():
    return jsonify(state.snapshot())


@app.route("/api/commands")
def api_commands():
    return jsonify([{"pick": p, "task": t} for p, t in PRESET_COMMANDS])


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json() or {}
    task_str = (data.get("task") or "").strip()
    seed = data.get("seed")

    if not task_str:
        return jsonify({"error": "No task provided."}), 400

    # Resolve pick object from the task string.
    pick = None
    tlower = task_str.lower()
    if "gear" in tlower:
        pick = "gear"
    elif "nut" in tlower:
        pick = "nut"
    elif "bolt" in tlower:
        pick = "bolt"

    if pick is None:
        return jsonify({
            "error": f"Cannot determine pick object from '{task_str}'. "
                     f"Use one of: gear, hex nut, bolt."
        }), 400

    if seed is None:
        if _FIXED_DEMO:
            seed = FIXED_DEMO_SEEDS.get(pick, 42)
        else:
            import random
            seed = random.randint(1000, 9999)
    else:
        seed = int(seed)

    snap = state.snapshot()
    if snap["status"] == "running":
        return jsonify({"error": "An episode is already running. Please wait."}), 409

    state.command_queue.put((pick, seed, task_str))
    return jsonify({"status": "accepted", "pick": pick, "seed": seed, "task": task_str})


# ── Sim loop (runs on MAIN thread — Genesis requires it) ────────────────
JPEG_QUALITY = 65
WEB_RES = (640, 360)  # downsample for web streaming
MAX_FRAMES = 450
DWELL = 15


def encode_jpg(rgb: np.ndarray, size: tuple[int, int] = WEB_RES) -> bytes:
    """Resize an RGB uint8 image and encode as JPEG."""
    small = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        return b""
    return buf.tobytes()


def render_cams(bundle, img_wh: tuple[int, int] = WEB_RES):
    """Render both cams at native res, return (w_native, r_native, w_policy, r_policy).

    **Must match eval_policy.py's render_cams exactly** — single render call per
    iteration, processes both cameras at once, returns native + policy-resolution
    copies so the loop can feed the policy and encode JPEGs from the same render.
    """
    w = _to_np(bundle.world_cam.render(rgb=True)[0]).astype(np.uint8)
    r = _to_np(bundle.wrist_cam.render(rgb=True)[0]).astype(np.uint8)
    wp = cv2.resize(w, img_wh, interpolation=cv2.INTER_AREA)
    rp = cv2.resize(r, img_wh, interpolation=cv2.INTER_AREA)
    return w, r, wp, rp


def run_episode(bundle, randomizer, runner, pick: str, seed: int, task_str: str) -> dict:
    """Run a single closed-loop episode. Returns result dict."""
    randomizer.reset(seed=seed)
    task = TaskSpec(pick_object=pick, place_target=SORT_TARGET[pick])

    # Reset robot arm to neutral idle pose — the randomizer only resets the
    # environment (object positions), NOT the robot qpos.  Unlike eval_policy.py
    # (fresh process per episode), the web demo reuses the same Genesis scene,
    # so the arm carries over its last position.  Teleport + settle avoids the
    # "snap back" artifact the user sees when clicking Run.
    _NEUTRAL_QPOS = np.array([0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79, 0.04, 0.04], dtype=np.float32)
    bundle.franka.set_qpos(_NEUTRAL_QPOS)
    for _ in range(10):
        bundle.scene.step()
    bundle.update_wrist_cam()

    acts, ai = None, 0
    accum = 0.0
    dwell = 0
    success = False
    success_frame = -1
    n_recorded = 0
    img_wh = (640, 360)
    steps_per_frame = CONTROL_FPS / FPS

    # Prime observation — single render call, matching eval_policy.py exactly.
    _, _, w_pol, r_pol = render_cams(bundle, img_wh)

    while n_recorded < MAX_FRAMES:
        if acts is None or ai >= len(acts):
            qpos = _to_np(bundle.franka.get_qpos()).reshape(-1).astype(np.float32)
            acts = runner.predict(
                qpos,
                {"observation.images.world": w_pol, "observation.images.wrist": r_pol},
                task_str,
            )
            ai = 0

        action = acts[ai].astype(np.float32)
        ai += 1

        # Replay this 30 Hz action on the 100 Hz sim (3/3/4 pattern).
        # Matches eval_policy.py exactly.
        accum += steps_per_frame
        n_steps = int(accum)
        accum -= n_steps
        for _ in range(n_steps):
            bundle.franka.control_dofs_position(action)
            bundle.scene.step()
            bundle.update_wrist_cam()

        # Single render call per iteration, matching eval_policy.py exactly.
        w, r, w_pol, r_pol = render_cams(bundle, img_wh)

        n_recorded += 1

        # Push frames to web (JPEG from the same render — only difference from eval_policy).
        state.set_frames(encode_jpg(w), encode_jpg(r))
        with state.lock:
            state.current_frame = n_recorded
            state.total_frames = MAX_FRAMES

        if check_success(bundle, task):
            dwell += 1
            if not success and dwell >= DWELL:
                success = True
                success_frame = n_recorded
        else:
            dwell = 0
        if success and n_recorded >= success_frame + FPS:
            break

    result = {
        "pick": pick, "seed": seed, "task": task_str,
        "success": bool(success), "frames": n_recorded,
    }
    return result




def idle_render(bundle):
    """Render one idle frame (hold arm at qpos) and push to web."""
    bundle.franka.control_dofs_position(np.array(
        [0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79, 0.04, 0.04], dtype=float))
    bundle.scene.step()
    bundle.update_wrist_cam()
    w, r, _, _ = render_cams(bundle)
    state.set_frames(encode_jpg(w), encode_jpg(r))


# ── HTML frontend (inline, served at /) ─────────────────────────────────
_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SmolVLA Industrial Sorting — Live Demo</title>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --muted: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --red: #f85149;
    --orange: #d2991d;
    --gear: #58a6ff;
    --bolt: #3fb950;
    --nut: #f0883e;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text);
    min-height: 100vh; display: flex; flex-direction: column;
  }
  header {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 12px 24px; display: flex; align-items: center; gap: 16px;
  }
  header h1 { font-size: 1.2rem; font-weight: 600; }
  .badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 0.75rem; font-weight: 600;
  }
  .badge-ok { background: var(--green); color: #000; }
  .badge-fail { background: var(--red); color: #fff; }
  .badge-idle { background: var(--border); color: var(--muted); }
  .badge-running { background: var(--orange); color: #000; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
  main {
    flex: 1; display: flex; gap: 12px; padding: 12px;
    max-height: calc(100vh - 130px);
  }
  .cam-panel {
    flex: 1; background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; overflow: hidden; display: flex; flex-direction: column;
  }
  .cam-label {
    padding: 6px 12px; font-size: 0.75rem; font-weight: 600;
    background: var(--surface); border-bottom: 1px solid var(--border);
    color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;
  }
  .cam-view {
    flex: 1; display: flex; align-items: center; justify-content: center;
    background: #000; min-height: 200px; position: relative; overflow: hidden;
  }
  .cam-view img { width: 100%; height: 100%; object-fit: contain; }
  .wrist-panel { max-width: 360px; }
  .no-signal {
    position: absolute; color: var(--muted); font-size: 1rem;
    pointer-events: none;
  }
  footer {
    background: var(--surface); border-top: 1px solid var(--border);
    padding: 12px 24px; display: flex; gap: 12px; align-items: center;
    flex-wrap: wrap;
  }
  .cmd-group { display: flex; gap: 6px; }
  .cmd-btn {
    padding: 8px 16px; border: 1px solid var(--border); border-radius: 6px;
    background: var(--surface); color: var(--text); cursor: pointer;
    font-size: 0.85rem; transition: background 0.15s, border-color 0.15s;
  }
  .cmd-btn:hover { background: #1f2937; border-color: var(--accent); }
  .cmd-btn.gear { border-left: 3px solid var(--gear); }
  .cmd-btn.bolt { border-left: 3px solid var(--bolt); }
  .cmd-btn.nut { border-left: 3px solid var(--nut); }
  .cmd-btn:disabled { opacity: 0.4; pointer-events: none; }
  #run-btn {
    padding: 8px 24px; border: none; border-radius: 6px;
    background: var(--accent); color: #fff; cursor: pointer;
    font-size: 0.9rem; font-weight: 600; transition: background 0.15s;
  }
  #run-btn:hover { background: #79b8ff; }
  #run-btn:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }
  #task-input {
    flex: 1; min-width: 280px; padding: 8px 12px;
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); font-size: 0.9rem; outline: none;
  }
  #task-input:focus { border-color: var(--accent); }
  #status-line {
    font-size: 0.8rem; color: var(--muted); white-space: nowrap;
  }
  #result-panel {
    padding: 4px 12px; border-radius: 6px; font-size: 0.8rem;
    background: var(--surface); border: 1px solid var(--border);
  }
</style>
</head>
<body>

<header>
  <h1>&#x2699; Industrial Sorting — Live VLA Demo</h1>
  <span id="status-badge" class="badge badge-idle">IDLE</span>
  <span id="status-line"></span>
  <span id="result-panel" style="display:none"></span>
</header>

<main>
  <div class="cam-panel">
    <div class="cam-label">World Camera (1280×720 → 640×360)</div>
    <div class="cam-view" id="world-view">
      <span class="no-signal" id="world-nosignal">Waiting for simulator...</span>
      <img id="world-img" src="" alt="World camera" style="display:none">
    </div>
  </div>
  <div class="cam-panel wrist-panel">
    <div class="cam-label">Wrist Camera (eye-in-hand)</div>
    <div class="cam-view" id="wrist-view">
      <span class="no-signal" id="wrist-nosignal">Waiting for simulator...</span>
      <img id="wrist-img" src="" alt="Wrist camera" style="display:none">
    </div>
  </div>
</main>

<footer>
  <div class="cmd-group">
    <button class="cmd-btn gear" onclick="pickCommand('gear')" title="pick the gear and place it in the blue box">&#x2699; Gear → Blue</button>
    <button class="cmd-btn nut"  onclick="pickCommand('nut')"  title="pick the hex nut and place it in the red box">&#x1f529; Hex Nut → Red</button>
    <button class="cmd-btn bolt" onclick="pickCommand('bolt')" title="pick the bolt and place it in the green box">&#x1f527; Bolt → Green</button>
  </div>
  <input type="text" id="task-input" placeholder="e.g. pick the gear and place it in the blue box">
  <button id="run-btn" onclick="runEpisode()">&#x25b6; Run</button>
  <span style="font-size:0.75rem;color:var(--muted)">Episodes: <b id="ep-count">0</b></span>
</footer>

<script>
const TASKS = {
  gear: "pick the gear and place it in the blue box",
  nut: "pick the hex nut and place it in the red box",
  bolt: "pick the bolt and place it in the green box",
};

let pollTimer = null;
let statusTimer = null;
let running = false;

function $(id) { return document.getElementById(id); }

function pickCommand(pick) {
  $("task-input").value = TASKS[pick] || "";
  $("task-input").focus();
}

async function runEpisode() {
  const task = $("task-input").value.trim();
  if (!task) { alert("Please enter or select a language command."); return; }
  if (running) return;

  running = true;
  updateUI("running", "Running episode...");
  $("run-btn").disabled = true;
  for (const b of document.querySelectorAll(".cmd-btn")) b.disabled = true;

  try {
    const resp = await fetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({task: task}),
    });
    const data = await resp.json();
    if (data.error) {
      alert(data.error);
      running = false;
      updateUI("idle", data.error);
      $("run-btn").disabled = false;
      for (const b of document.querySelectorAll(".cmd-btn")) b.disabled = false;
      return;
    }
    console.log("Episode started:", data);
  } catch (err) {
    console.error(err);
    alert("Failed to start episode: " + err.message);
    running = false;
    updateUI("idle", "Error: " + err.message);
    $("run-btn").disabled = false;
    for (const b of document.querySelectorAll(".cmd-btn")) b.disabled = false;
  }
}

function updateUI(status, msg) {
  const badge = $("status-badge");
  badge.className = "badge";
  if (status === "running") {
    badge.classList.add("badge-running"); badge.textContent = "RUNNING";
  } else if (status === "done" || status === "success") {
    badge.classList.add("badge-ok"); badge.textContent = "DONE";
  } else if (status === "fail") {
    badge.classList.add("badge-fail"); badge.textContent = "FAIL";
  } else {
    badge.classList.add("badge-idle"); badge.textContent = "IDLE";
  }
  $("status-line").textContent = msg || "";
}

function refreshFrames() {
  const t = Date.now();
  const wImg = $("world-img");
  const rImg = $("wrist-img");
  wImg.src = "/world.jpg?t=" + t;
  rImg.src = "/wrist.jpg?t=" + t;
}

function pollStatus() {
  fetch("/api/status")
    .then(r => r.json())
    .then(data => {
      if (data.status === "running") {
        if (!running) running = true;
        updateUI("running", "Frame " + data.current_frame + " / " + data.total_frames);
        $("run-btn").disabled = true;
        for (const b of document.querySelectorAll(".cmd-btn")) b.disabled = true;
      } else if (data.status === "done" || data.status === "fail") {
        if (running) {
          running = false;
          const r = data.result;
          if (r) {
            const icon = r.success ? "&#x2705;" : "&#x274c;";
            const label = r.success ? "SUCCESS" : "FAIL";
            updateUI(r.success ? "success" : "fail",
              icon + " " + label + " — " + r.pick + " seed=" + r.seed + " (" + r.frames + " frames)");
            const rp = $("result-panel");
            rp.style.display = "inline-block";
            rp.innerHTML = icon + " <b>" + label + "</b> " + r.pick + " s" + r.seed + " · " + r.frames + "f";
            rp.style.color = r.success ? "var(--green)" : "var(--red)";
          }
          $("run-btn").disabled = false;
          for (const b of document.querySelectorAll(".cmd-btn")) b.disabled = false;
          $("ep-count").textContent = data.episode_count;
        } else {
          updateUI("idle", data.status_msg || "Ready.");
          $("run-btn").disabled = false;
          for (const b of document.querySelectorAll(".cmd-btn")) b.disabled = false;
        }
      }
    })
    .catch(err => console.error("Status poll error:", err));
}

// Init
window.addEventListener("DOMContentLoaded", () => {
  // Show imgs once they start loading
  $("world-img").onload = () => {
    $("world-img").style.display = "block";
    $("world-nosignal").style.display = "none";
  };
  $("wrist-img").onload = () => {
    $("wrist-img").style.display = "block";
    $("wrist-nosignal").style.display = "none";
  };
  // Handle load errors gracefully
  $("world-img").onerror = () => {
    $("world-img").style.display = "none";
    $("world-nosignal").style.display = "block";
  };
  $("wrist-img").onerror = () => {
    $("wrist-img").style.display = "none";
    $("wrist-nosignal").style.display = "block";
  };

  // Start polling
  pollTimer = setInterval(refreshFrames, 120);   // ~8 fps
  statusTimer = setInterval(pollStatus, 500);     // status check

  // Enter key triggers run
  $("task-input").addEventListener("keydown", e => {
    if (e.key === "Enter") runEpisode();
  });

  // Pre-fill with gear
  $("task-input").value = TASKS.gear;
  console.log("SmolVLA Industrial Sorting Demo ready.");
  console.log("Commands:", Object.values(TASKS));
});
</script>
</body>
</html>"""


# ── main ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Web demo server for SmolVLA industrial sorting.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--checkpoint", required=True,
                        help="Path to trained SmolVLA checkpoint directory.")
    parser.add_argument("--dataset-id", default="local/industrial_sort_v2",
                        help="LeRobot dataset id (default: local/industrial_sort_v2)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Base seed for the EnvRandomizer (default: 42)")
    parser.add_argument("--fps", type=int, default=8,
                        help="Idle render FPS to web (default: 8)")
    parser.add_argument("--cpu", action="store_true", help="Use CPU backend (debug only).")
    parser.add_argument("--fixed-demo", action="store_true",
                        help="Use fixed, verified-successful seeds per part (gear=2003, bolt=2014, nut=2007) "
                             "instead of random seeds. Greatly increases demo success rate.")
    args = parser.parse_args()

    # Activate fixed-demo mode (use verified-successful seeds per part).
    global _FIXED_DEMO
    if args.fixed_demo:
        _FIXED_DEMO = True

    print("=" * 60)
    print("[web-demo] Starting SmolVLA Industrial Sorting Web Demo")
    print(f"[web-demo]   checkpoint : {args.checkpoint}")
    print(f"[web-demo]   dataset    : {args.dataset_id}")
    print(f"[web-demo]   port       : {args.port}")
    print(f"[web-demo]   fixed-demo : {_FIXED_DEMO}")
    if _FIXED_DEMO:
        print(f"[web-demo]   demo seeds : {FIXED_DEMO_SEEDS}")
    print("=" * 60)

    # -- 1. Init Genesis & build scene (MAIN thread) --
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    print(f"[web-demo] device: {device}")

    gs.init(backend=gs.cpu if args.cpu else gs.gpu, logging_level="warning")
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=True, add_wrist_cam=True)
    print("[web-demo] Genesis scene built.")

    # -- 2. Load VLA model --
    runner = PolicyRunner(args.checkpoint, args.dataset_id, device)
    randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=False, seed=args.seed))

    # -- 3. Start Flask in background thread --
    flask_thread = threading.Thread(
        target=lambda: app.run(host=args.host, port=args.port, debug=False, threaded=True),
        daemon=True,
    )
    flask_thread.start()
    print(f"[web-demo] Flask server on http://{args.host}:{args.port}")

    # -- 4. Print the three dataset instructions --
    print("\n[web-demo] Dataset language instructions (exact match required):")
    for pick, task_str in PRESET_COMMANDS:
        print(f"  [{pick}] {task_str}")
    print()

    # -- 5. Main sim loop --
    idle_period = 1.0 / args.fps
    print(f"[web-demo] Idle render loop started ({args.fps} fps). Waiting for commands...\n")

    while True:
        # Check for a queued command.
        try:
            pick, seed, task_str = state.command_queue.get(timeout=0.05)
        except queue.Empty:
            # Idle: keep rendering so the web stream stays live.
            idle_render(bundle)
            time.sleep(idle_period)
            continue

        # -- Run episode --
        state.set_status("running", f"Running: {task_str} (seed={seed})")
        with state.lock:
            state.current_frame = 0
            state.total_frames = MAX_FRAMES

        print(f"\n[web-demo] === Episode start: pick={pick} seed={seed} task='{task_str}' ===")
        t0 = time.time()
        try:
            result = run_episode(bundle, randomizer, runner, pick, seed, task_str)
        except Exception:
            traceback.print_exc()
            result = {"pick": pick, "seed": seed, "task": task_str, "success": False,
                      "frames": 0, "error": traceback.format_exc()}
        elapsed = time.time() - t0

        tag = "OK" if result["success"] else "FAIL"
        print(f"[web-demo] === Episode done: {tag} frames={result['frames']} "
              f"elapsed={elapsed:.1f}s ===")

        with state.lock:
            state.episode_count += 1
            state.last_result = result
        state.set_status(
            "done" if result["success"] else "fail",
            f"{tag} — {pick} seed={seed} ({result['frames']} frames, {elapsed:.1f}s)"
        )

        # Let the frontend see the "done" state for a moment, then go back to idle.
        time.sleep(0.5)
        state.set_status("idle", "Ready. Select a command and press Run.")


if __name__ == "__main__":
    main()
