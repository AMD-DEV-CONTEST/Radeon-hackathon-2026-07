#!/usr/bin/env python3
"""ww gen-video query — Query the status of a video generation job.

Usage:
    ww gen-video query <job_id> [options]

Environment:
    GEN_VIDEO_SERVER_URL   The gen-video API server URL (e.g. http://localhost:8000)

Options:
    --server URL    Override GEN_VIDEO_SERVER_URL for this call
    --json          Output raw JSON response
"""

import json
import os
import sys

import requests


def main():
    try:
        from fluxreel.env import load_env as _le

        _le()
    except ImportError:
        pass

    args = list(sys.argv[1:])

    job_id = None
    server_url = None
    as_json = False

    i = 0
    while i < len(args):
        if args[i] == "--server" and i + 1 < len(args):
            server_url = args[i + 1]
            i += 2
        elif args[i] == "--json":
            as_json = True
            i += 1
        elif args[i] in ("--help", "-h"):
            print(__doc__)
            return
        elif args[i].startswith("--"):
            print(f"Unknown option: {args[i]}")
            print(__doc__)
            sys.exit(1)
        else:
            job_id = args[i]
            i += 1

    if not job_id:
        print("Error: job_id is required.")
        print(__doc__)
        sys.exit(1)

    # ── Get server URL ──────────────────────────────────────────────────
    if server_url is None:
        server_url = os.getenv("GEN_VIDEO_SERVER_URL", "")
    if not server_url:
        print(
            "Error: GEN_VIDEO_SERVER_URL not set. "
            "Set it in .env or pass --server URL."
        )
        sys.exit(1)

    server_url = server_url.rstrip("/")
    base_url = server_url.removesuffix("/api/generate-video").removesuffix("/api")
    status_url = f"{base_url}/api/jobs/{job_id}"

    try:
        resp = requests.get(status_url, timeout=10)
    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {base_url}")
        print("  Is the gen-video server running? Try: ww gen-video server")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    if resp.status_code == 404:
        print(f"Error: Job {job_id} not found.")
        sys.exit(1)
    elif resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text[:500])
        except Exception:
            detail = resp.text[:500]
        print(f"Error: Server returned HTTP {resp.status_code}: {detail}")
        sys.exit(1)

    data = resp.json()

    if as_json:
        print(json.dumps(data, indent=2))
        return

    status = data.get("status", "unknown")
    download_url = data.get("download_url")

    print(f"Job:     {job_id}")
    print(f"Status:  {status}")

    if status == "completed":
        if download_url:
            print(f"Download: {base_url}{download_url}")
    elif status == "failed":
        error = data.get("error", "Unknown error")
        print(f"Error:   {error}")
    elif status in ("pending", "processing"):
        pass  # no extra info

    print()
    if status == "completed":
        print("Download: curl -s -o video.mp4")
        print(f"  {base_url}/api/jobs/{job_id}/download")
    elif status == "processing":
        print("Still processing — check again in a few seconds.")
    elif status == "pending":
        print("Waiting for processing to start.")
    elif status == "failed":
        print("Job failed. Check the error message above.")