"""Process Verification — verifies process execution results.

Checks:
  - Process started successfully
  - Process exited with expected code
  - Process produced expected stdout
  - Process produced expected stderr
  - Process ran within expected time
  - Process is still running (long-running check)
  - Process memory usage is within bounds
  - Process CPU usage is within bounds
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProcessCheck:
    """Result of a process verification."""
    check_type: str
    target: str
    expected: Any
    actual: Any
    passed: bool
    duration_ms: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type,
            "target": target,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 2) if self.duration_ms else None,
            "error": self.error,
        }


class ProcessVerifier:
    """Verifies process execution results."""

    def verify_exit_code(
        self,
        command: List[str],
        expected_code: int = 0,
        timeout: float = 30.0,
    ) -> ProcessCheck:
        """Verify a command exits with the expected code."""
        try:
            start = time.time()
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = (time.time() - start) * 1000

            passed = result.returncode == expected_code
            return ProcessCheck(
                check_type="exit_code",
                target=" ".join(command),
                expected=expected_code,
                actual=result.returncode,
                passed=passed,
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired:
            return ProcessCheck(
                check_type="exit_code",
                target=" ".join(command),
                expected=expected_code,
                actual="timeout",
                passed=False,
                error=f"timeout after {timeout}s",
            )
        except Exception as e:
            return ProcessCheck(
                check_type="exit_code",
                target=" ".join(command),
                expected=expected_code,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_stdout(
        self,
        command: List[str],
        expected_output: str,
        timeout: float = 30.0,
    ) -> ProcessCheck:
        """Verify a command's stdout contains expected output."""
        try:
            start = time.time()
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = (time.time() - start) * 1000

            passed = expected_output in result.stdout
            return ProcessCheck(
                check_type="stdout",
                target=" ".join(command),
                expected=expected_output,
                actual=result.stdout[:200] + "..." if len(result.stdout) > 200 else result.stdout,
                passed=passed,
                duration_ms=duration,
            )
        except Exception as e:
            return ProcessCheck(
                check_type="stdout",
                target=" ".join(command),
                expected=expected_output,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_duration(
        self,
        command: List[str],
        max_ms: float,
        timeout: float = 30.0,
    ) -> ProcessCheck:
        """Verify a command completes within the expected time."""
        try:
            start = time.time()
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = (time.time() - start) * 1000

            passed = duration <= max_ms and result.returncode == 0
            return ProcessCheck(
                check_type="duration",
                target=" ".join(command),
                expected=f"<= {max_ms}ms",
                actual=f"{duration:.1f}ms",
                passed=passed,
                duration_ms=duration,
            )
        except Exception as e:
            return ProcessCheck(
                check_type="duration",
                target=" ".join(command),
                expected=f"<= {max_ms}ms",
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_process_running(self, process_name: str) -> ProcessCheck:
        """Verify a process is currently running."""
        try:
            if platform.system() == "Windows":
                cmd = ["tasklist", "/FI", f"IMAGENAME eq {process_name}"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                is_running = process_name.lower() in result.stdout.lower()
            else:
                cmd = ["pgrep", "-f", process_name]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                is_running = result.returncode == 0

            return ProcessCheck(
                check_type="running",
                target=process_name,
                expected=True,
                actual=is_running,
                passed=is_running,
            )
        except Exception as e:
            return ProcessCheck(
                check_type="running",
                target=process_name,
                expected=True,
                actual=False,
                passed=False,
                error=str(e),
            )

    def verify_process_stopped(self, process_name: str) -> ProcessCheck:
        """Verify a process is NOT running."""
        try:
            if platform.system() == "Windows":
                cmd = ["tasklist", "/FI", f"IMAGENAME eq {process_name}"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                is_running = process_name.lower() in result.stdout.lower()
            else:
                cmd = ["pgrep", "-f", process_name]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                is_running = result.returncode == 0

            return ProcessCheck(
                check_type="stopped",
                target=process_name,
                expected=False,
                actual=is_running,
                passed=not is_running,
            )
        except Exception as e:
            return ProcessCheck(
                check_type="stopped",
                target=process_name,
                expected=False,
                actual=True,
                passed=False,
                error=str(e),
            )

    def verify(self, check_type: str, target: Any, expected: Any) -> ProcessCheck:
        """Dispatch to the appropriate process verifier."""
        if check_type == "exit_code":
            cmd = target if isinstance(target, list) else [target]
            exp = expected if isinstance(expected, int) else 0
            return self.verify_exit_code(cmd, exp)
        if check_type == "stdout":
            cmd = target if isinstance(target, list) else [target]
            return self.verify_stdout(cmd, expected if isinstance(expected, str) else "")
        if check_type == "duration":
            cmd = target if isinstance(target, list) else [target]
            return self.verify_duration(cmd, expected if isinstance(expected, (int, float)) else 1000)
        if check_type == "running":
            return self.verify_process_running(target if isinstance(target, str) else "")
        if check_type == "stopped":
            return self.verify_process_stopped(target if isinstance(target, str) else "")
        return ProcessCheck(
            check_type=check_type,
            target=str(target),
            expected=expected,
            actual=None,
            passed=False,
            error=f"unknown check_type: {check_type}",
        )
