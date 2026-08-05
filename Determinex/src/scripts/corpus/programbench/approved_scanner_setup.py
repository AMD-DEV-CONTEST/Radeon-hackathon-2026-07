#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.approved_scanner_setup_record import (
    make_approved_scanner_setup_record,
    write_approved_scanner_setup_record,
)
from corpus.programbench.cleanroom_image_scanner_admission import (
    CleanroomImageScannerAdmissionConfig,
    CleanroomImageScannerAdmissionStatus,
    CommandResult,
    ProgramBenchCleanroomImageScannerAdmission,
)


class ApprovedScannerSetupStatus(str, Enum):
    APPROVED_SCANNER_SETUP_READY = "APPROVED_SCANNER_SETUP_READY"
    APPROVED_SCANNER_FOUND = "APPROVED_SCANNER_FOUND"
    APPROVED_SCANNER_NOT_FOUND = "APPROVED_SCANNER_NOT_FOUND"
    APPROVED_SCANNER_OPERATOR_PATH_ACCEPTED = "APPROVED_SCANNER_OPERATOR_PATH_ACCEPTED"
    APPROVED_SCANNER_OPERATOR_PATH_REJECTED = "APPROVED_SCANNER_OPERATOR_PATH_REJECTED"
    APPROVED_SCANNER_VERSION_VERIFIED = "APPROVED_SCANNER_VERSION_VERIFIED"
    APPROVED_SCANNER_CAPABILITY_VERIFIED = "APPROVED_SCANNER_CAPABILITY_VERIFIED"
    APPROVED_SCANNER_SETUP_REQUIRED = "APPROVED_SCANNER_SETUP_REQUIRED"
    APPROVED_SCANNER_ADMISSION_RERUN_READY = "APPROVED_SCANNER_ADMISSION_RERUN_READY"
    APPROVED_SCANNER_ADMISSION_PASSED = "APPROVED_SCANNER_ADMISSION_PASSED"
    APPROVED_SCANNER_ADMISSION_FAILED = "APPROVED_SCANNER_ADMISSION_FAILED"
    CLEANROOM_IMAGE_NOT_EXECUTABLE = "CLEANROOM_IMAGE_NOT_EXECUTABLE"
    CLEANROOM_IMAGE_TRAINING_INELIGIBLE = "CLEANROOM_IMAGE_TRAINING_INELIGIBLE"


@dataclass(slots=True)
class ApprovedScannerSetupConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_approved_scanner_setup")
    admission_output_dir: Path = Path(
        "assurance/evidence/programbench_cleanroom_image_scanner_admissions"
    )
    command_runner: Callable[[list[str], int], CommandResult] | None = None
    which: Callable[[str], str | None] = shutil.which
    allow_wrappers: bool = False


class ProgramBenchApprovedScannerSetup:
    def __init__(self, config: ApprovedScannerSetupConfig | None = None) -> None:
        self.config = config or ApprovedScannerSetupConfig()

    def setup(self, scanner_name: str = "", scanner_path: Path | None = None) -> dict[str, object]:
        normalized = _normalize_name(scanner_name)
        operator_supplied = scanner_path is not None
        if operator_supplied and not normalized:
            normalized = _infer_name(scanner_path)
        if operator_supplied:
            return self._admit_candidate(normalized, scanner_path, operator_supplied=True)

        if normalized:
            found = self.config.which(_binary_for_name(normalized))
            return self._admit_candidate(normalized, Path(found) if found else None)

        for candidate in ("trivy", "grype"):
            found = self.config.which(candidate)
            if found:
                return self._admit_candidate(candidate, Path(found))

        return self._write(
            ApprovedScannerSetupStatus.APPROVED_SCANNER_SETUP_REQUIRED.value,
            "",
            "",
            "",
            "",
            "",
            "",
            [
                ApprovedScannerSetupStatus.APPROVED_SCANNER_NOT_FOUND.value,
                ApprovedScannerSetupStatus.APPROVED_SCANNER_SETUP_REQUIRED.value,
            ],
            ["no_trivy_or_grype_found"],
            _install_instructions(),
        )

    def _admit_candidate(
        self, scanner_name: str, scanner_path: Path | None, *, operator_supplied: bool = False
    ) -> dict[str, object]:
        if scanner_name not in {"trivy", "grype", "docker_scout"}:
            return self._write(
                ApprovedScannerSetupStatus.APPROVED_SCANNER_OPERATOR_PATH_REJECTED.value
                if operator_supplied
                else ApprovedScannerSetupStatus.APPROVED_SCANNER_SETUP_REQUIRED.value,
                scanner_name,
                str(scanner_path or ""),
                "",
                "",
                "",
                "",
                [ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_FAILED.value],
                ["unknown_scanner_name"],
                _install_instructions(),
            )

        admission = ProgramBenchCleanroomImageScannerAdmission(
            CleanroomImageScannerAdmissionConfig(
                root=self.config.root,
                output_dir=self.config.admission_output_dir,
                command_runner=self.config.command_runner,
                allow_wrappers=self.config.allow_wrappers,
            )
        ).admit(scanner_name, scanner_path)
        admission_record = admission["record"]
        admission_status = str(admission_record.get("status") or "")
        admitted = (
            admission_status
            == CleanroomImageScannerAdmissionStatus.CLEANROOM_SCANNER_ADMITTED.value
        )
        statuses = [
            ApprovedScannerSetupStatus.APPROVED_SCANNER_SETUP_READY.value,
            ApprovedScannerSetupStatus.APPROVED_SCANNER_FOUND.value
            if scanner_path
            else ApprovedScannerSetupStatus.APPROVED_SCANNER_NOT_FOUND.value,
            ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_RERUN_READY.value,
            ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_PASSED.value
            if admitted
            else ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_FAILED.value,
            ApprovedScannerSetupStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value,
            ApprovedScannerSetupStatus.CLEANROOM_IMAGE_TRAINING_INELIGIBLE.value,
        ]
        if operator_supplied:
            statuses.append(
                ApprovedScannerSetupStatus.APPROVED_SCANNER_OPERATOR_PATH_ACCEPTED.value
                if admitted
                else ApprovedScannerSetupStatus.APPROVED_SCANNER_OPERATOR_PATH_REJECTED.value
            )
        if admitted:
            statuses.extend(
                [
                    ApprovedScannerSetupStatus.APPROVED_SCANNER_VERSION_VERIFIED.value,
                    ApprovedScannerSetupStatus.APPROVED_SCANNER_CAPABILITY_VERIFIED.value,
                ]
            )
        reasons = list(admission_record.get("reasons") or [])
        return self._write(
            ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_PASSED.value
            if admitted
            else ApprovedScannerSetupStatus.APPROVED_SCANNER_ADMISSION_FAILED.value,
            str(admission_record.get("scanner_name") or scanner_name),
            str(admission_record.get("scanner_path") or scanner_path or ""),
            str(admission_record.get("scanner_version") or ""),
            str(admission_record.get("capability") or ""),
            str(admission.get("record_path") or ""),
            admission_status,
            statuses,
            reasons,
            [] if admitted else _install_instructions(),
        )

    def _write(
        self,
        status: str,
        scanner_name: str,
        scanner_path: str,
        scanner_version: str,
        capability: str,
        admission_record_path: str,
        admission_status: str,
        setup_statuses: list[str],
        reasons: list[str],
        install_instructions: list[str],
    ) -> dict[str, object]:
        setup_statuses = [
            *setup_statuses,
            ApprovedScannerSetupStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value,
            ApprovedScannerSetupStatus.CLEANROOM_IMAGE_TRAINING_INELIGIBLE.value,
        ]
        record = make_approved_scanner_setup_record(
            status=status,
            scanner_name=scanner_name,
            scanner_path=scanner_path,
            scanner_version=scanner_version,
            capability=capability,
            setup_statuses=list(dict.fromkeys(setup_statuses)),
            reasons=reasons,
            install_instructions=install_instructions,
            admission_record_path=admission_record_path,
            admission_status=admission_status,
            cache_ready=False,
            executable=False,
        )
        path = write_approved_scanner_setup_record(record, self._resolve(self.config.output_dir))
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


def _infer_name(path: Path | None) -> str:
    if path is None:
        return ""
    stem = path.stem.lower().replace("-", "_")
    if stem in {"docker", "scout"}:
        return "docker_scout"
    return stem


def _install_instructions() -> list[str]:
    return [
        "Install Trivy from the official Aqua Security release or package source and provide its executable path.",
        "Alternatively install Grype from the official Anchore release or package source and provide its executable path.",
        "Rerun scanner admission after the scanner version and archive-scan capability are available.",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up or admit an approved scanner path for ProgramBench cleanroom images."
    )
    parser.add_argument("--scanner-name", default="")
    parser.add_argument("--scanner-path", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_approved_scanner_setup"),
    )
    parser.add_argument(
        "--admission-output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_image_scanner_admissions"),
    )
    parser.add_argument("--allow-wrapper", action="store_true")
    args = parser.parse_args()
    result = ProgramBenchApprovedScannerSetup(
        ApprovedScannerSetupConfig(
            root=args.root,
            output_dir=args.output_dir,
            admission_output_dir=args.admission_output_dir,
            allow_wrappers=args.allow_wrapper,
        )
    ).setup(args.scanner_name, args.scanner_path)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
