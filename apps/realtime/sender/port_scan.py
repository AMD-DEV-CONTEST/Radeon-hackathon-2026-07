"""COM port auto-scanner for Feetech-based runtimes (M6.4).

Scans available serial ports and probes each with a Feetech PING to identify
which port has a leader arm and which has a follower arm.

Usage:
    from sender.port_scan import scan_feetech_ports

    result = scan_feetech_ports()
    # result = {"COM3": {"motor_ids": [1,2,3,4,5,6], "role_hint": "unknown"},
    #           "COM5": {"motor_ids": [1,2,3,4,5,6], "role_hint": "unknown"}}

The scanner does NOT distinguish leader from follower by hardware (they use
identical motors). Role assignment is done by:
  1. env hints: BOTVERSEX_LEADER_COM_HINT / BOTVERSEX_FOLLOWER_COM_HINT
  2. user confirmation (CLI interactive)
  3. fallback: first port found = leader, second = follower
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Ensure lerobot is importable
_LEROBOT_ROOT_DEFAULT = r"D:/Downloads/botverseX MVP/makermods/lerobot-MakerMods-main"
_LEROBOT_ROOT = os.environ.get("BOTVERSEX_LEROBOT_PATH", _LEROBOT_ROOT_DEFAULT)
for _p in (os.path.join(_LEROBOT_ROOT, "src"), _LEROBOT_ROOT):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)


@dataclass
class PortScanResult:
    port: str
    motor_ids: List[int] = field(default_factory=list)
    model: str = ""
    role_hint: str = "unknown"
    error: Optional[str] = None


def list_serial_ports() -> List[str]:
    """List available serial ports on the system."""
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        return sorted([p.device for p in ports])
    except ImportError:
        import glob
        if sys.platform == "win32":
            return [f"COM{i}" for i in range(1, 21)
                    if _port_exists(f"COM{i}")]
        return sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


def _port_exists(port: str) -> bool:
    """Quick check if a COM port can be opened."""
    try:
        import serial
        s = serial.Serial(port, timeout=0.1)
        s.close()
        return True
    except Exception:
        return False


def probe_feetech_port(
    port: str,
    motor_ids: List[int] = (1, 2, 3, 4, 5, 6),
    model: str = "sts3215",
    timeout_s: float = 1.0,
) -> PortScanResult:
    """Try to open a port, send Feetech PING to expected motor IDs."""
    result = PortScanResult(port=port, model=model)

    try:
        from lerobot.motors.feetech import FeetechMotorsBus  # type: ignore
        from lerobot.motors.motors_bus import Motor, MotorNormMode  # type: ignore
    except ImportError as exc:
        result.error = f"lerobot not available: {exc}"
        return result

    try:
        motors_config = {
            f"motor_{i}": Motor(id=i, model=model, norm_mode=MotorNormMode.RANGE_0_100)
            for i in motor_ids
        }
        bus = FeetechMotorsBus(port=port, motors=motors_config)
        bus.connect()

        found = []
        for i in motor_ids:
            try:
                bus.read("Present_Position", f"motor_{i}", normalize=False)
                found.append(i)
            except Exception:
                pass

        bus.disconnect()
        result.motor_ids = found

    except Exception as exc:
        result.error = str(exc)

    return result


def scan_feetech_ports(
    motor_ids: List[int] = (1, 2, 3, 4, 5, 6),
    model: str = "sts3215",
) -> Dict[str, PortScanResult]:
    """Scan all serial ports for Feetech motors.

    Returns dict of port -> PortScanResult for ports that responded.
    """
    ports = list_serial_ports()
    if not ports:
        print("[WARN] no serial ports found on system")
        return {}

    print(f"[INFO] scanning {len(ports)} ports: {ports}")
    results: Dict[str, PortScanResult] = {}

    for port in ports:
        r = probe_feetech_port(port, motor_ids=list(motor_ids), model=model)
        if r.motor_ids:
            results[port] = r
            print(f"  [OK] {port}: found motors {r.motor_ids}")
        elif r.error:
            print(f"  [--] {port}: {r.error}")

    return results


def auto_assign_roles(
    scan_results: Dict[str, PortScanResult],
) -> Dict[str, str]:
    """Assign leader/follower roles to discovered ports.

    Priority:
      1. Environment hints (BOTVERSEX_LEADER_COM_HINT, BOTVERSEX_FOLLOWER_COM_HINT)
      2. Fallback: first port = leader, second = follower
    """
    leader_hint = os.environ.get("BOTVERSEX_LEADER_COM_HINT", "").upper()
    follower_hint = os.environ.get("BOTVERSEX_FOLLOWER_COM_HINT", "").upper()

    assignments: Dict[str, str] = {}
    remaining = list(scan_results.keys())

    if leader_hint and leader_hint in remaining:
        assignments[leader_hint] = "leader"
        remaining.remove(leader_hint)

    if follower_hint and follower_hint in remaining:
        assignments[follower_hint] = "follower"
        remaining.remove(follower_hint)

    for port in remaining:
        if "leader" not in assignments.values():
            assignments[port] = "leader"
        elif "follower" not in assignments.values():
            assignments[port] = "follower"
        else:
            assignments[port] = "extra"

    return assignments


if __name__ == "__main__":
    print("=" * 60)
    print("BotverseX COM Port Scanner (M6.4)")
    print("=" * 60)

    results = scan_feetech_ports()

    if not results:
        print("\n[RESULT] No Feetech motors found on any port")
    else:
        assignments = auto_assign_roles(results)
        print("\n[RESULT] Port assignments:")
        for port, role in assignments.items():
            motors = results[port].motor_ids
            print(f"  {port}: {role} (motors: {motors})")
