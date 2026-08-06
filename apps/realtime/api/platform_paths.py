"""Cross-platform paths for Reachy / adapter venvs and temp files."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def venv_executable(sdk_root: Path, name: str) -> Path:
    """Return python/pip/uv inside an adapter or project venv."""
    if is_windows():
        scripts = sdk_root / ".venv" / "Scripts"
        if name == "python":
            return scripts / "python.exe"
        if name == "pip":
            return scripts / "pip.exe"
        return scripts / f"{name}.exe"
    return sdk_root / ".venv" / "bin" / name


def default_log_path(filename: str) -> Path:
    override = os.environ.get("BOTVERSEX_LOG_DIR", "").strip()
    if override:
        return Path(override).expanduser() / filename
    return Path(tempfile.gettempdir()) / filename


def iter_serial_port_candidates() -> list[str]:
    """USB serial ports for Reachy Mini (COM* on Windows, /dev/ttyACM* on Linux)."""
    if is_windows():
        try:
            from serial.tools import list_ports  # type: ignore

            return sorted(p.device for p in list_ports.comports())
        except ImportError:
            return []
    import glob

    return sorted(glob.glob("/dev/ttyACM*"))


def serial_port_exists(port: str) -> bool:
    if is_windows():
        return port.upper().startswith("COM")
    return Path(port).exists()
