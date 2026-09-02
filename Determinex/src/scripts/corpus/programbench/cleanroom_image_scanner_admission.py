#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_image_scanner_admission_record import (
    make_cleanroom_image_scanner_admission_record,
    write_cleanroom_image_scanner_admission_record,
)


class CleanroomImageScannerAdmissionStatus(str, Enum):
    CLEANROOM_SCANNER_ADMISSION_READY = "CLEANROOM_SCANNER_ADMISSION_READY"
    CLEANROOM_SCANNER_ADMITTED = "CLEANROOM_SCANNER_ADMITTED"
    CLEANROOM_SCANNER_REJECTED = "CLEANROOM_SCANNER_REJECTED"
    CLEANROOM_SCANNER_NOT_FOUND = "CLEANROOM_SCANNER_NOT_FOUND"
    CLEANROOM_SCANNER_VERSION_READ = "CLEANROOM_SCANNER_VERSION_READ"
    CLEANROOM_SCANNER_VERSION_FAILED = "CLEANROOM_SCANNER_VERSION_FAILED"
    CLEANROOM_SCANNER_CAPABILITY_VERIFIED = "CLEANROOM_SCANNER_CAPABILITY_VERIFIED"
    CLEANROOM_SCANNER_CAPABILITY_UNSUPPORTED = "CLEANROOM_SCANNER_CAPABILITY_UNSUPPORTED"
    CLEANROOM_SCANNER_BLOCKED_UNKNOWN = "CLEANROOM_SCANNER_BLOCKED_UNKNOWN"
    CLEANROOM_SCANNER_BLOCKED_WRAPPER = "CLEANROOM_SCANNER_BLOCKED_WRAPPER"
    CLEANROOM_SCANNER_BLOCKED_REQUIRES_EXECUTION = "CLEANROOM_SCANNER_BLOCKED_REQUIRES_EXECUTION"
    CLEANROOM_SCANNER_ADMISSION_RECORD_SIGNED = "CLEANROOM_SCANNER_ADMISSION_RECORD_SIGNED"
    CLEANROOM_SCANNER_NOT_CACHE_READY = "CLEANROOM_SCANNER_NOT_CACHE_READY"
    CLEANROOM_SCANNER_NOT_EXECUTABLE = "CLEANROOM_SCANNER_NOT_EXECUTABLE"
    CLEANROOM_SCANNER_TRAINING_INELIGIBLE = "CLEANROOM_SCANNER_TRAINING_INELIGIBLE"


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class CleanroomImageScannerAdmissionConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_cleanroom_image_scanner_admissions")
    command_runner: Callable[[list[str], int], CommandResult] | None = None
    allow_wrappers: bool = False


class ProgramBenchCleanroomImageScannerAdmission:
    def __init__(self, config: CleanroomImageScannerAdmissionConfig | None = None) -> None:
        self.config = config or CleanroomImageScannerAdmissionConfig()

    def admit(self, scanner_name: str = "", scanner_path: Path | None = None) -> dict[str, object]:
        name = _normalize_name(scanner_name)
        discovered = scanner_path
        if discovered is None and name:
            found = shutil.which(_binary_for_name(name))
            discovered = Path(found) if found else None
        if discovered is None and not name:
            for candidate in ("trivy", "grype", "docker"):
                found = shutil.which(candidate)
                if found:
                    name = "docker_scout" if candidate == "docker" else candidate
                    discovered = Path(found)
                    break
        if not name and discovered is not None:
            name = _normalize_name(discovered.stem)

        if not name or name not in {"trivy", "grype", "docker_scout"}:
            return self._write(
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_BLOCKED_UNKNOWN.value,
                name,
                discovered,
                "",
                "",
                "",
                ["unknown_scanner_name"],
            )
        if discovered is None or not discovered.exists():
            return self._write(
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_NOT_FOUND.value,
                name,
                discovered,
                "",
                "",
                "",
                ["scanner_executable_not_found"],
            )
        if _is_wrapper(discovered) and not self.config.allow_wrappers:
            return self._write(
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_BLOCKED_WRAPPER.value,
                name,
                discovered,
                "",
                "",
                "",
                ["wrapper_or_script_scanner_rejected"],
            )

        version_command = _version_command(name, discovered)
        version_result = self._run(version_command, timeout=30)
        if version_result.returncode != 0:
            return self._write(
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_VERSION_FAILED.value,
                name,
                discovered,
                "",
                "",
                "",
                [f"version_command_failed:{version_result.stderr[-300:]}"],
                scanner_command=version_command,
            )
        version = (
            (version_result.stdout or version_result.stderr or "unknown")
            .strip()
            .splitlines()[0][:160]
        )
        capability = _capability_for(name)
        if not capability:
            return self._write(
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_CAPABILITY_UNSUPPORTED.value,
                name,
                discovered,
                version,
                "",
                "",
                ["archive_scan_capability_unknown"],
            )
        if name == "docker_scout":
            cap_result = self._run([str(discovered), "scout", "cves", "--help"], timeout=30)
            text = f"{cap_result.stdout}\n{cap_result.stderr}".lower()
            if cap_result.returncode != 0 or "docker-archive" not in text:
                return self._write(
                    CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_BLOCKED_REQUIRES_EXECUTION.value,
                    name,
                    discovered,
                    version,
                    "image archive scan",
                    capability,
                    ["docker_scout_archive_scan_capability_not_verified"],
                )

        return self._write(
            CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMITTED.value,
            name,
            discovered,
            version,
            "image archive scan",
            capability,
            [],
            scanner_command=_scan_command_template(name, discovered),
            admitted=True,
        )

    def _run(self, command: list[str], timeout: int) -> CommandResult:
        if self.config.command_runner:
            return self.config.command_runner(command, timeout)
        try:
            proc = subprocess.run(
                command,
                cwd=self.config.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return CommandResult(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(124, exc.stdout or "", exc.stderr or "timeout")

    def _write(
        self,
        status: str,
        scanner_name: str,
        scanner_path: Path | None,
        scanner_version: str,
        scanner_mode: str,
        capability: str,
        reasons: list[str],
        *,
        scanner_command: list[str] | None = None,
        admitted: bool = False,
    ) -> dict[str, object]:
        admission_statuses = [
            status,
            CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMISSION_RECORD_SIGNED.value,
            CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_NOT_CACHE_READY.value,
            CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_NOT_EXECUTABLE.value,
            CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_TRAINING_INELIGIBLE.value,
        ]
        if admitted:
            admission_statuses = [
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMISSION_READY.value,
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_VERSION_READ.value,
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_CAPABILITY_VERIFIED.value,
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMITTED.value,
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMISSION_RECORD_SIGNED.value,
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_NOT_CACHE_READY.value,
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_NOT_EXECUTABLE.value,
                CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_TRAINING_INELIGIBLE.value,
            ]
        record = make_cleanroom_image_scanner_admission_record(
            status=status,
            scanner_name=scanner_name,
            scanner_path=str(scanner_path or ""),
            scanner_version=scanner_version,
            scanner_mode=scanner_mode,
            capability=capability,
            admission_statuses=admission_statuses,
            reasons=reasons,
            scanner_command=scanner_command or [],
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_image_scanner_admission_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _normalize_name(name: str) -> str:
    raw = name.strip().lower().replace("-", "_")
    if raw in {"docker", "docker_scout", "scout"}:
        return "docker_scout"
    return raw


def _binary_for_name(name: str) -> str:
    return "docker" if name == "docker_scout" else name


def _is_wrapper(path: Path) -> bool:
    return path.suffix.lower() in {".ps1", ".bat", ".cmd", ".py", ".sh"}


def _version_command(name: str, path: Path) -> list[str]:
    if name == "trivy":
        return [str(path), "--version"]
    if name == "grype":
        return [str(path), "version", "-o", "json"]
    return [str(path), "scout", "version"]


def _capability_for(name: str) -> str:
    if name == "trivy":
        return "trivy image --input <archive.tar> --format json"
    if name == "grype":
        return "grype docker-archive:<archive.tar> -o json"
    if name == "docker_scout":
        return "docker scout cves docker-archive://<archive.tar> --format json"
    return ""


def _scan_command_template(name: str, path: Path) -> list[str]:
    if name == "trivy":
        return [str(path), "image", "--input", "<archive.tar>", "--format", "json"]
    if name == "grype":
        return [str(path), "docker-archive:<archive.tar>", "-o", "json"]
    return [str(path), "scout", "cves", "--format", "json", "docker-archive://<archive.tar>"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Admit an approved scanner for ProgramBench cleanroom image scanning."
    )
    parser.add_argument("--scanner-name", default="")
    parser.add_argument("--scanner-path", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_image_scanner_admissions"),
    )
    parser.add_argument("--allow-wrapper", action="store_true")
    args = parser.parse_args()
    result = ProgramBenchCleanroomImageScannerAdmission(
        CleanroomImageScannerAdmissionConfig(
            root=args.root,
            output_dir=args.output_dir,
            allow_wrappers=args.allow_wrapper,
        )
    ).admit(args.scanner_name, args.scanner_path)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
