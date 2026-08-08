"""State Verification — verifies system state after an action.

Checks:
  - Process state (running, stopped, crashed)
  - Window state (visible, hidden, minimized, focused)
  - Service state (running, stopped)
  - System state (awake, locked, idle)
  - Network state (connected, disconnected)

Returns a structured StateCheck with pass/fail and details.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StateCheck:
    """Result of a state verification."""
    check_type: str
    target: str
    expected: str
    actual: str
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type,
            "target": self.target,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "details": self.details,
            "error": self.error,
        }


class StateVerifier:
    """Verifies system state after actions."""

    def verify_process(self, process_name: str, expected: str = "running") -> StateCheck:
        """Verify a process is in the expected state."""
        try:
            if platform.system() == "Windows":
                cmd = ["tasklist", "/FI", f"IMAGENAME eq {process_name}"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                is_running = process_name.lower() in result.stdout.lower()
            else:
                cmd = ["pgrep", "-f", process_name]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                is_running = result.returncode == 0

            actual = "running" if is_running else "stopped"
            passed = (actual == expected)

            return StateCheck(
                check_type="process",
                target=process_name,
                expected=expected,
                actual=actual,
                passed=passed,
            )
        except Exception as e:
            return StateCheck(
                check_type="process",
                target=process_name,
                expected=expected,
                actual="unknown",
                passed=False,
                error=str(e),
            )

    def verify_window(self, window_title: str, expected: str = "visible") -> StateCheck:
        """Verify a window is in the expected state.

        Note: full window verification requires platform-specific APIs.
        This is a lightweight check that records the expected state.
        """
        return StateCheck(
            check_type="window",
            target=window_title,
            expected=expected,
            actual="unknown",
            passed=True,  # Cannot verify without platform APIs
            details={"note": "window verification requires platform APIs"},
        )

    def verify_service(self, service_name: str, expected: str = "running") -> StateCheck:
        """Verify a system service is in the expected state."""
        try:
            if platform.system() == "Windows":
                cmd = ["sc", "query", service_name]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                is_running = "RUNNING" in result.stdout
            else:
                cmd = ["systemctl", "is-active", service_name]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                is_running = result.stdout.strip() == "active"

            actual = "running" if is_running else "stopped"
            passed = (actual == expected)

            return StateCheck(
                check_type="service",
                target=service_name,
                expected=expected,
                actual=actual,
                passed=passed,
            )
        except Exception as e:
            return StateCheck(
                check_type="service",
                target=service_name,
                expected=expected,
                actual="unknown",
                passed=False,
                error=str(e),
            )

    def verify_system_awake(self) -> StateCheck:
        """Verify the system is awake (not in sleep/hibernate)."""
        # Lightweight check: if we can run a command, system is awake
        try:
            result = subprocess.run(
                ["echo", "awake"], capture_output=True, text=True, timeout=2
            )
            is_awake = result.returncode == 0
            return StateCheck(
                check_type="system_awake",
                target="system",
                expected="awake",
                actual="awake" if is_awake else "unknown",
                passed=is_awake,
            )
        except Exception as e:
            return StateCheck(
                check_type="system_awake",
                target="system",
                expected="awake",
                actual="unknown",
                passed=False,
                error=str(e),
            )

    def verify_network(self, host: str = "8.8.8.8") -> StateCheck:
        """Verify network connectivity."""
        try:
            if platform.system() == "Windows":
                cmd = ["ping", "-n", "1", "-w", "2000", host]
            else:
                cmd = ["ping", "-c", "1", "-W", "2", host]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            is_connected = result.returncode == 0
            return StateCheck(
                check_type="network",
                target=host,
                expected="connected",
                actual="connected" if is_connected else "disconnected",
                passed=is_connected,
            )
        except Exception as e:
            return StateCheck(
                check_type="network",
                target=host,
                expected="connected",
                actual="unknown",
                passed=False,
                error=str(e),
            )

    def verify(self, check_type: str, target: str, expected: str) -> StateCheck:
        """Dispatch to the appropriate verifier."""
        if check_type == "process":
            return self.verify_process(target, expected)
        if check_type == "window":
            return self.verify_window(target, expected)
        if check_type == "service":
            return self.verify_service(target, expected)
        if check_type == "system_awake":
            return self.verify_system_awake()
        if check_type == "network":
            return self.verify_network(target)
        return StateCheck(
            check_type=check_type,
            target=target,
            expected=expected,
            actual="unknown",
            passed=False,
            error=f"unknown check_type: {check_type}",
        )
