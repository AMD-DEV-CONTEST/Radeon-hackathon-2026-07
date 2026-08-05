"""Quality checks for source-code corpus intake."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_CODE_EXTENSIONS = {
    ".py",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".cc",
    ".hpp",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rb",
    ".php",
    ".sql",
    ".sh",
}


@dataclass
class QualityReport:
    passed: bool
    code_files: int
    total_bytes: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "code_files": self.code_files,
            "total_bytes": self.total_bytes,
            "reasons": self.reasons,
        }


def assess(
    path: Path, *, min_code_files: int = 1, max_total_bytes: int = 50_000_000
) -> QualityReport:
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    code_files = 0
    total_bytes = 0
    reasons: list[str] = []
    for file_path in files:
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        total_bytes += size
        if file_path.suffix.lower() in _CODE_EXTENSIONS:
            code_files += 1
    if code_files < min_code_files:
        reasons.append("no supported code files found")
    if total_bytes > max_total_bytes:
        reasons.append(f"source too large: {total_bytes} bytes")
    return QualityReport(
        passed=not reasons, code_files=code_files, total_bytes=total_bytes, reasons=reasons
    )
