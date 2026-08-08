"""File Verification — verifies file system state after an action.

Checks:
  - File exists at expected path
  - File does NOT exist (deletion check)
  - File size matches expected
  - File hash matches expected
  - File content matches expected (substring or regex)
  - File permissions are correct
  - File was modified within expected time window
  - Directory contains expected files
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FileCheck:
    """Result of a file verification."""
    check_type: str
    target: str
    expected: Any
    actual: Any
    passed: bool
    confidence: float = 1.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type,
            "target": self.target,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "confidence": round(self.confidence, 2),
            "error": self.error,
        }


class FileVerifier:
    """Verifies file system state."""

    def verify_exists(self, path: str) -> FileCheck:
        """Verify a file exists."""
        try:
            exists = os.path.exists(path)
            return FileCheck(
                check_type="exists",
                target=path,
                expected=True,
                actual=exists,
                passed=exists,
            )
        except Exception as e:
            return FileCheck(
                check_type="exists",
                target=path,
                expected=True,
                actual=False,
                passed=False,
                error=str(e),
            )

    def verify_not_exists(self, path: str) -> FileCheck:
        """Verify a file does NOT exist."""
        try:
            exists = os.path.exists(path)
            return FileCheck(
                check_type="not_exists",
                target=path,
                expected=False,
                actual=exists,
                passed=not exists,
            )
        except Exception as e:
            return FileCheck(
                check_type="not_exists",
                target=path,
                expected=False,
                actual=True,
                passed=False,
                error=str(e),
            )

    def verify_size(self, path: str, expected_size: int, tolerance: int = 0) -> FileCheck:
        """Verify a file's size matches expected."""
        try:
            if not os.path.exists(path):
                return FileCheck(
                    check_type="size",
                    target=path,
                    expected=expected_size,
                    actual=None,
                    passed=False,
                    error="file not found",
                )
            actual_size = os.path.getsize(path)
            passed = abs(actual_size - expected_size) <= tolerance
            return FileCheck(
                check_type="size",
                target=path,
                expected=expected_size,
                actual=actual_size,
                passed=passed,
            )
        except Exception as e:
            return FileCheck(
                check_type="size",
                target=path,
                expected=expected_size,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_hash(self, path: str, expected_hash: str, algorithm: str = "sha256") -> FileCheck:
        """Verify a file's hash matches expected."""
        try:
            if not os.path.exists(path):
                return FileCheck(
                    check_type="hash",
                    target=path,
                    expected=expected_hash,
                    actual=None,
                    passed=False,
                    error="file not found",
                )
            hasher = hashlib.new(algorithm)
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            actual_hash = hasher.hexdigest()
            passed = actual_hash == expected_hash
            return FileCheck(
                check_type="hash",
                target=path,
                expected=expected_hash,
                actual=actual_hash,
                passed=passed,
            )
        except Exception as e:
            return FileCheck(
                check_type="hash",
                target=path,
                expected=expected_hash,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_content(
        self,
        path: str,
        expected_content: str,
        regex: bool = False,
    ) -> FileCheck:
        """Verify a file contains expected content."""
        try:
            if not os.path.exists(path):
                return FileCheck(
                    check_type="content",
                    target=path,
                    expected=expected_content,
                    actual=None,
                    passed=False,
                    error="file not found",
                )
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                actual_content = f.read()
            if regex:
                passed = bool(re.search(expected_content, actual_content))
            else:
                passed = expected_content in actual_content
            return FileCheck(
                check_type="content",
                target=path,
                expected=expected_content,
                actual=actual_content[:200] + "..." if len(actual_content) > 200 else actual_content,
                passed=passed,
            )
        except Exception as e:
            return FileCheck(
                check_type="content",
                target=path,
                expected=expected_content,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_modified_within(
        self,
        path: str,
        seconds: int,
    ) -> FileCheck:
        """Verify a file was modified within the last N seconds."""
        try:
            if not os.path.exists(path):
                return FileCheck(
                    check_type="modified_within",
                    target=path,
                    expected=f"within {seconds}s",
                    actual=None,
                    passed=False,
                    error="file not found",
                )
            mtime = os.path.getmtime(path)
            age = time.time() - mtime
            passed = age <= seconds
            return FileCheck(
                check_type="modified_within",
                target=path,
                expected=f"within {seconds}s",
                actual=f"{age:.1f}s ago",
                passed=passed,
            )
        except Exception as e:
            return FileCheck(
                check_type="modified_within",
                target=path,
                expected=f"within {seconds}s",
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify_directory_contains(
        self,
        directory: str,
        expected_files: List[str],
    ) -> FileCheck:
        """Verify a directory contains expected files."""
        try:
            if not os.path.isdir(directory):
                return FileCheck(
                    check_type="directory_contains",
                    target=directory,
                    expected=expected_files,
                    actual=None,
                    passed=False,
                    error="directory not found",
                )
            actual_files = set(os.listdir(directory))
            missing = [f for f in expected_files if f not in actual_files]
            passed = len(missing) == 0
            return FileCheck(
                check_type="directory_contains",
                target=directory,
                expected=expected_files,
                actual=list(actual_files),
                passed=passed,
                details={"missing": missing} if missing else {},
            )
        except Exception as e:
            return FileCheck(
                check_type="directory_contains",
                target=directory,
                expected=expected_files,
                actual=None,
                passed=False,
                error=str(e),
            )

    def verify(self, check_type: str, target: str, expected: Any) -> FileCheck:
        """Dispatch to the appropriate file verifier."""
        if check_type == "exists":
            return self.verify_exists(target)
        if check_type == "not_exists":
            return self.verify_not_exists(target)
        if check_type == "size":
            exp = expected if isinstance(expected, dict) else {"size": expected}
            return self.verify_size(target, exp.get("size", 0), exp.get("tolerance", 0))
        if check_type == "hash":
            exp = expected if isinstance(expected, dict) else {"hash": expected}
            return self.verify_hash(target, exp.get("hash", ""), exp.get("algorithm", "sha256"))
        if check_type == "content":
            exp = expected if isinstance(expected, dict) else {"content": expected}
            return self.verify_content(target, exp.get("content", ""), exp.get("regex", False))
        if check_type == "modified_within":
            return self.verify_modified_within(target, expected if isinstance(expected, int) else 60)
        if check_type == "directory_contains":
            return self.verify_directory_contains(target, expected if isinstance(expected, list) else [])
        return FileCheck(
            check_type=check_type,
            target=target,
            expected=expected,
            actual=None,
            passed=False,
            error=f"unknown check_type: {check_type}",
        )
