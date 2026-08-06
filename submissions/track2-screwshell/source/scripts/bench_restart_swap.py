#!/usr/bin/env python3
"""Measure llama.cpp server restart cost to validate the L3 紧张档 swap strategy.

Why this exists
---------------
The optimized plan proposes: on low-VRAM hardware, swap experts by restarting
llama-server with a different `--lora` set (llama-swap style). That restart
RELOADS the whole 27B base + LoRA, so the real cost is not "swap latency" but
"full model reload". This script measures it empirically so we can decide
between (A) dynamic swap + guards vs (B) fixed single expert.

What it measures (per --lora variant = one expert you'd swap to)
----------------------------------------------------------------
  1. Ensure the target port is FREE (kill any listener if --takeover, else
     refuse to start). This prevents silently measuring a stale server.
  2. Launch a FRESH llama-server with that variant's --lora.
  3. Poll /health until the HTTP server is up                -> t_to_health
  4. Poll a 1-token completion until it SUCCEEDS (model loaded) -> t_to_serve
     t_to_serve is the true user dead-wait: from launch to a model that can
     actually answer. /health alone is NOT enough — llama.cpp reports healthy
     before weights are in VRAM.
  5. Kill ONLY our own process group, then wait until the port is FREE again
     before the next variant (so the next launch truly rebinds the port).

SAFETY
------
By default this script NEVER touches a server it didn't start:
  * It launches the server in its OWN process group and only kills that group.
  * It NEVER pkill's 'llama-server' globally.
If another agent already runs a server on the target port:
  * --takeover : explicitly kill the pre-existing listener on --port ONCE at
                startup (USE ONLY IF that other session can be interrupted).
  * --port N   : run on a different port in parallel (needs spare VRAM for a
                second 27B instance — ~21GB extra; may OOM on a 48GB card).
If you pick neither and the port is busy, the harness aborts with a clear error
and will NOT kill the other agent's server.

Usage (on the ROCm host)
------------------------
  python scripts/bench_restart_swap.py \
      --takeover \
      --port 8080 \
      --launch-cmd '/persistent/llama.cpp/build/bin/llama-server --model /persistent/models/Qwen3.6-27B-Q4_K_M.gguf --lora {lora} --host 127.0.0.1 --port 8080 -ngl 99 -fa on -c 8192' \
      --loras "/persistent/loras/teichai_fable5_plan/adapter.gguf" \  # on-disk folder; logical name is teichai_plan (resolved via router.EXPERT_NAME_ALIASES)
              "/persistent/loras/btl3/adapter.gguf" \
              "/persistent/loras/cybersec/adapter.gguf" \
              "/persistent/loras/n7/adapter.gguf" \
      --repeat 1

  # No-GPU logic check:
  python scripts/bench_restart_swap.py --mock-delay 9.0 --loras a b c --repeat 2
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer


# ----------------------------- port helpers -----------------------------

def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def _wait_port_free(port: int, timeout: float = 30.0) -> bool:
    """Return True once the port stops accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_free(port):
            return True
        time.sleep(0.5)
    return _port_free(port)


def _listener_pid_ss(port: int) -> str | None:
    """Find the PID listening on TCP port via `ss` (Linux), if available."""
    try:
        out = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if f":{port}" in line:
            i = line.find("pid=")
            if i != -1:
                j = line.find(",", i)
                return line[i + 4: j if j != -1 else len(line)].strip()
    return None


def _listener_pid_proc(port: int) -> str | None:
    """Fallback: find the listener PID by parsing /proc (no external tools).

    Reads /proc/net/tcp{,6}, matches the LISTEN state + port (hex), grabs the
    socket inode, then scans /proc/<pid>/fd to find which process owns it.
    """
    hexport = f"{port:04X}"
    for proto in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(proto) as f:
                next(f)
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    local = parts[1]            # e.g. 00000000:1F90
                    state = parts[3]            # 0A = LISTEN
                    if state != "0A":
                        continue
                    lp = local.split(":")[-1].upper()
                    if lp != hexport:
                        continue
                    inode = parts[9]
                    for fdlink in glob.glob("/proc/[0-9]*/fd/*"):
                        try:
                            if os.readlink(fdlink).endswith(f"socket:[{inode}]"):
                                return fdlink.split("/")[2]
                        except Exception:
                            pass
        except Exception:
            continue
    return None


def _listener_pid(port: int) -> str | None:
    return _listener_pid_ss(port) or _listener_pid_proc(port)


def _kill_listener(port: int) -> None:
    """Kill whichever process is listening on `port` (takeover only)."""
    pid = _listener_pid(port)
    if not pid:
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except Exception:
        pass
    # also SIGKILL the whole group a bit later if still alive
    time.sleep(1.0)
    if not _wait_port_free(port, timeout=8.0):
        try:
            os.kill(int(pid), signal.SIGKILL)
        except Exception:
            pass


# ----------------------------- real backend -----------------------------

def _health_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def _first_token(url: str, prompt: str = "hi", model_id: str = "m",
                timeout: float = 180.0) -> float | None:
    """Return seconds-to-first-token, or None if it never answered."""
    payload = json.dumps({
        "model": model_id, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1, "temperature": 0.0,
    }).encode()
    req = urllib.request.Request(
        f"{url}/v1/chat/completions", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        urllib.request.urlopen(req, timeout=timeout).read()
        return time.time() - t0
    except Exception:
        return None


def _kill_proc(proc):
    """Kill ONLY our own process group (never a sibling server)."""
    if proc is None:
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            return
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            pass


def measure_variant(launch_cmd: str, lora: str, port: int,
                    health_path: str, serve_timeout: float,
                    prompt: str, model_id: str, log_path: str) -> dict:
    """Launch a fresh server for this variant, measure, then kill only ours.

    Correctness guarantees:
      * Refuses to measure if the port is NOT free right before launch
        (so we never silently hit a stale sibling server).
      * t_to_serve = time from launch until a real completion answers
        (true reload cost; not just HTTP-up).
      * After killing, waits for the port to be free again so the next
        variant truly rebinds the port.
    """
    base = f"http://127.0.0.1:{port}"
    cmd = launch_cmd.replace("{lora}", lora)
    # GUARD: port must be free before we start — otherwise we'd measure a
    # server someone else is running.
    if not _wait_port_free(port, timeout=8.0):
        return {"lora": lora, "ready": False, "error":
                "port still occupied before launch — aborting to avoid "
                "measuring a stale server"}
    t_launch = time.time()
    with open(log_path, "ab") as logf:
        proc = subprocess.Popen(
            cmd, shell=True, stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True)  # own PGID -> safe to killpg later
    # 1) wait for HTTP up (gate only)
    t_to_health = None
    while time.time() - t_launch < serve_timeout:
        if _health_ok(f"{base}{health_path}"):
            t_to_health = time.time() - t_launch
            break
        time.sleep(0.5)
    # 2) wait until a real completion answers (model actually loaded)
    t_to_serve = None
    if t_to_health is not None:
        ft = _first_token(base, prompt, model_id, timeout=serve_timeout)
        if ft is not None:
            t_to_serve = time.time() - t_launch  # launch -> serving
    _kill_proc(proc)
    _wait_port_free(port, timeout=20.0)  # ensure next variant rebinds
    return {
        "lora": lora,
        "to_health_s": round(t_to_health, 2) if t_to_health is not None else None,
        "to_serve_s": round(t_to_serve, 2) if t_to_serve is not None else None,
        "ready": t_to_serve is not None,
    }


# ----------------------------- mock backend -----------------------------

class _MockHandler(BaseHTTPRequestHandler):
    startup_delay = 2.0
    ready_at = 0.0

    def log_message(self, *a):
        pass

    def _ensure_ready(self):
        if time.time() < _MockHandler.ready_at:
            time.sleep(_MockHandler.ready_at - time.time())

    def do_GET(self):
        self._ensure_ready()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_POST(self):
        self._ensure_ready()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}],'
                         b'"usage":{"prompt_tokens":1,"completion_tokens":1}}')


def run_mock(delay: float, port: int, loraseq: list[str], repeat: int):
    _MockHandler.startup_delay = delay
    srv = HTTPServer(("127.0.0.1", port), _MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    results = []
    for _ in range(repeat):
        for lora in loraseq:
            _MockHandler.ready_at = time.time() + delay
            t0 = time.time()
            # wait for health (gated by ready_at)
            while not _health_ok(f"http://127.0.0.1:{port}/health"):
                time.sleep(0.05)
            _first_token(f"http://127.0.0.1:{port}")
            results.append({"lora": lora,
                            "to_health_s": round(delay, 2),
                            "to_serve_s": round(time.time() - t0, 2),
                            "ready": True})
    srv.shutdown()
    return results


# ----------------------------- reporting -----------------------------

def report(results: list[dict], repeat: int):
    print("\n=== per-variant restart cost (fresh model reload) ===")
    print(f"{'lora':42} {'to_health_s':>11} {'to_serve_s':>11}")
    for r in results:
        hs = r.get("to_health_s"); ss = r.get("to_serve_s")
        print(f"{r['lora'][:42]:42} "
              f"{str(hs):>11} {str(ss):>11}")
    distinct = []
    seen = set()
    for r in results:
        if r["lora"] not in seen:
            seen.add(r["lora"]); distinct.append(r)
    worst = sum((r.get("to_serve_s") or 0) for r in distinct)
    print(f"\nDistinct experts measured : {len(distinct)}")
    print(f"Worst-case task wait      : {worst:.1f}s "
          f"(sum of full reloads over {len(distinct)} experts, repeat={repeat})")
    print("Interpretation: this is the dead-wait a user endures if every "
          "expert swap reloads the full 27B base. Compare against the ~0.65ms "
          "scale-toggle in the 宽裕档 (all preloaded).")
    if any(not r.get("ready") for r in results):
        print("\n[!] Some variants did NOT become ready — the run is INVALID. "
              "Likely the port was occupied by a server we refused to kill, "
              "or the model failed to load. Check llama_server.log.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--launch-cmd", help="llama-server launch cmd; {lora} "
                    "is replaced with the current --lora variant. Do NOT add "
                    "'&' — the harness manages the process lifecycle.")
    ap.add_argument("--loras", nargs="+", required=True,
                    help="--lora argument per expert variant")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--health-path", default="/health")
    ap.add_argument("--takeover", action="store_true",
                    help="EXPLICIT & DESTRUCTIVE: kill the listener on --port "
                         "ONCE at startup. Only use if the other session on "
                         "that port can be interrupted.")
    ap.add_argument("--model-id", default="m",
                    help="model id sent in the /v1/chat/completions probe")
    ap.add_argument("--serve-timeout", type=float, default=180.0,
                    help="max seconds to wait for a variant to become ready")
    ap.add_argument("--prompt", default="hi")
    ap.add_argument("--repeat", type=int, default=1,
                    help="how many times to loop the full expert sequence")
    ap.add_argument("--mock-delay", type=float,
                    help="if set, run a fake server with this startup delay "
                         "(no GPU needed) to validate harness logic")
    args = ap.parse_args()

    if args.mock_delay is not None:
        results = run_mock(args.mock_delay, args.port, args.loras, args.repeat)
        report(results, args.repeat)
        return

    if not args.launch_cmd:
        ap.error("--launch-cmd is required in real mode")

    # Guard: do not silently clobber another agent's live server.
    if args.port == 8080 and not args.takeover:
        print("[WARN] port 8080 is the default the other agent uses. "
              "Refusing to start without --takeover. Either pass --takeover "
              "(interrupts the other session) or use --port 8081 (needs spare "
              "VRAM for a 2nd 27B instance).")
        ap.exit(2)

    if args.takeover:
        print("[TAKEOVER] killing the listener on port "
              f"{args.port} ONCE. This interrupts other sessions on that port.")
        _kill_listener(args.port)
        if not _wait_port_free(args.port, timeout=15.0):
            print("[ERR] port still occupied after takeover — aborting.")
            ap.exit(3)

    results = []
    for _ in range(args.repeat):
        for lora in args.loras:
            log_path = f"llama_server_{lora.split('/')[-2] or 'x'}.log"
            results.append(measure_variant(
                args.launch_cmd, lora, args.port, args.health_path,
                args.serve_timeout, args.prompt, args.model_id, log_path))
    report(results, args.repeat)


if __name__ == "__main__":
    main()
