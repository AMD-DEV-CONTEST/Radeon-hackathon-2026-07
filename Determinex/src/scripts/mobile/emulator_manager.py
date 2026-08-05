"""
Android emulator manager — lifecycle for mobile agent isolation.
Hard rule: emulator first. No physical device automation by default.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

_REQUIRE_EMULATOR = os.environ.get("DETERMINEX_REQUIRE_EMULATOR", "1") == "1"
_ALLOW_PHYSICAL = os.environ.get("DETERMINEX_ALLOW_PHYSICAL_DEVICE", "0") == "1"


@dataclass
class EmulatorInfo:
    serial: str  # e.g. "emulator-5554"
    avd_name: str  # e.g. "Pixel_6_API_33"
    state: str  # "offline" | "online" | "unknown"
    is_emulator: bool = True


class EmulatorManager:
    """Manages Android emulator lifecycle via avdmanager/emulator CLI."""

    def __init__(self) -> None:
        self._active: dict[str, EmulatorInfo] = {}

    def list_avds(self) -> list[str]:
        try:
            result = subprocess.run(
                ["avdmanager", "list", "avd", "-c"], capture_output=True, text=True, timeout=30
            )
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except FileNotFoundError:
            log.warning("[emulator_manager] avdmanager not found — Android SDK required")
            return []

    def start(self, avd_name: str, headless: bool = True, port: int = 5554) -> EmulatorInfo:
        serial = f"emulator-{port}"
        log.info("[emulator_manager] starting AVD %s → %s", avd_name, serial)
        flags = ["-no-window"] if headless else []
        try:
            subprocess.Popen(
                ["emulator", "-avd", avd_name, "-port", str(port)] + flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise RuntimeError("emulator CLI not found. Ensure Android SDK emulator is in PATH.")
        # Wait for boot
        self._wait_for_boot(serial)
        info = EmulatorInfo(serial=serial, avd_name=avd_name, state="online")
        self._active[serial] = info
        return info

    def stop(self, serial: str) -> None:
        log.info("[emulator_manager] stopping %s", serial)
        try:
            subprocess.run(["adb", "-s", serial, "emu", "kill"], capture_output=True, timeout=10)
        except Exception as exc:
            log.warning("[emulator_manager] stop failed: %s", exc)
        self._active.pop(serial, None)

    def _wait_for_boot(self, serial: str, timeout: int = 120) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                result = subprocess.run(
                    ["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.stdout.strip() == "1":
                    log.info("[emulator_manager] %s boot complete", serial)
                    return
            except Exception:
                pass
            time.sleep(3)
        raise TimeoutError(f"Emulator {serial} did not boot in {timeout}s")

    def require_emulator_or_raise(self, serial: str) -> EmulatorInfo:
        """Enforce emulator isolation. Raises if using physical device and DETERMINEX_REQUIRE_EMULATOR=1."""
        info = self._active.get(serial)
        is_physical = serial.startswith("emulator") is False
        if is_physical and not _ALLOW_PHYSICAL:
            raise RuntimeError(
                f"Mobile agent is connected to a physical device ({serial}). "
                "This is blocked by default. Set DETERMINEX_ALLOW_PHYSICAL_DEVICE=1 to override (not recommended)."
            )
        if info is None:
            if _REQUIRE_EMULATOR:
                raise RuntimeError(
                    f"No active emulator session for {serial}. "
                    "Call EmulatorManager.start() first or set DETERMINEX_REQUIRE_EMULATOR=0."
                )
        return info or EmulatorInfo(serial=serial, avd_name="unknown", state="unknown")

    def list_devices(self) -> list[EmulatorInfo]:
        try:
            result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
            devices = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serial = parts[0]
                    devices.append(
                        EmulatorInfo(
                            serial=serial,
                            avd_name="",
                            state="online",
                            is_emulator=serial.startswith("emulator"),
                        )
                    )
            return devices
        except Exception as exc:
            log.error("[emulator_manager] list_devices failed: %s", exc)
            return []
