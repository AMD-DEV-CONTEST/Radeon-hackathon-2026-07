# -*- coding: utf-8 -*-
"""Textovid — Deployment helper notebook (run as Python script)

Usage:  python deploy_notebook.py

This runs the full install pipeline in sequence and launches the app.
It is equivalent to running install.sh + app.py, but as a single script
that can be pasted into a Jupyter notebook cell.
"""

import subprocess
import sys
import os

WORKSPACE = "/workspace/textovid"
VENV = "/opt/venv"


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f">>> {cmd}")
    return subprocess.run(cmd, shell=True, check=check)


def main():
    os.chdir(WORKSPACE)

    # 1. Activate venv
    activate = f"source {VENV}/bin/activate && "

    # 2. Install system deps
    print("=== Installing system packages ===")
    run(f"sudo apt-get update -qq && sudo apt-get install -y -qq "
        f"libgl1-mesa-glx libglib2.0-0 ffmpeg 2>&1 | tail -3")

    # 3. Install Python deps
    print("=== Installing Python packages ===")
    run(f"{activate}pip install --upgrade pip -q")
    run(f"{activate}pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm7.2 -q")
    run(f"{activate}pip install -r requirements.txt -q")

    # 4. Download frpc
    print("=== Downloading frpc ===")
    frpc_dir = os.path.expanduser("~/.cache/huggingface/gradio/frpc")
    os.makedirs(frpc_dir, exist_ok=True)
    frpc_path = os.path.join(frpc_dir, "frpc_linux_amd64_v0.3")
    if not os.path.exists(frpc_path):
        run(f"wget -q -O {frpc_path} https://github.com/gradio-app/frpc/releases/download/v0.3/linux-amd64")
        run(f"chmod +x {frpc_path}")

    # 5. Launch
    print("=== Launching Textovid ===")
    run(f"{activate}python app.py")


if __name__ == "__main__":
    main()
