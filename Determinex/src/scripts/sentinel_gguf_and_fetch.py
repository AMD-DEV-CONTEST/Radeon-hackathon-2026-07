#!/usr/bin/env python3
"""
sentinel_gguf_and_fetch.py
==========================
Runs on LOCAL machine (Windows).

1. SSH to RunPod → launch GGUF conversion (q8_0 directly, no F16 intermediate)
2. Poll pod every 60s until GGUF appears + is fully written
3. SCP GGUF → $DETERMINEX_MODELS_DIR/versions/sentinel/v4-dsl/determinex-sentinel-v4.gguf-candidate
4. Send Windows toast notification
5. Print final instructions

Usage:
    python scripts/sentinel_gguf_and_fetch.py
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
POD_HOST = "<POD_IP>"
POD_PORT = "10001"
SSH_KEY = str(Path.home() / ".ssh" / "id_runpod")
SSH_BASE = [
    "ssh",
    "-p",
    POD_PORT,
    "-i",
    SSH_KEY,
    "-o",
    "StrictHostKeyChecking=no",
    f"root@{POD_HOST}",
]

REMOTE_MERGED = "/workspace/tmp_dsl_sen_merged"
REMOTE_OUT_DIR = "/workspace/outputs/determinex-sentinel-v4-dsl"
REMOTE_GGUF = f"{REMOTE_OUT_DIR}/determinex-sentinel-v4-dsl.gguf"
REMOTE_LOG = "/workspace/sentinel_gguf_retry.log"
LLAMA_CPP = "/workspace/llama.cpp"

LOCAL_OUT_DIR = (
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "versions"
    / "sentinel"
    / "v4-dsl"
)
LOCAL_GGUF = LOCAL_OUT_DIR / "determinex-sentinel-v4-dsl-candidate.gguf"

EXPECTED_SIZE_GB_MIN = 6.5  # Q8_0 Sentinel should be ~7.2 GB
POLL_INTERVAL_S = 60
MAX_WAIT_S = int(os.environ.get("DETERMINEX_GGUF_MAX_WAIT_S", "7200"))  # 2h default


# ── Helpers ─────────────────────────────────────────────────────────────────
def ts():
    return datetime.now().strftime("%H:%M:%S")


def ssh_run(cmd_str, capture=True):
    """Run a command on RunPod via SSH."""
    full = SSH_BASE + [cmd_str]
    r = subprocess.run(full, capture_output=capture, text=True)
    return r


def toast(title, message):
    """Send a Windows toast notification via PowerShell."""
    ps = (
        f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        f"ContentType = WindowsRuntime] | Out-Null; "
        f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        f"[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        f'$template.SelectSingleNode("//text[@id=1]").InnerText = "{title}"; '
        f'$template.SelectSingleNode("//text[@id=2]").InnerText = "{message}"; '
        f"$notifier = [Windows.UI.Notifications.ToastNotificationManager]::"
        f'CreateToastNotifier("Determinex"); '
        f"$notifier.Show([Windows.UI.Notifications.ToastNotification]::new($template));"
    )
    subprocess.run(["powershell", "-Command", ps], capture_output=True)


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


# ── Step 1: Launch GGUF conversion on pod ───────────────────────────────────
log("=== STEP 1: Launching GGUF conversion on RunPod ===")

# Verify merged model is there
r = ssh_run(f"ls -lh {REMOTE_MERGED}/model-*.safetensors 2>/dev/null | wc -l")
shard_count = r.stdout.strip()
log(f"Safetensor shards found: {shard_count}")
if shard_count == "0":
    log("ERROR: Merged model not found on pod. Aborting.")
    sys.exit(1)

# Check if GGUF already exists and is complete (in case of re-run)
r = ssh_run(f"stat --format=%s {REMOTE_GGUF} 2>/dev/null || echo 0")
existing_bytes = int(r.stdout.strip() or "0")
if existing_bytes > (EXPECTED_SIZE_GB_MIN * 1e9):
    log(f"GGUF already complete on pod ({existing_bytes / 1e9:.2f} GB). Skipping conversion.")
else:
    log("Starting nohup conversion (q8_0 direct, no F16 intermediate)...")

    launch_cmd = (
        f"mkdir -p {REMOTE_OUT_DIR} && "
        f"nohup python3 {LLAMA_CPP}/convert_hf_to_gguf.py "
        f"  {REMOTE_MERGED} "
        f"  --outtype q8_0 "
        f"  --outfile {REMOTE_GGUF} "
        f"> {REMOTE_LOG} 2>&1 & "
        f"echo $!"
    )
    r = ssh_run(launch_cmd)
    pid = r.stdout.strip()
    log(f"Conversion launched (PID {pid}). Log: {REMOTE_LOG}")
    log("Polling every 60s until GGUF is complete...")

# ── Step 2: Poll until GGUF is done ─────────────────────────────────────────
log("\n=== STEP 2: Polling for completion ===")
start = time.time()
last_size = 0
while True:
    time.sleep(POLL_INTERVAL_S)
    elapsed = int(time.time() - start)
    if elapsed > MAX_WAIT_S:
        log(f"TIMEOUT: GGUF conversion exceeded {MAX_WAIT_S}s. Last size: {last_size / 1e9:.2f}GB")
        toast("Determinex ⚠️", f"Sentinel GGUF conversion timed out after {MAX_WAIT_S // 60}min")
        sys.exit(2)

    # Check file size
    r = ssh_run(f"stat --format=%s {REMOTE_GGUF} 2>/dev/null || echo 0")
    size_bytes = int(r.stdout.strip() or "0")
    size_gb = size_bytes / 1e9

    # Check if process is still running
    r2 = ssh_run("pgrep -f convert_hf_to_gguf || echo dead")
    alive = r2.stdout.strip() != "dead" and r2.stdout.strip() != ""

    # Get last log line
    r3 = ssh_run(f"tail -1 {REMOTE_LOG} 2>/dev/null | tr -d '\\r\\n'")
    last_line = r3.stdout.strip()[-100:] if r3.stdout.strip() else "(no log)"

    log(
        f"  elapsed={elapsed}s  size={size_gb:.2f}GB  proc={'alive' if alive else 'DONE'}  | {last_line}"
    )

    if not alive and size_bytes > 0:
        if size_gb >= EXPECTED_SIZE_GB_MIN:
            log(f"GGUF complete! {size_gb:.2f} GB")
            break
        else:
            log(
                f"ERROR: Process exited but GGUF is only {size_gb:.2f} GB (expected >{EXPECTED_SIZE_GB_MIN} GB)"
            )
            log("Check pod log:")
            ssh_run(f"tail -30 {REMOTE_LOG}", capture=False)
            toast("Determinex ⚠️", f"Sentinel GGUF conversion FAILED ({size_gb:.2f}GB)")
            sys.exit(1)

    last_size = size_bytes

# ── Step 3: SCP to T: ───────────────────────────────────────────────────────
log(f"\n=== STEP 3: SCP GGUF to {LOCAL_GGUF} ===")
LOCAL_OUT_DIR.mkdir(parents=True, exist_ok=True)

scp_cmd = [
    "scp",
    "-P",
    POD_PORT,
    "-i",
    SSH_KEY,
    "-o",
    "StrictHostKeyChecking=no",
    f"root@{POD_HOST}:{REMOTE_GGUF}",
    str(LOCAL_GGUF),
]
log(f"Running: {' '.join(scp_cmd)}")
t0 = time.time()
r = subprocess.run(scp_cmd)
if r.returncode != 0:
    log("ERROR: SCP failed. Manual download needed.")
    toast("Determinex ⚠️", "Sentinel GGUF SCP FAILED — download manually")
    sys.exit(1)

elapsed_scp = int(time.time() - t0)
local_size_gb = LOCAL_GGUF.stat().st_size / 1e9
log(f"SCP complete in {elapsed_scp}s. Local size: {local_size_gb:.2f} GB")

# ── Step 4: Toast notification ───────────────────────────────────────────────
log("\n=== STEP 4: Sending notification ===")
toast(
    "✅ Determinex — Sentinel v4-dsl GGUF ready",
    f"Downloaded to {LOCAL_OUT_DIR}  |  {local_size_gb:.2f} GB",
)

# ── Step 5: Print next steps ─────────────────────────────────────────────────
log("""
╔══════════════════════════════════════════════════════════════════╗
║  Sentinel v4-dsl GGUF is on T:. NEXT STEPS:                     ║
║                                                                  ║
║  1. Create Modelfile → see below                                 ║
║  2. ollama create determinex-sentinel-v4 -f Modelfile.sentinel_v4   ║
║  3. cd <repo>/scripts                                    ║
║     python micro_eval.py --model determinex-sentinel-v4             ║
║  4. Evaluate result vs 87% baseline (accept if delta >= -3pp)    ║
║  5. Update BENCHMARK_HISTORY.md Phase 3 table                    ║
║                                                                  ║
║  THEN: rank-4 retrains for Observer + Engineer                   ║
╚══════════════════════════════════════════════════════════════════╝
""")
log(f"Candidate GGUF: {LOCAL_GGUF}")
log("Done.")
