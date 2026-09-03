#!/usr/bin/env python3
"""Inference entry points for G1-D organize-and-tidy task.

This project uses Client–Server VLA inference:
  - Server (AMD cloud): Policy Server + rc-tunnel
  - Client (local PC): real robot + cameras

Usage (from project root):

  # Cloud — start Policy Server
  bash src/self_scripts/infer/serve_g1d_policy_amd.sh
  # or: RC_TUNNEL=1 bash src/self_scripts/infer/serve_g1d_policy_amd.sh

  # Local — start real-robot Client
  bash src/self_scripts/infer/run_g1d_client.sh \\
    --server_host wss://rc-xxxx.radeon.firstdg.ai \\
    --image_host <JETSON_IP> \\
    --instruction "Organize and tidy the items on the table."

See README.md Section 5 for full setup.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="G1-D inference launcher")
    sub = parser.add_subparsers(dest="mode", required=True)

    serve = sub.add_parser("serve", help="Start AMD cloud Policy Server")
    serve.add_argument("--tunnel", action="store_true", help="Enable RC_TUNNEL=1")

    client = sub.add_parser("client", help="Start local real-robot Client")
    client.add_argument("--server_host", required=True)
    client.add_argument("--image_host", required=True)
    client.add_argument(
        "--instruction",
        default="Organize and tidy the items on the table.",
    )
    client.add_argument("--frequency", type=int, default=30)

    args = parser.parse_args()

    if args.mode == "serve":
        script = _ROOT / "self_scripts" / "infer" / "serve_g1d_policy_amd.sh"
        env = None
        if args.tunnel:
            import os

            env = os.environ.copy()
            env["RC_TUNNEL"] = "1"
        return subprocess.call(["bash", str(script)], env=env)

    script = _ROOT / "self_scripts" / "infer" / "run_g1d_client.sh"
    cmd = [
        "bash",
        str(script),
        "--server_host",
        args.server_host,
        "--image_host",
        args.image_host,
        "--instruction",
        args.instruction,
        "--frequency",
        str(args.frequency),
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
