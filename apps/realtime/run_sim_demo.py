#!/usr/bin/env python3
"""
运行 MakerMods 仿真 Demo

用法:
    /d/miniconda3/envs/lerobot/python botclaw/run_sim_demo.py

注意: 需要 conda 环境 lerobot
"""

import subprocess
import sys
import os

WORKING_SCRIPTS = os.path.join(os.path.dirname(__file__), "../working_scripts")
DEMO_SCRIPT = os.path.join(WORKING_SCRIPTS, "leader_to_mujoco_calibrated.py")
CONDA_PYTHON = "D:/miniconda3/envs/lerobot/python"


def run_sim_demo():
    """运行仿真 demo"""
    if not os.path.exists(DEMO_SCRIPT):
        print(f"Error: Script not found: {DEMO_SCRIPT}")
        return False

    result = subprocess.run(
        [CONDA_PYTHON, DEMO_SCRIPT],
        cwd=os.path.dirname(os.path.dirname(__file__))
    )
    return result.returncode == 0


if __name__ == "__main__":
    success = run_sim_demo()
    sys.exit(0 if success else 1)
