#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_image_import_record import verify_cleanroom_image_import_record
from corpus.programbench.cleanroom_image_scan_record import (
    make_cleanroom_image_scan_record,
    write_cleanroom_image_scan_record,
)


class CleanroomImageScanStatus(str, Enum):
    CLEANROOM_IMAGE_SCAN_READY = "CLEANROOM_IMAGE_SCAN_READY"
    CLEANROOM_IMAGE_SCAN_UNAVAILABLE = "CLEANROOM_IMAGE_SCAN_UNAVAILABLE"
    CLEANROOM_IMAGE_SCAN_STARTED = "CLEANROOM_IMAGE_SCAN_STARTED"
    CLEANROOM_IMAGE_SCAN_PASSED = "CLEANROOM_IMAGE_SCAN_PASSED"
    CLEANROOM_IMAGE_SCAN_FAILED = "CLEANROOM_IMAGE_SCAN_FAILED"
    CLEANROOM_IMAGE_SCAN_ERROR = "CLEANROOM_IMAGE_SCAN_ERROR"
    CLEANROOM_IMAGE_SCAN_TIMEOUT = "CLEANROOM_IMAGE_SCAN_TIMEOUT"
    CLEANROOM_IMAGE_SCAN_BLOCKED_DIGEST_MISMATCH = "CLEANROOM_IMAGE_SCAN_BLOCKED_DIGEST_MISMATCH"
    CLEANROOM_IMAGE_SCAN_BLOCKED_MISSING_ARTIFACT = "CLEANROOM_IMAGE_SCAN_BLOCKED_MISSING_ARTIFACT"
    CLEANROOM_IMAGE_SCAN_BLOCKED_NO_IMPORT_RECORD = "CLEANROOM_IMAGE_SCAN_BLOCKED_NO_IMPORT_RECORD"
    CLEANROOM_IMAGE_SCAN_RECORD_SIGNED = "CLEANROOM_IMAGE_SCAN_RECORD_SIGNED"
    CLEANROOM_IMAGE_NOT_EXECUTABLE = "CLEANROOM_IMAGE_NOT_EXECUTABLE"
    CLEANROOM_IMAGE_TRAINING_INELIGIBLE = "CLEANROOM_IMAGE_TRAINING_INELIGIBLE"


@dataclass(slots=True)
class ScannerSpec:
    name: str
    version: str
    command: list[str]


@dataclass(slots=True)
class ScannerResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(slots=True)
class CleanroomImageScanConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_cleanroom_image_scans")
    timeout_seconds: int = 900
    scanner_override: ScannerSpec | None = None
    scanner_runner: Callable[[ScannerSpec, Path, int], ScannerResult] | None = None


class ProgramBenchCleanroomImageScan:
    def __init__(self, config: CleanroomImageScanConfig | None = None) -> None:
        self.config = config or CleanroomImageScanConfig()

    def scan(self, import_record_path: Path) -> dict[str, Any]:
        import_path = self._resolve(import_record_path)
        if not import_path.is_file():
            return self._blocked(
                CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_BLOCKED_NO_IMPORT_RECORD.value,
                import_path,
                {},
                None,
                "",
                0,
                ["import_record_missing"],
            )
        import_record = _read_json(import_path)
        if not verify_cleanroom_image_import_record(import_record):
            return self._blocked(
                CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_BLOCKED_NO_IMPORT_RECORD.value,
                import_path,
                import_record,
                None,
                "",
                0,
                ["import_record_signature_invalid"],
            )

        artifact_path = self._resolve(Path(str(import_record.get("artifact_import_path") or "")))
        if not str(import_record.get("artifact_import_path") or "") or not artifact_path.is_file():
            return self._blocked(
                CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_BLOCKED_MISSING_ARTIFACT.value,
                import_path,
                import_record,
                artifact_path if str(import_record.get("artifact_import_path") or "") else None,
                "",
                0,
                ["artifact_path_missing"],
            )

        file_sha = _sha256(artifact_path)
        file_size = artifact_path.stat().st_size
        expected = str(import_record.get("expected_digest") or "")
        observed = str(import_record.get("observed_digest") or "")
        if not expected.startswith("sha256:") or observed != expected:
            return self._blocked(
                CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_BLOCKED_DIGEST_MISMATCH.value,
                import_path,
                import_record,
                artifact_path,
                file_sha,
                file_size,
                ["import_record_observed_digest_does_not_match_expected_digest"],
            )

        scanner = self.config.scanner_override or _detect_scanner(artifact_path)
        if scanner is None:
            return self._blocked(
                CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_UNAVAILABLE.value,
                import_path,
                import_record,
                artifact_path,
                file_sha,
                file_size,
                ["no_approved_scanner_available"],
            )

        started = _now()
        result = self._run_scanner(scanner, artifact_path)
        completed = _now()
        if result.timed_out:
            return self._write_scan_record(
                status=CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_TIMEOUT.value,
                import_path=import_path,
                import_record=import_record,
                artifact_path=artifact_path,
                file_sha=file_sha,
                file_size=file_size,
                scanner=scanner,
                started_at=started,
                completed_at=completed,
                findings_summary={},
                normalized_findings=[],
                reasons=["scanner_timeout"],
            )
        if result.returncode != 0:
            return self._write_scan_record(
                status=CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_ERROR.value,
                import_path=import_path,
                import_record=import_record,
                artifact_path=artifact_path,
                file_sha=file_sha,
                file_size=file_size,
                scanner=scanner,
                started_at=started,
                completed_at=completed,
                findings_summary={},
                normalized_findings=[],
                reasons=[f"scanner_error:{result.stderr[-500:]}"],
            )

        normalized = normalize_scan_output(scanner.name, result.stdout)
        summary = summarize_findings(normalized)
        status = (
            CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_PASSED.value
            if int(summary.get("critical") or 0) == 0 and int(summary.get("high") or 0) == 0
            else CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_FAILED.value
        )
        reasons = (
            []
            if status == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_PASSED.value
            else ["critical_or_high_findings_present"]
        )
        return self._write_scan_record(
            status=status,
            import_path=import_path,
            import_record=import_record,
            artifact_path=artifact_path,
            file_sha=file_sha,
            file_size=file_size,
            scanner=scanner,
            started_at=started,
            completed_at=completed,
            findings_summary=summary,
            normalized_findings=normalized,
            reasons=reasons,
        )

    def _run_scanner(self, scanner: ScannerSpec, artifact_path: Path) -> ScannerResult:
        if self.config.scanner_runner:
            return self.config.scanner_runner(scanner, artifact_path, self.config.timeout_seconds)
        try:
            proc = subprocess.run(
                scanner.command,
                cwd=self.config.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.timeout_seconds,
                check=False,
            )
            return ScannerResult(proc.returncode, proc.stdout, proc.stderr, False)
        except subprocess.TimeoutExpired as exc:
            return ScannerResult(124, exc.stdout or "", exc.stderr or "", True)
        except OSError as exc:
            return ScannerResult(126, "", f"scanner_execution_error:{exc}", False)

    def _blocked(
        self,
        status: str,
        import_path: Path,
        import_record: dict[str, Any],
        artifact_path: Path | None,
        file_sha: str,
        file_size: int,
        reasons: list[str],
    ) -> dict[str, Any]:
        return self._write_scan_record(
            status=status,
            import_path=import_path,
            import_record=import_record,
            artifact_path=artifact_path,
            file_sha=file_sha,
            file_size=file_size,
            scanner=ScannerSpec("", "", []),
            started_at="",
            completed_at="",
            findings_summary={},
            normalized_findings=[],
            reasons=reasons,
        )

    def _write_scan_record(
        self,
        *,
        status: str,
        import_path: Path,
        import_record: dict[str, Any],
        artifact_path: Path | None,
        file_sha: str,
        file_size: int,
        scanner: ScannerSpec,
        started_at: str,
        completed_at: str,
        findings_summary: dict[str, Any],
        normalized_findings: list[dict[str, Any]],
        reasons: list[str],
    ) -> dict[str, Any]:
        statuses = [
            status,
            CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_RECORD_SIGNED.value,
            CleanroomImageScanStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value,
            CleanroomImageScanStatus.CLEANROOM_IMAGE_TRAINING_INELIGIBLE.value,
        ]
        if status in {
            CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_PASSED.value,
            CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_FAILED.value,
            CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_ERROR.value,
            CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_TIMEOUT.value,
        }:
            statuses.insert(0, CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_STARTED.value)
        if status == CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_PASSED.value:
            statuses.insert(0, CleanroomImageScanStatus.CLEANROOM_IMAGE_SCAN_READY.value)
        record = make_cleanroom_image_scan_record(
            status=status,
            import_record=_rel(self.config.root, import_path),
            image_reference=str(import_record.get("image_reference") or ""),
            artifact_path=_rel(self.config.root, artifact_path) if artifact_path else "",
            expected_digest=str(import_record.get("expected_digest") or ""),
            observed_digest=str(import_record.get("observed_digest") or ""),
            file_sha256=file_sha,
            file_size=file_size,
            scanner=scanner.name,
            scanner_version=scanner.version,
            scanner_command=scanner.command,
            scan_statuses=statuses,
            started_at=started_at,
            completed_at=completed_at,
            findings_summary=findings_summary,
            normalized_findings=normalized_findings,
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_image_scan_record(record, self._resolve(self.config.output_dir))
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def normalize_scan_output(scanner: str, raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    data = json.loads(raw)
    if scanner == "trivy":
        return _normalize_trivy(data)
    if scanner == "grype":
        return _normalize_grype(data)
    return []


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "unknown": 0,
        "total": len(findings),
    }
    for finding in findings:
        sev = str(finding.get("severity") or "unknown").lower()
        if sev not in summary:
            sev = "unknown"
        summary[sev] += 1
    return summary


def _normalize_trivy(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for result in data.get("Results", []) or []:
        target = str(result.get("Target") or "")
        for vuln in result.get("Vulnerabilities", []) or []:
            out.append(
                {
                    "id": str(vuln.get("VulnerabilityID") or ""),
                    "package": str(vuln.get("PkgName") or ""),
                    "installed_version": str(vuln.get("InstalledVersion") or ""),
                    "fixed_version": str(vuln.get("FixedVersion") or ""),
                    "severity": str(vuln.get("Severity") or "UNKNOWN").lower(),
                    "target": target,
                }
            )
    return sorted(
        out, key=lambda item: (item["severity"], item["id"], item["package"], item["target"])
    )


def _normalize_grype(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in data.get("matches", []) or []:
        vuln = match.get("vulnerability") if isinstance(match.get("vulnerability"), dict) else {}
        artifact = match.get("artifact") if isinstance(match.get("artifact"), dict) else {}
        out.append(
            {
                "id": str(vuln.get("id") or ""),
                "package": str(artifact.get("name") or ""),
                "installed_version": str(artifact.get("version") or ""),
                "fixed_version": str(
                    vuln.get("fix", {}).get("versions", [""])[0]
                    if isinstance(vuln.get("fix"), dict) and vuln.get("fix", {}).get("versions")
                    else ""
                ),
                "severity": str(vuln.get("severity") or "UNKNOWN").lower(),
                "target": str(artifact.get("type") or ""),
            }
        )
    return sorted(
        out, key=lambda item: (item["severity"], item["id"], item["package"], item["target"])
    )


def _detect_scanner(artifact_path: Path) -> ScannerSpec | None:
    trivy = shutil.which("trivy")
    if trivy:
        version = _detected_version([trivy, "--version"])
        if version is not None:
            return ScannerSpec(
                "trivy",
                version,
                [trivy, "image", "--input", str(artifact_path), "--format", "json"],
            )
    grype = shutil.which("grype")
    if grype:
        version = _detected_version([grype, "version", "-o", "json"])
        if version is not None:
            return ScannerSpec(
                "grype", version, [grype, f"docker-archive:{artifact_path}", "-o", "json"]
            )
    docker = shutil.which("docker")
    if docker and _docker_scout_usable(docker):
        version = _version([docker, "scout", "version"])
        return ScannerSpec(
            "docker_scout",
            version,
            [docker, "scout", "cves", "--format", "json", f"docker-archive://{artifact_path}"],
        )
    return None


def _docker_scout_usable(docker: str) -> bool:
    try:
        proc = subprocess.run(
            [docker, "scout", "version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except Exception:
        return False
    return proc.returncode == 0


def _version(command: list[str]) -> str:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except Exception:
        return "unknown"
    return (proc.stdout or proc.stderr or "unknown").strip().splitlines()[0][:160]


def _detected_version(command: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or proc.stderr or "unknown").strip().splitlines()[0][:160]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan a quarantined ProgramBench cleanroom image artifact."
    )
    parser.add_argument("import_record", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_image_scans"),
    )
    args = parser.parse_args()
    result = ProgramBenchCleanroomImageScan(
        CleanroomImageScanConfig(root=args.root, output_dir=args.output_dir)
    ).scan(args.import_record)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
