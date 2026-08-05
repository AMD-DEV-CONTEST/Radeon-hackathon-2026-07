"""
tonight_launch.py — Watch corpus, then fire RunPod training.
Works from PowerShell, Git Bash, or WSL.

Usage:
  python scripts/tonight_launch.py
  python scripts/tonight_launch.py --skip-wait   (corpus already done)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

POD_HOST = os.environ.get("RUNPOD_HOST", "")
POD_PORT = os.environ.get("RUNPOD_PORT", "22")
POD_KEY = os.environ.get("RUNPOD_KEY", str(Path.home() / ".ssh/id_runpod"))
DETERMINEX = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).parent.parent))

if not POD_HOST:
    print("ERROR: set RUNPOD_HOST=<pod-ip> before running")
    sys.exit(1)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def ssh(cmd: str, capture=False):
    full = [
        "ssh",
        "-p",
        POD_PORT,
        "-i",
        POD_KEY,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=15",
        f"root@{POD_HOST}",
        cmd,
    ]
    if capture:
        return subprocess.run(full, capture_output=True, text=True).stdout.strip()
    else:
        subprocess.run(full, check=False)


def scp(local: str, remote: str):
    subprocess.run(
        [
            "scp",
            "-P",
            POD_PORT,
            "-i",
            POD_KEY,
            "-o",
            "StrictHostKeyChecking=no",
            local,
            f"root@{POD_HOST}:{remote}",
        ],
        check=False,
    )


def corpus_progress():
    return "..."


def wait_for_corpus():
    target = DETERMINEX / "data" / "rosetta_training.jsonl"
    log("Watching corpus expansion (checks every 60s)...")
    while True:
        if target.exists():
            lines = sum(1 for _ in target.open(encoding="utf-8"))
            if lines >= 18000:
                log(f"Corpus ready: {lines:,} examples")
                return
            else:
                log(f"  File exists but only {lines} lines — waiting for more...")
        log(f"  {corpus_progress()}")
        time.sleep(60)


def split_corpus():
    log("Splitting corpus...")
    result = subprocess.run(
        [
            sys.executable,
            str(DETERMINEX / "dataset_generation/generate_rosetta_corpus.py"),
            "--split",
            "--data-dir",
            str(DETERMINEX / "data"),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"Split error: {result.stderr[-500:]}")
    else:
        log("Split complete")
    for f in ["rosetta_train.jsonl", "lora_train.jsonl"]:
        p = DETERMINEX / "data" / f
        if p.exists():
            log(f"  {f}: {sum(1 for _ in p.open(encoding='utf-8')):,} lines")


def upload_files():
    log("Setting up pod workspace...")
    ssh("mkdir -p /workspace/data /workspace/outputs")

    log("Uploading corpus files...")
    scp(str(DETERMINEX / "data/rosetta_train.jsonl"), "/workspace/data/")
    scp(str(DETERMINEX / "data/lora_train.jsonl"), "/workspace/data/")

    log("Uploading curriculum + DSL data...")
    for fname in ["curriculum.jsonl", "dsl_corpus_merged.jsonl"]:
        p = DETERMINEX / "scripts" / fname
        if p.exists():
            scp(str(p), "/workspace/data/")
            log(f"  ↑ {fname}")

    ac = DETERMINEX / "auto_curriculum.jsonl"
    if ac.exists():
        scp(str(ac), "/workspace/data/")
        log("  ↑ auto_curriculum.jsonl")

    for f in sorted((DETERMINEX / "scripts").glob("gap_v*.jsonl")):
        scp(str(f), "/workspace/data/")

    log("Uploading training scripts...")
    scp(str(DETERMINEX / "scripts/train_rosetta_bases.py"), "/workspace/")
    scp(str(DETERMINEX / "determinex_trainer/dsl_finetune.py"), "/workspace/")


def kill_vllm():
    log("Stopping vLLM to free VRAM...")
    ssh("pkill -f 'vllm.entrypoints' 2>/dev/null || true; sleep 3")
    mem = ssh("nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader", capture=True)
    log(f"  GPU after kill: {mem}")


def launch_rosetta():
    log("Launching Rosetta Stone training on pod...")
    ssh("""
        cd /workspace
        nohup python3 train_rosetta_bases.py \
            --data-dir        /workspace/data \
            --out-dir         /workspace/rosetta_out \
            --cache-dir       /workspace/rosetta_cache \
            --skip-gated-check \
            > /workspace/rosetta_train.log 2>&1 &
        echo $! > /workspace/rosetta.pid
        echo "Rosetta PID: $(cat /workspace/rosetta.pid)"
    """)
    log("Rosetta training running. Polling every 60s for rosetta_v1.pt...")
    max_wait_s = int(os.environ.get("DETERMINEX_ROSETTA_MAX_WAIT_S", "14400"))  # 4h default
    start = time.time()
    while True:
        if time.time() - start > max_wait_s:
            log(f"TIMEOUT: Rosetta training exceeded {max_wait_s}s. Aborting poll.")
            return
        done = ssh(
            "[ -f /workspace/rosetta_out/rosetta_v1.pt ] && echo YES || echo NO", capture=True
        )
        if done.strip() == "YES":
            log("rosetta_v1.pt DONE!")
            break
        last = ssh("tail -2 /workspace/rosetta_train.log 2>/dev/null", capture=True)
        log(f"  {last.replace(chr(10), ' | ')}")
        time.sleep(60)


def download_rosetta():
    rosetta_local = Path.home() / ".determinex" / "rosetta"
    rosetta_local.mkdir(parents=True, exist_ok=True)
    log(f"Downloading rosetta_v1.pt → {rosetta_local}")
    subprocess.run(
        [
            "scp",
            "-P",
            POD_PORT,
            "-i",
            POD_KEY,
            "-o",
            "StrictHostKeyChecking=no",
            f"root@{POD_HOST}:/workspace/rosetta_out/rosetta_v1.pt",
            str(rosetta_local / "rosetta_v1.pt"),
        ],
        check=False,
    )
    if (rosetta_local / "rosetta_v1.pt").exists():
        log("rosetta_v1.pt saved locally")


def launch_lora():
    log("Launching LoRA fine-tune sequence: observer → engineer → sentinel")
    ssh("""
        cd /workspace
        nohup bash -c '
            echo "STAGE:observer-start $(date)"
            python3 dsl_finetune.py observer > /workspace/retrain_observer.log 2>&1
            echo "STAGE:engineer-start $(date)"
            python3 dsl_finetune.py engineer > /workspace/retrain_engineer.log 2>&1
            echo "STAGE:sentinel-start $(date)"
            python3 dsl_finetune.py sentinel > /workspace/retrain_sentinel.log 2>&1
            echo "ALL_LORA_COMPLETE $(date)"
        ' > /workspace/lora_master.log 2>&1 &
        echo $! > /workspace/lora.pid
        echo "LoRA PID: $(cat /workspace/lora.pid)"
    """)
    log("LoRA training is running in the background on the pod.")
    log("")
    log("=" * 60)
    log("ALL TRAINING LAUNCHED. Leave pod running overnight.")
    log("")
    log("Check status anytime:")
    log(
        f"  ssh root@{POD_HOST} -p {POD_PORT} -i ~/.ssh/id_runpod 'tail -5 /workspace/lora_master.log'"
    )
    log(
        f"  ssh root@{POD_HOST} -p {POD_PORT} -i ~/.ssh/id_runpod 'tail -5 /workspace/retrain_observer.log'"
    )
    log("")
    log("When LoRA is done, download + register v1.1:")
    log("  python scripts/register_v1_1.py")
    log("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-wait", action="store_true", help="Skip corpus wait")
    parser.add_argument("--skip-rosetta", action="store_true", help="Skip Rosetta training")
    parser.add_argument("--skip-lora", action="store_true", help="Skip LoRA fine-tune")
    args = parser.parse_args()

    log("Determinex Tonight Launch — v1.1 training pipeline")
    log(f"Pod: {POD_HOST}:{POD_PORT}")
    log("Budget: ~$6.21 remaining @ $0.28/hr = ~22h of runway")
    log("")

    if not args.skip_wait:
        wait_for_corpus()
        split_corpus()

    upload_files()
    kill_vllm()

    if not args.skip_rosetta:
        launch_rosetta()
        download_rosetta()

    if not args.skip_lora:
        launch_lora()


if __name__ == "__main__":
    main()
