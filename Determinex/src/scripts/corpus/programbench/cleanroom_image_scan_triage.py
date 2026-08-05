#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_image_hydration_record import (
    verify_cleanroom_image_hydration_record,
)
from corpus.programbench.cleanroom_image_scan_record import verify_cleanroom_image_scan_record
from corpus.programbench.cleanroom_image_scan_triage_record import (
    make_cleanroom_image_scan_triage_record,
    write_cleanroom_image_scan_triage_record,
)

EXPECTED_IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
EXPECTED_DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


class CleanroomImageScanTriageStatus(str, Enum):
    CLEANROOM_IMAGE_SCAN_TRIAGED = "CLEANROOM_IMAGE_SCAN_TRIAGED"
    CLEANROOM_IMAGE_REMEDIATE_REQUIRED = "CLEANROOM_IMAGE_REMEDIATE_REQUIRED"
    CLEANROOM_IMAGE_ALTERNATE_SOURCE_REQUIRED = "CLEANROOM_IMAGE_ALTERNATE_SOURCE_REQUIRED"
    CLEANROOM_IMAGE_POLICY_EXCEPTION_REVIEW_REQUIRED = (
        "CLEANROOM_IMAGE_POLICY_EXCEPTION_REVIEW_REQUIRED"
    )
    CLEANROOM_IMAGE_SCAN_DATA_INSUFFICIENT = "CLEANROOM_IMAGE_SCAN_DATA_INSUFFICIENT"
    CLEANROOM_IMAGE_CRITICALS_WITH_FIXES = "CLEANROOM_IMAGE_CRITICALS_WITH_FIXES"
    CLEANROOM_IMAGE_CRITICALS_WITHOUT_FIXES = "CLEANROOM_IMAGE_CRITICALS_WITHOUT_FIXES"
    CLEANROOM_IMAGE_OS_VULNERABILITY_DOMINANT = "CLEANROOM_IMAGE_OS_VULNERABILITY_DOMINANT"
    CLEANROOM_IMAGE_APP_VULNERABILITY_DOMINANT = "CLEANROOM_IMAGE_APP_VULNERABILITY_DOMINANT"
    CLEANROOM_IMAGE_POLICY_STILL_BLOCKED = "CLEANROOM_IMAGE_POLICY_STILL_BLOCKED"
    CLEANROOM_IMAGE_NOT_EXECUTABLE = "CLEANROOM_IMAGE_NOT_EXECUTABLE"
    CLEANROOM_IMAGE_TRAINING_INELIGIBLE = "CLEANROOM_IMAGE_TRAINING_INELIGIBLE"
    CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_SCAN = "CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_SCAN"
    CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_HYDRATION = (
        "CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_HYDRATION"
    )
    CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_DIGEST_MISMATCH = (
        "CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_DIGEST_MISMATCH"
    )


@dataclass(slots=True)
class CleanroomImageScanTriageConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_cleanroom_image_scan_triage")
    expected_image: str = EXPECTED_IMAGE
    expected_digest: str = EXPECTED_DIGEST


class ProgramBenchCleanroomImageScanTriage:
    def __init__(self, config: CleanroomImageScanTriageConfig | None = None) -> None:
        self.config = config or CleanroomImageScanTriageConfig()

    def triage(self, scan_record_path: Path, hydration_record_path: Path) -> dict[str, Any]:
        scan_path = self._resolve(scan_record_path)
        hydration_path = self._resolve(hydration_record_path)
        if not scan_path.is_file():
            return self._blocked(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_SCAN.value,
                scan_path,
                hydration_path,
                {},
                {},
                ["scan_evidence_missing"],
            )
        if not hydration_path.is_file():
            return self._blocked(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_HYDRATION.value,
                scan_path,
                hydration_path,
                _read_json(scan_path),
                {},
                ["hydration_policy_block_evidence_missing"],
            )

        scan = _read_json(scan_path)
        hydration = _read_json(hydration_path)
        if not verify_cleanroom_image_scan_record(scan):
            return self._blocked(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_SCAN.value,
                scan_path,
                hydration_path,
                scan,
                hydration,
                ["scan_evidence_signature_invalid"],
            )
        if not verify_cleanroom_image_hydration_record(hydration):
            return self._blocked(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_NO_HYDRATION.value,
                scan_path,
                hydration_path,
                scan,
                hydration,
                ["hydration_evidence_signature_invalid"],
            )
        digest_reasons = self._digest_reasons(scan, hydration)
        if digest_reasons:
            return self._blocked(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGE_BLOCKED_DIGEST_MISMATCH.value,
                scan_path,
                hydration_path,
                scan,
                hydration,
                digest_reasons,
            )
        findings = [item for item in scan.get("normalized_findings", []) if isinstance(item, dict)]
        if not findings and str(scan.get("status") or "") != "CLEANROOM_IMAGE_SCAN_PASSED":
            return self._write(
                status=CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_DATA_INSUFFICIENT.value,
                recommendation="SCAN_DATA_INSUFFICIENT",
                scan_path=scan_path,
                hydration_path=hydration_path,
                scan=scan,
                severity_counts=_severity_counts(findings),
                fixed_summary=_fixed_summary(findings),
                category_summary=_category_summary(findings),
                grouped=[],
                top_critical=[],
                top_high=[],
                statuses=[
                    CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_DATA_INSUFFICIENT.value,
                    CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_POLICY_STILL_BLOCKED.value,
                ],
                reasons=["failed_scan_without_normalized_findings"],
            )

        severity_counts = _severity_counts(findings)
        grouped = _group_findings(findings)
        fixed_summary = _fixed_summary(findings)
        category_summary = _category_summary(findings)
        critical_high = severity_counts.get("critical", 0) + severity_counts.get("high", 0)
        statuses = [
            CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGED.value,
            CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_POLICY_STILL_BLOCKED.value,
        ]
        if fixed_summary.get("critical_with_fix", 0) > 0:
            statuses.append(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_CRITICALS_WITH_FIXES.value
            )
        if fixed_summary.get("critical_without_fix", 0) > 0:
            statuses.append(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_CRITICALS_WITHOUT_FIXES.value
            )
        dominant = str(category_summary.get("dominant_category") or "")
        if dominant == "os_base":
            statuses.append(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_OS_VULNERABILITY_DOMINANT.value
            )
        else:
            statuses.append(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_APP_VULNERABILITY_DOMINANT.value
            )
        recommendation = "SCAN_DATA_INSUFFICIENT"
        if critical_high > 0 and fixed_summary.get("critical_high_with_fix", 0) > 0:
            recommendation = "REMEDIATE_IMAGE_REQUIRED"
            statuses.append(CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_REMEDIATE_REQUIRED.value)
        elif critical_high > 0:
            recommendation = "ALTERNATE_PROVENANCE_IMAGE_REQUIRED"
            statuses.append(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_ALTERNATE_SOURCE_REQUIRED.value
            )
        elif severity_counts.get("medium", 0) or severity_counts.get("low", 0):
            recommendation = "POLICY_EXCEPTION_REVIEW_REQUIRED"
            statuses.append(
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_POLICY_EXCEPTION_REVIEW_REQUIRED.value
            )
        top_critical = _top_groups(grouped, "critical", limit=10)
        top_high = _top_groups(grouped, "high", limit=10)
        return self._write(
            status=CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_SCAN_TRIAGED.value,
            recommendation=recommendation,
            scan_path=scan_path,
            hydration_path=hydration_path,
            scan=scan,
            severity_counts=severity_counts,
            fixed_summary=fixed_summary,
            category_summary=category_summary,
            grouped=grouped[:100],
            top_critical=top_critical,
            top_high=top_high,
            statuses=statuses,
            reasons=["scan_policy_failed", "vulnerabilities_not_suppressed"],
        )

    def _digest_reasons(self, scan: dict[str, Any], hydration: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if str(scan.get("image_reference") or "") != self.config.expected_image:
            reasons.append("scan_image_reference_mismatch")
        if str(hydration.get("image_reference") or "") != self.config.expected_image:
            reasons.append("hydration_image_reference_mismatch")
        if str(scan.get("expected_digest") or "") != self.config.expected_digest:
            reasons.append("scan_expected_digest_mismatch")
        if str(scan.get("observed_digest") or "") != self.config.expected_digest:
            reasons.append("scan_observed_digest_mismatch")
        if str(hydration.get("expected_digest") or "") != self.config.expected_digest:
            reasons.append("hydration_expected_digest_mismatch")
        if str(hydration.get("observed_digest") or "") != self.config.expected_digest:
            reasons.append("hydration_observed_digest_mismatch")
        return reasons

    def _blocked(
        self,
        status: str,
        scan_path: Path,
        hydration_path: Path,
        scan: dict[str, Any],
        hydration: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        return self._write(
            status=status,
            recommendation="SCAN_DATA_INSUFFICIENT",
            scan_path=scan_path,
            hydration_path=hydration_path,
            scan=scan,
            severity_counts={},
            fixed_summary={},
            category_summary={},
            grouped=[],
            top_critical=[],
            top_high=[],
            statuses=[
                status,
                CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_POLICY_STILL_BLOCKED.value,
            ],
            reasons=reasons,
        )

    def _write(
        self,
        *,
        status: str,
        recommendation: str,
        scan_path: Path,
        hydration_path: Path,
        scan: dict[str, Any],
        severity_counts: dict[str, int],
        fixed_summary: dict[str, Any],
        category_summary: dict[str, Any],
        grouped: list[dict[str, Any]],
        top_critical: list[dict[str, Any]],
        top_high: list[dict[str, Any]],
        statuses: list[str],
        reasons: list[str],
    ) -> dict[str, Any]:
        statuses = [
            *statuses,
            CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value,
            CleanroomImageScanTriageStatus.CLEANROOM_IMAGE_TRAINING_INELIGIBLE.value,
        ]
        record = make_cleanroom_image_scan_triage_record(
            status=status,
            recommendation=recommendation,
            image_reference=str(scan.get("image_reference") or self.config.expected_image),
            artifact_path=str(scan.get("artifact_path") or ""),
            expected_digest=str(scan.get("expected_digest") or ""),
            observed_digest=str(scan.get("observed_digest") or ""),
            file_sha256=str(scan.get("file_sha256") or ""),
            scan_record=_rel(self.config.root, scan_path),
            hydration_record=_rel(self.config.root, hydration_path),
            severity_counts=severity_counts,
            fixed_version_summary=fixed_summary,
            category_summary=category_summary,
            top_critical=top_critical,
            top_high=top_high,
            grouped_findings=grouped,
            triage_statuses=list(dict.fromkeys(statuses)),
            reasons=reasons,
            policy_blocked=True,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_image_scan_triage_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _severity_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0, "total": len(findings)}
    for finding in findings:
        severity = str(finding.get("severity") or "unknown").lower()
        if severity not in counts:
            severity = "unknown"
        counts[severity] += 1
    return counts


def _fixed_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "critical_with_fix": 0,
        "critical_without_fix": 0,
        "high_with_fix": 0,
        "high_without_fix": 0,
        "critical_high_with_fix": 0,
        "critical_high_without_fix": 0,
        "no_fixed_version_total": 0,
    }
    for finding in findings:
        severity = str(finding.get("severity") or "").lower()
        has_fix = bool(str(finding.get("fixed_version") or "").strip())
        if not has_fix:
            out["no_fixed_version_total"] += 1
        if severity in {"critical", "high"}:
            out[f"{severity}_{'with_fix' if has_fix else 'without_fix'}"] += 1
            out[f"critical_high_{'with_fix' if has_fix else 'without_fix'}"] += 1
    return out


def _category_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    critical_high: Counter[str] = Counter()
    for finding in findings:
        category = _category_for(finding)
        counts[category] += 1
        if str(finding.get("severity") or "").lower() in {"critical", "high"}:
            critical_high[category] += 1
    dominant = "unknown"
    if critical_high:
        dominant = sorted(critical_high.items(), key=lambda item: (-item[1], item[0]))[0][0]
    elif counts:
        dominant = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "all_findings": dict(sorted(counts.items())),
        "critical_high": dict(sorted(critical_high.items())),
        "dominant_category": dominant,
    }


def _category_for(finding: dict[str, Any]) -> str:
    target = str(finding.get("target") or "").lower()
    package = str(finding.get("package") or "").lower()
    if "(ubuntu" in target or target.endswith(".tar (ubuntu 22.04)") or package in _OS_PACKAGES:
        return "os_base"
    if target.startswith("usr/local/go") or package in {"stdlib", "go", "golang"}:
        return "language_runtime"
    if "site-packages" in target or "node_modules" in target or "cargo/registry" in target:
        return "application_dependency"
    return "application_or_unknown"


_OS_PACKAGES = {
    "apt",
    "bash",
    "binutils",
    "coreutils",
    "curl",
    "dpkg",
    "gcc",
    "git",
    "glibc",
    "gnupg",
    "libc6",
    "linux-libc-dev",
    "openssl",
    "perl",
    "python3",
    "tar",
    "ubuntu-keyring",
    "zlib1g",
}


def _group_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    targets: defaultdict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    for finding in findings:
        severity = str(finding.get("severity") or "unknown").lower()
        key = (
            severity,
            str(finding.get("package") or ""),
            str(finding.get("installed_version") or ""),
            str(finding.get("fixed_version") or ""),
            str(finding.get("id") or ""),
        )
        if key not in grouped:
            grouped[key] = {
                "severity": severity,
                "package": key[1],
                "installed_version": key[2],
                "fixed_version": key[3],
                "id": key[4],
                "category": _category_for(finding),
                "count": 0,
                "sample_targets": [],
                "has_fix": bool(key[3].strip()),
            }
        grouped[key]["count"] += 1
        targets[key].add(str(finding.get("target") or ""))
    for key, item in grouped.items():
        item["sample_targets"] = sorted(targets[key])[:5]
    return sorted(
        grouped.values(),
        key=lambda item: (
            _severity_rank(str(item["severity"])),
            -int(item["count"]),
            str(item["package"]),
            str(item["id"]),
        ),
    )


def _top_groups(groups: list[dict[str, Any]], severity: str, *, limit: int) -> list[dict[str, Any]]:
    return [group for group in groups if group.get("severity") == severity][:limit]


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}.get(severity, 5)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Triage ProgramBench cleanroom image scan findings."
    )
    parser.add_argument("scan_record", type=Path)
    parser.add_argument("hydration_record", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_image_scan_triage"),
    )
    args = parser.parse_args()
    result = ProgramBenchCleanroomImageScanTriage(
        CleanroomImageScanTriageConfig(root=args.root, output_dir=args.output_dir)
    ).triage(args.scan_record, args.hydration_record)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
