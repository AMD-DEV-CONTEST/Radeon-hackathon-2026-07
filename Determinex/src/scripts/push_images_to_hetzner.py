#!/usr/bin/env python3
"""Push missing :task images from local Docker to Hetzner via docker save | ssh docker load.
Runs unattended - pipes one image at a time. 3GB images take ~10-15 min each on typical uplink.
"""

import json
import subprocess
import time
from pathlib import Path

REMOTE = "root@5.78.192.163"
SSH_KEY = str(Path.home() / ".ssh" / "id_citadel")
ROOT = Path(__file__).resolve().parent.parent
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
TERMINAL = {
    "strict_lock",
    "locked",
    "ceiling_certified",
    "ceiling_confirmed",
    "impossible_ceiling",
    "alias",
}


def remote_short_names() -> set[str]:
    """Get set of short tool names already on Hetzner."""
    r = subprocess.run(
        [
            "ssh",
            "-i",
            SSH_KEY,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "BatchMode=yes",
            REMOTE,
            "docker images --format '{{.Repository}}'",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    shorts = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if "programbench/" in line and "programbench-compiled" not in line:
            # e.g. programbench/burntsushi_1776_ripgrep.3b7fd44 -> ripgrep
            parts = line.replace("programbench/", "").split("_1776_")
            if len(parts) == 2:
                short = parts[1].split(".")[0]
                shorts.add(short)
    return shorts


def local_image_for_slug(slug: str) -> str | None:
    """Find the best local image for a slug."""
    if "__" not in slug:
        return None
    author, rest = slug.split("__", 1)
    short = rest.split(".")[0]
    slug_img = slug.replace("__", "_1776_")

    r = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True
    )
    lines = [
        l
        for l in r.stdout.splitlines()
        if short.lower() in l.lower() and "programbench/" in l and "programbench-compiled" not in l
    ]
    # prefer :task over :task_cleanroom_v6
    plain = [l for l in lines if l.endswith(":task")]
    if plain:
        return plain[0]
    cleanroom = [l for l in lines if "cleanroom" in l]
    if cleanroom:
        return cleanroom[0]
    return None


def push_image(local_img: str, slug: str) -> bool:
    print(f"  [push] {local_img} -> Hetzner ...", flush=True)
    save_proc = subprocess.Popen(
        ["docker", "save", local_img], stdout=subprocess.PIPE, stderr=subprocess.PIPE
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
            "-o",
            "ServerAliveInterval=30",
            REMOTE,
            "docker load",
        ],
        stdin=save_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    save_proc.stdout.close()
    load_out, load_err = load_proc.communicate(timeout=900)
    save_proc.wait(timeout=60)

    if load_proc.returncode == 0:
        loaded = load_out.decode("utf-8", "replace").strip()
        print(f"  [push] OK: {loaded}", flush=True)
        return True
    else:
        err = load_err.decode("utf-8", "replace")[:300]
        print(f"  [push] FAILED: {err}", flush=True)
        return False


def main():
    print("[push] Loading eval_index...", flush=True)
    rows = json.loads(EVAL_INDEX.read_bytes())
    slugs = [
        r["slug"]
        for r in rows
        if r.get("status") not in TERMINAL and r.get("slug") and "__" in r.get("slug", "")
    ]

    print("[push] Checking what's already on Hetzner...", flush=True)
    have_shorts = remote_short_names()
    print(f"[push] Hetzner has {len(have_shorts)} tool short-names", flush=True)

    to_push = []
    for slug in slugs:
        short = slug.split("__")[-1].split(".")[0]
        if short in have_shorts:
            continue
        img = local_image_for_slug(slug)
        if img:
            to_push.append((slug, img))
        else:
            print(f"[push] SKIP {slug} — no local image found", flush=True)

    print(f"[push] {len(to_push)} images to push", flush=True)

    ok = 0
    fail = 0
    for i, (slug, img) in enumerate(to_push):
        print(f"\n[push] {i + 1}/{len(to_push)}: {slug} ({img})", flush=True)
        if push_image(img, slug):
            ok += 1
        else:
            fail += 1
        time.sleep(2)

    print(f"\n[push] DONE. ok={ok} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
