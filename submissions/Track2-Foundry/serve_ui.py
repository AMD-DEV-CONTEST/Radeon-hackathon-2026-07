"""Foundry web UI: Flask server with disconnect-proof agent jobs.

Architecture (v2): POST /chat starts the agent turn in a background
thread that appends events to a per-job buffer — the turn runs to
completion no matter what happens to the browser or tunnel. Clients
subscribe via GET /events/<job> (Server-Sent Events, which cloudflared
streams unbuffered), with Last-Event-ID replay on reconnect and comment
heartbeats so no proxy ever sees an idle connection.

Usage:
    python serve_ui.py --config configs/local_4060.toml [--port 8300]
"""

import argparse
import json
import subprocess
import threading
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

from foundry import config as config_mod
from foundry.agent import Agent
from foundry.teacher import TeacherClient
from foundry.tools import ToolBox

app = Flask(__name__, static_folder="static", static_url_path="/static")
STATE: dict = {}   # cfg, agent, toolbox, ctl
JOBS: dict = {}    # job_id -> {events: [], cond: Condition, done: bool}
AGENT_LOCK = threading.Lock()  # one agent turn at a time

HEARTBEAT_S = 12


def _new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"events": [], "cond": threading.Condition(), "done": False}
    return job_id


def emit(job_id: str, kind: str, data):
    job = JOBS[job_id]
    with job["cond"]:
        job["events"].append({"id": len(job["events"]), "type": kind,
                              "data": data})
        job["cond"].notify_all()


def run_turn(job_id: str, message: str):
    try:
        with AGENT_LOCK:
            STATE["toolbox"].progress = lambda detail: emit(
                job_id, "tool_progress", {"detail": detail})
            for kind, data in STATE["agent"].turn(message):
                emit(job_id, kind, data)
    except Exception as e:
        emit(job_id, "error", f"{type(e).__name__}: {e}")
    finally:
        job = JOBS[job_id]
        emit(job_id, "done", None)
        with job["cond"]:
            job["done"] = True
            job["cond"].notify_all()


def gpu_stats() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            name, used, total, util = [x.strip() for x in
                                       out.stdout.strip().splitlines()[0].split(",")]
            return {"name": name, "used_mb": int(used), "total_mb": int(total),
                    "util_pct": int(util)}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    try:  # ROCm
        out = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--showuse",
                              "--json"], capture_output=True, text=True, timeout=5)
        data = json.loads(out.stdout)
        card = next(iter(data.values()))
        used = int(card.get("VRAM Total Used Memory (B)", 0)) // 2**20
        total = int(card.get("VRAM Total Memory (B)", 0)) // 2**20
        util = int(card.get("GPU use (%)", 0))
        return {"name": "AMD Radeon (ROCm)", "used_mb": used,
                "total_mb": total, "util_pct": util}
    except Exception:
        return {"name": "GPU unavailable", "used_mb": 0, "total_mb": 0,
                "util_pct": 0}


@app.get("/")
def index():
    return send_file(Path(app.static_folder) / "index.html")


@app.get("/gpu")
def gpu():
    return jsonify(gpu_stats())


@app.get("/state")
def state():
    toolbox: ToolBox = STATE["toolbox"]
    build = None
    if toolbox.spec is not None:
        build = {
            "task": toolbox.spec.name,
            "workspace": str(toolbox.run_dir),
            "has_dataset": (toolbox.run_dir / "train.jsonl").exists(),
            "has_model": (toolbox.run_dir / "merged").exists(),
            "has_eval": (toolbox.run_dir / "eval_report.json").exists(),
            "has_bench": (toolbox.run_dir / "bench_report.json").exists(),
        }
    return jsonify({
        "build": build,
        "experiments": toolbox.registry.list()[-8:],
        "model": Path(str(STATE["cfg"]["teacher"]["gguf"])).name,
        "busy": AGENT_LOCK.locked(),
    })


@app.get("/artifact")
def artifact():
    out_root = Path(STATE["cfg"]["run"]["out_root"]).resolve()
    p = Path(request.args["path"]).resolve()
    if not str(p).startswith(str(out_root)) or not p.exists():
        return "not found", 404
    return send_file(p)


@app.post("/chat")
def chat():
    message = request.get_json(force=True)["message"]
    if AGENT_LOCK.locked():
        return jsonify({"error": "busy"}), 409
    job_id = _new_job()
    threading.Thread(target=run_turn, args=(job_id, message),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/jobs/<job_id>")
def job_info(job_id):
    """Existence probe: lets the client tell a dead job (server was
    restarted; clear state and go idle) from a network blip (keep
    reconnecting)."""
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"exists": False}), 404
    return jsonify({"exists": True, "done": job["done"],
                    "events": len(job["events"])})


@app.get("/events/<job_id>")
def events(job_id):
    if job_id not in JOBS:
        return "unknown job", 404
    after = request.headers.get("Last-Event-ID",
                                request.args.get("after", "-1"))
    try:
        cursor = int(after) + 1
    except ValueError:
        cursor = 0

    def gen(cursor):
        job = JOBS[job_id]
        while True:
            with job["cond"]:
                while len(job["events"]) <= cursor and not job["done"]:
                    if not job["cond"].wait(timeout=HEARTBEAT_S):
                        break  # heartbeat turn
                batch = job["events"][cursor:]
                done = job["done"]
            if batch:
                for ev in batch:
                    yield (f"id: {ev['id']}\n"
                           f"data: {json.dumps(ev, default=str)}\n\n")
                cursor += len(batch)
            elif not done:
                yield ": ping\n\n"
                yield "event: hb\ndata: {}\n\n"
            if done and len(JOBS[job_id]["events"]) <= cursor:
                return

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
               "Connection": "keep-alive"}
    return Response(gen(cursor), mimetype="text/event-stream",
                    headers=headers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/local_4060.toml")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (0.0.0.0 for remote access)")
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--open", action="store_true",
                    help="open the browser once the server is up")
    args = ap.parse_args()

    from chat import TeacherCtl

    cfg = config_mod.load(args.config)
    ctl = TeacherCtl(cfg)
    if not TeacherClient(cfg["teacher"]["base_url"]).healthy():
        ctl.start()
    toolbox = ToolBox(cfg, args.config, ctl)
    STATE.update(cfg=cfg, ctl=ctl, toolbox=toolbox,
                 agent=Agent(cfg, toolbox))
    shown = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"Foundry UI: http://{shown}:{args.port}")
    if args.open:
        import webbrowser
        threading.Timer(1.5, webbrowser.open,
                        [f"http://{shown}:{args.port}"]).start()
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
