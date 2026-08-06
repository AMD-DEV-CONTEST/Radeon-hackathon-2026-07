#!/usr/bin/env python3
"""ww gen-video generate — Read markdown from pasteboard, send to the gen-video API server.

Reads content from the system clipboard, POSTs it to the GEN_VIDEO_SERVER_URL
endpoint (returns immediately with a job_id), and prints the job ID.
Use --poll to wait for completion and download the generated video.

Usage:
    ww gen-video generate [options]

Environment:
    GEN_VIDEO_SERVER_URL   The gen-video API server URL (e.g. http://localhost:8000)
                           The /api/generate-video path is appended automatically.

Options:
    --output PATH   Where to save the generated video (default: gen_video_<timestamp>.mp4)
    --model MODEL   LLM model override to send to the server
    --image-model   Image generation model override
    --server URL    Override GEN_VIDEO_SERVER_URL for this call
    --poll          Wait for job to complete and download the video
    --upload        Upload the generated video to YouTube after creation
    --privacy STATUS  YouTube privacy status: public, private, or unlisted (default: public)
"""

import os
import sys
import time

import requests


def main():
    try:
        from fluxreel.env import load_env as _le

        _le()
    except ImportError:
        pass

    # ── Parse args ──────────────────────────────────────────────────────
    args = list(sys.argv[1:])

    output_path = None
    model = None
    image_model = None
    provider = "openrouter"
    local_variant = "schnell"
    server_url = None
    do_poll = False
    do_upload = False
    privacy = "public"

    i = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        elif args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] == "--image-model" and i + 1 < len(args):
            image_model = args[i + 1]
            i += 2
        elif args[i] == "--provider" and i + 1 < len(args):
            provider = args[i + 1]
            i += 2
        elif args[i] == "--local-variant" and i + 1 < len(args):
            local_variant = args[i + 1]
            i += 2
        elif args[i] == "--server" and i + 1 < len(args):
            server_url = args[i + 1]
            i += 2
        elif args[i] == "--poll":
            do_poll = True
            i += 1
        elif args[i] == "--upload":
            do_upload = True
            i += 1
        elif args[i] == "--privacy" and i + 1 < len(args):
            privacy = args[i + 1]
            if privacy not in ("public", "private", "unlisted"):
                print(
                    f"Error: --privacy must be public, private, or unlisted, got: {privacy}"
                )
                sys.exit(1)
            i += 2
        elif args[i] in ("--help", "-h"):
            print(__doc__)
            return
        else:
            print(f"Unknown option: {args[i]}")
            print(__doc__)
            sys.exit(1)

    # ── Get server URL ──────────────────────────────────────────────────
    if server_url is None:
        server_url = os.getenv("GEN_VIDEO_SERVER_URL", "")
    if not server_url:
        print(
            "Error: GEN_VIDEO_SERVER_URL not set. Set it in .env or pass --server URL."
        )
        sys.exit(1)

    server_url = server_url.rstrip("/")
    base_url = server_url.removesuffix("/api/generate-video").removesuffix("/api")
    submit_url = base_url + "/api/generate-video"

    # ── Read pasteboard ─────────────────────────────────────────────────
    try:
        import pyperclip

        content = pyperclip.paste()
    except Exception:
        import subprocess

        try:
            result = subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=5
            )
            content = result.stdout
        except Exception:
            print(
                "Error: Could not read from pasteboard. Is pyperclip or pbpaste available?"
            )
            sys.exit(1)

    if not content or not content.strip():
        print("Error: Pasteboard is empty.")
        sys.exit(1)

    print(f"Read {len(content)} chars from pasteboard.")

    # ── Determine output path ───────────────────────────────────────────
    if output_path is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = f"gen_video_{timestamp}.mp4"

    # ── Build and send request ──────────────────────────────────────────
    payload: dict[str, str | bool] = {"content": content}
    if model:
        payload["model"] = model
    if image_model:
        payload["image_model"] = image_model
    if provider:
        payload["provider"] = provider
    if local_variant:
        payload["local_variant"] = local_variant
    if do_upload:
        payload["upload"] = True
        payload["privacy"] = privacy

    print(f"Sending to {submit_url} ...")
    print(f"  Model: {model or 'default'}")
    print(f"  Image model: {image_model or 'default'}")
    if do_upload:
        print(f"  Upload to YouTube: yes (privacy: {privacy})")

    try:
        resp = requests.post(submit_url, json=payload, timeout=(10, 30))
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {submit_url}")
        print("  Is the gen-video server running? Try: ww gen-video server")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("Error: Request timed out connecting to server.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text[:500])
        except Exception:
            detail = resp.text[:500]
        print(f"Error: Server returned HTTP {resp.status_code}")
        print(f"  {detail}")
        sys.exit(1)

    result = resp.json()
    job_id = result.get("job_id")
    if not job_id:
        print(f"Error: No job_id in response: {result}")
        sys.exit(1)

    print(f"\nJob submitted: {job_id}")
    print(f"  Status URL:  {base_url}/api/jobs/{job_id}")
    print(f"  Download URL: {base_url}/api/jobs/{job_id}/download")

    if not do_poll:
        print(f"\nJob ID: {job_id}")
        return

    # ── Poll until completed ────────────────────────────────────────────
    print("\nWaiting for completion...")
    status_url = f"{base_url}/api/jobs/{job_id}"

    dots = 0
    while True:
        try:
            sresp = requests.get(status_url, timeout=10)
        except Exception:
            time.sleep(5)
            continue

        if sresp.status_code != 200:
            time.sleep(5)
            continue

        status_data = sresp.json()
        status = status_data.get("status", "unknown")

        if status == "completed":
            print()
            youtube_url = status_data.get("youtube_url")
            if youtube_url:
                print(f"YouTube URL: {youtube_url}")
            break
        elif status == "failed":
            error = status_data.get("error", "Unknown error")
            print(f"\nError: Job failed: {error}")
            sys.exit(1)
        else:
            # pending or processing
            dots += 1
            marker = "." * dots
            print(f"\r  Status: {status}{marker:<10}", end="", flush=True)
            time.sleep(5)

    # ── Download the completed video ────────────────────────────────────
    download_url = f"{base_url}/api/jobs/{job_id}/download"
    print("Downloading video...")

    try:
        dresp = requests.get(download_url, stream=True, timeout=(10, 600))
    except Exception as e:
        print(f"Error: Download failed: {e}")
        sys.exit(1)

    if dresp.status_code != 200:
        try:
            detail = dresp.json().get("detail", dresp.text[:500])
        except Exception:
            detail = dresp.text[:500]
        print(f"Error: Download returned HTTP {dresp.status_code}: {detail}")
        sys.exit(1)

    with open(output_path, "wb") as f:
        for chunk in dresp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    size = os.path.getsize(output_path)
    print(f"\n✓ Video saved: {output_path}")
    print(f"  Size: {size / 1024 / 1024:.1f} MB")
