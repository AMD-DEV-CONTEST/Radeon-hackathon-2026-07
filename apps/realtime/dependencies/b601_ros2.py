"""ROS2 + MoveIt2 bridge probe for B601."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

_DEFAULT_WS = Path.home() / "rebotarm_ros2"


def workspace_path() -> Path:
    raw = os.environ.get("REBOTARM_ROS2_WS", "")
    return Path(raw).expanduser() if raw else _DEFAULT_WS


def ros_distro() -> str:
    return os.environ.get("ROS_DISTRO", "jazzy")


def ros2_binary() -> Optional[str]:
    return shutil.which("ros2")


def setup_bash() -> Optional[Path]:
    ws = workspace_path()
    install = ws / "install" / "setup.bash"
    if install.is_file():
        return install
    return None


def probe_health() -> Dict[str, Any]:
    ws = workspace_path()
    install = setup_bash()
    ros2 = ros2_binary()
    distro = ros_distro()
    opt_setup = Path(f"/opt/ros/{distro}/setup.bash")

    pkgs_ok = False
    if ros2 and install and opt_setup.is_file():
        try:
            cmd = (
                f"source {opt_setup} && source {install} && "
                "ros2 pkg list | grep -q rebotarmcontroller"
            )
            r = subprocess.run(["bash", "-lc", cmd], capture_output=True, timeout=15)
            pkgs_ok = r.returncode == 0
        except (subprocess.SubprocessError, OSError):
            pkgs_ok = False

    return {
        "ready": bool(ros2 and install and pkgs_ok),
        "ros2": bool(ros2),
        "ros_distro": distro,
        "workspace": str(ws),
        "workspace_exists": ws.is_dir(),
        "install_setup": str(install) if install else None,
        "install_script": "scripts/b601_ros2_install.sh",
    }
