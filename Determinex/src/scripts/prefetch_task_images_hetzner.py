#!/usr/bin/env python3
"""Bulk-pull missing :task images on Hetzner from the ProgramBench registry.

Run this locally — it SSHes into Hetzner and runs docker pull for each missing image.
"""

import json
import subprocess
import time

REMOTE = "root@5.78.192.163"
SSH_KEY = str(__import__("pathlib").Path.home() / ".ssh" / "id_citadel")
ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"

TERMINAL = {
    "strict_lock",
    "locked",
    "ceiling_certified",
    "ceiling_confirmed",
    "impossible_ceiling",
    "alias",
}


def ssh(cmd: str, timeout: int = 30) -> str:
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
        timeout=timeout,
    )
    return r.stdout


def remote_image_set() -> set[str]:
    out = ssh("docker images --format '{{.Repository}}:{{.Tag}}'", timeout=30)
    return {l.strip() for l in out.splitlines() if "programbench/" in l}


def slug_to_image(slug: str) -> str:
    # e.g. burntsushi__ripgrep.3b7fd44 -> programbench/burntsushi_1776_ripgrep.3b7fd44:task
    slug_img = slug.replace("__", "_1776_")
    return f"programbench/{slug_img}:task"


def main():
    print("[prefetch] Loading eval_index...", flush=True)
    rows = json.loads(EVAL_INDEX.read_bytes())

    slugs = [r["slug"] for r in rows if r.get("status") not in TERMINAL and r.get("slug")]
    print(f"[prefetch] {len(slugs)} non-terminal tools", flush=True)

    print("[prefetch] Fetching remote image list...", flush=True)
    remote = remote_image_set()
    print(f"[prefetch] {len(remote)} images already on Hetzner", flush=True)

    missing = []
    for slug in slugs:
        img = slug_to_image(slug)
        # Check both :task and the actual tag format we see on Hetzner
        slug_img = slug.replace("__", "_1776_")
        base = f"programbench/{slug_img}"
        if not any(r.startswith(base) for r in remote):
            missing.append((slug, img))

    print(f"[prefetch] {len(missing)} images to pull", flush=True)

    ok = 0
    fail = 0
    for i, (slug, img) in enumerate(missing):
        print(f"\n[prefetch] {i + 1}/{len(missing)}: {img}", flush=True)
        # Fire background pull on Hetzner (non-blocking, each pull runs in background)
        cmd = f"nohup docker pull {img} >> /root/pb_image_pull.log 2>&1 &"
        ssh(cmd, timeout=15)
        print("  [queued on Hetzner]", flush=True)
        ok += 1
        # Stagger slightly to avoid hammering the registry
        time.sleep(0.3)

    print(f"\n[prefetch] Done queuing. {ok} pulls fired on Hetzner.", flush=True)
    print(
        "[prefetch] Monitor with: ssh root@5.78.192.163 'tail -f /root/pb_image_pull.log'",
        flush=True,
    )


if __name__ == "__main__":
    main()
