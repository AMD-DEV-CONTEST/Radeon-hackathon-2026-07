#!/usr/bin/env python3
"""Push missing :task images from local Docker to Hetzner via docker save | ssh docker load.

Only pushes programbench/*:task images that are present locally but absent on Hetzner.
Skips programbench-compiled/* images (those are per-candidate, not base images).
"""

import os
import subprocess
import time
from pathlib import Path

REMOTE = "root@5.78.192.163"
SSH_KEY = os.environ.get("DETERMINEX_SSH_KEY", str(Path.home() / ".ssh" / "id_citadel"))


def ssh_lines(cmd: str) -> list[str]:
    r = subprocess.run(
        [
            "ssh",
            "-i",
            SSH_KEY,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            REMOTE,
            cmd,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def local_images() -> list[str]:
    r = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True
    )
    imgs = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("programbench/") and not line.startswith("programbench-compiled/"):
            imgs.append(line)
    return sorted(set(imgs))


def remote_images() -> set[str]:
    lines = ssh_lines("docker images --format '{{.Repository}}:{{.Tag}}'")
    return {
        l
        for l in lines
        if l.startswith("programbench/") and not l.startswith("programbench-compiled/")
    }


def push_image(image: str) -> bool:
    print(f"  [push] {image} ...", flush=True)
    save_proc = subprocess.Popen(
        ["docker", "save", image], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    load_proc = subprocess.Popen(
        [
            "ssh",
            "-i",
            SSH_KEY,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            REMOTE,
            "docker load",
        ],
        stdin=save_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    save_proc.stdout.close()
    load_out, load_err = load_proc.communicate(timeout=600)
    save_proc.wait(timeout=30)

    if load_proc.returncode == 0:
        print(f"  [push] OK: {load_out.decode('utf-8', 'replace').strip()}", flush=True)
        return True
    else:
        print(f"  [push] FAILED: {load_err.decode('utf-8', 'replace')[:300]}", flush=True)
        return False


def main():
    print("[sync] Checking local images...", flush=True)
    local = local_images()
    print(f"[sync] Local task images: {len(local)}", flush=True)

    print("[sync] Checking Hetzner images...", flush=True)
    remote = remote_images()
    print(f"[sync] Hetzner task images: {len(remote)}", flush=True)

    missing = [img for img in local if img not in remote]
    print(f"[sync] Missing on Hetzner: {len(missing)}", flush=True)

    if not missing:
        print("[sync] Nothing to push.", flush=True)
        return

    ok = 0
    fail = 0
    for i, img in enumerate(missing):
        print(f"\n[sync] {i + 1}/{len(missing)}: {img}", flush=True)
        if push_image(img):
            ok += 1
        else:
            fail += 1
        # Brief pause between pushes to avoid overwhelming the pipe
        time.sleep(1)

    print(f"\n[sync] Done. pushed={ok} failed={fail}", flush=True)


if __name__ == "__main__":
    main()
