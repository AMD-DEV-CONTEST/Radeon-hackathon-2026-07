#!/usr/bin/env python3
"""
运行 MakerMods demo
需要先安装: pip install -e ../makermods/lerobot-MakerMods-main --no-deps
"""

import subprocess
import sys
import os

MAKERMODS_PATH = os.path.join(os.path.dirname(__file__), "../makermods/lerobot-MakerMods-main")
IL_SIM_SCRIPT = os.path.join(MAKERMODS_PATH, "src/lerobot/scripts/lerobot_info.py")


def run_info():
    """运行 lerobot info 验证安装"""
    result = subprocess.run(
        [sys.executable, IL_SIM_SCRIPT],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
    return result.returncode == 0


if __name__ == "__main__":
    success = run_info()
    sys.exit(0 if success else 1)