#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_image_hydration_record import (
    make_cleanroom_image_hydration_record,
    write_cleanroom_image_hydration_record,
)
from corpus.programbench.operator_artifact_admission import OperatorArtifactAdmissionStatus
from corpus.programbench.operator_artifact_admission_record import (
    verify_operator_artifact_admission_record,
)


class CleanroomImageHydrationStatus(str, Enum):
    CLEANROOM_IMAGE_HYDRATION_READY = "CLEANROOM_IMAGE_HYDRATION_READY"
    CLEANROOM_IMAGE_HYDRATED_TO_QUARANTINE = "CLEANROOM_IMAGE_HYDRATED_TO_QUARANTINE"
    CLEANROOM_IMAGE_DIGEST_VERIFIED = "CLEANROOM_IMAGE_DIGEST_VERIFIED"
    CLEANROOM_IMAGE_DIGEST_MISMATCH = "CLEANROOM_IMAGE_DIGEST_MISMATCH"
    CLEANROOM_IMAGE_SCAN_PASSED = "CLEANROOM_IMAGE_SCAN_PASSED"
    CLEANROOM_IMAGE_SCAN_FAILED = "CLEANROOM_IMAGE_SCAN_FAILED"
    CLEANROOM_IMAGE_POLICY_ADMITTED = "CLEANROOM_IMAGE_POLICY_ADMITTED"
    CLEANROOM_IMAGE_POLICY_BLOCKED = "CLEANROOM_IMAGE_POLICY_BLOCKED"
    CLEANROOM_IMAGE_CACHE_READY = "CLEANROOM_IMAGE_CACHE_READY"
    CLEANROOM_IMAGE_NOT_EXECUTABLE = "CLEANROOM_IMAGE_NOT_EXECUTABLE"
    CLEANROOM_IMAGE_BLOCKED_FIXTURE_ADMISSION = "CLEANROOM_IMAGE_BLOCKED_FIXTURE_ADMISSION"
    CLEANROOM_IMAGE_BLOCKED_NO_REAL_ADMISSION = "CLEANROOM_IMAGE_BLOCKED_NO_REAL_ADMISSION"
    CLEANROOM_IMAGE_BLOCKED_NON_CANDIDATE = "CLEANROOM_IMAGE_BLOCKED_NON_CANDIDATE"
    CLEANROOM_IMAGE_BLOCKED_ALREADY_EXECUTABLE = "CLEANROOM_IMAGE_BLOCKED_ALREADY_EXECUTABLE"
    CLEANROOM_IMAGE_BLOCKED_TRAINING_ELIGIBLE = "CLEANROOM_IMAGE_BLOCKED_TRAINING_ELIGIBLE"
    CLEANROOM_IMAGE_BLOCKED_NO_DIGEST = "CLEANROOM_IMAGE_BLOCKED_NO_DIGEST"
    CLEANROOM_IMAGE_BLOCKED_NO_PROVENANCE = "CLEANROOM_IMAGE_BLOCKED_NO_PROVENANCE"
    CLEANROOM_IMAGE_BLOCKED_NO_ARTIFACT = "CLEANROOM_IMAGE_BLOCKED_NO_ARTIFACT"


@dataclass(slots=True)
class CleanroomImageHydrationConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_cleanroom_image_hydration")
    quarantine_dir: Path = Path("T:/determinex_artifacts/quarantine/programbench")
    cache_dir: Path = Path("T:/determinex_artifacts/cache/programbench")


class ProgramBenchCleanroomImageHydration:
    def __init__(self, config: CleanroomImageHydrationConfig | None = None) -> None:
        self.config = config or CleanroomImageHydrationConfig()

    def hydrate(
        self,
        admission_record_path: Path,
        *,
        artifact_path: Path | None = None,
        observed_digest: str = "",
        scan_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        admission_path = self._resolve(admission_record_path)
        if not admission_path.is_file():
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_REAL_ADMISSION.value,
                admission_path,
                {},
                "",
                scan_result or {},
                ["admission_record_missing"],
            )
        admission = _read_json(admission_path)
        if not verify_operator_artifact_admission_record(admission):
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_REAL_ADMISSION.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["admission_record_signature_invalid"],
            )
        if _is_fixture_admission(admission):
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_FIXTURE_ADMISSION.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["fixture_admission_cannot_hydrate"],
            )
        if (
            str(admission.get("status") or "")
            != OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_ADMISSION_ACCEPTED.value
        ):
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_REAL_ADMISSION.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["admission_not_accepted"],
            )
        if not bool(admission.get("hydration_candidate")):
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NON_CANDIDATE.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["admission_not_hydration_candidate"],
            )
        if bool(admission.get("executable")):
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_ALREADY_EXECUTABLE.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["admission_must_not_be_executable_before_hydration"],
            )
        if bool(admission.get("training_eligible")):
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_TRAINING_ELIGIBLE.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["admission_must_not_be_training_eligible"],
            )

        claim = (
            admission.get("operator_claim")
            if isinstance(admission.get("operator_claim"), dict)
            else {}
        )
        expected_digest = str(claim.get("digest") or claim.get("immutable_revision") or "")
        if not expected_digest.startswith("sha256:"):
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_DIGEST.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["sha256_digest_required"],
            )
        if not str(
            claim.get("license_provenance_notes") or claim.get("provenance_notes") or ""
        ).strip():
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_PROVENANCE.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["provenance_notes_required"],
            )
        if artifact_path is None:
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_ARTIFACT.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["artifact_import_path_required_for_hydration"],
            )

        artifact = self._resolve(artifact_path)
        if not artifact.is_file():
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_ARTIFACT.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["artifact_import_path_missing"],
            )
        if observed_digest != expected_digest:
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_DIGEST_MISMATCH.value,
                admission_path,
                admission,
                observed_digest,
                scan_result or {},
                ["observed_digest_does_not_match_admitted_digest"],
            )

        scan = scan_result or {}
        if not _scan_passes(scan):
            return self._blocked(
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_SCAN_FAILED.value,
                admission_path,
                admission,
                observed_digest,
                scan,
                ["security_scan_policy_failed"],
            )

        quarantine = self._copy_artifact(
            artifact, self._resolve(self.config.quarantine_dir), expected_digest
        )
        cache = self._copy_artifact(
            quarantine, self._resolve(self.config.cache_dir), expected_digest
        )
        record = make_cleanroom_image_hydration_record(
            status=CleanroomImageHydrationStatus.CLEANROOM_IMAGE_CACHE_READY.value,
            admission_record=_rel(self.config.root, admission_path),
            image_reference=str(admission.get("image_reference") or ""),
            source_url_or_registry=str(claim.get("source_url_or_registry") or ""),
            expected_digest=expected_digest,
            observed_digest=observed_digest,
            target=dict(admission.get("target") or {}),
            hydration_statuses=[
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_HYDRATION_READY.value,
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_HYDRATED_TO_QUARANTINE.value,
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_DIGEST_VERIFIED.value,
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_SCAN_PASSED.value,
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_POLICY_ADMITTED.value,
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_CACHE_READY.value,
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value,
            ],
            quarantine_path=_rel(self.config.root, quarantine),
            cache_path=_rel(self.config.root, cache),
            scan_result=_compact_scan(scan),
            policy_result=CleanroomImageHydrationStatus.CLEANROOM_IMAGE_POLICY_ADMITTED.value,
            cache_ready=True,
            executable=False,
        )
        path = write_cleanroom_image_hydration_record(record, self._resolve(self.config.output_dir))
        return {"record_path": str(path), "record": record}

    def _blocked(
        self,
        status: str,
        admission_path: Path,
        admission: dict[str, Any],
        observed_digest: str,
        scan_result: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        claim = (
            admission.get("operator_claim")
            if isinstance(admission.get("operator_claim"), dict)
            else {}
        )
        record = make_cleanroom_image_hydration_record(
            status=status,
            admission_record=_rel(self.config.root, admission_path),
            image_reference=str(
                admission.get("image_reference") or claim.get("image_reference") or ""
            ),
            source_url_or_registry=str(claim.get("source_url_or_registry") or ""),
            expected_digest=str(claim.get("digest") or claim.get("immutable_revision") or ""),
            observed_digest=observed_digest,
            target=dict(admission.get("target") or {}),
            hydration_statuses=[
                status,
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_POLICY_BLOCKED.value,
                CleanroomImageHydrationStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value,
            ],
            scan_result=_compact_scan(scan_result),
            policy_result=CleanroomImageHydrationStatus.CLEANROOM_IMAGE_POLICY_BLOCKED.value,
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_image_hydration_record(record, self._resolve(self.config.output_dir))
        return {"record_path": str(path), "record": record}

    def _copy_artifact(self, source: Path, target_dir: Path, digest: str) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{_safe(digest)}{source.suffix or '.artifact'}"
        shutil.copy2(source, target)
        return target

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _scan_passes(scan: dict[str, Any]) -> bool:
    if not scan:
        return False
    status = str(scan.get("status") or "")
    explicit_policy = str(scan.get("policy") or "").lower()
    if explicit_policy and explicit_policy != "pass":
        return False
    if not explicit_policy and status != "CLEANROOM_IMAGE_SCAN_PASSED":
        return False
    summary = scan.get("findings_summary") if isinstance(scan.get("findings_summary"), dict) else {}
    critical = int(scan.get("critical") or summary.get("critical") or 0)
    high = int(scan.get("high") or summary.get("high") or 0)
    return critical == 0 and high == 0


def _compact_scan(scan: dict[str, Any]) -> dict[str, Any]:
    allowed = ("scanner", "policy", "critical", "high", "medium", "low", "artifact")
    compact = {key: scan.get(key) for key in allowed if key in scan}
    summary = scan.get("findings_summary") if isinstance(scan.get("findings_summary"), dict) else {}
    for key in ("critical", "high", "medium", "low", "total", "unknown"):
        if key not in compact and key in summary:
            compact[key] = summary.get(key)
    if "artifact" not in compact and scan.get("artifact_path"):
        compact["artifact"] = scan.get("artifact_path")
    if "policy" not in compact and scan.get("status"):
        compact["policy"] = (
            "pass" if scan.get("status") == "CLEANROOM_IMAGE_SCAN_PASSED" else "block"
        )
    return compact


def _is_fixture_admission(record: dict[str, Any]) -> bool:
    claim = record.get("operator_claim") if isinstance(record.get("operator_claim"), dict) else {}
    operator_id = str(claim.get("operator_id") or "")
    source = str(claim.get("source_url_or_registry") or "")
    reason = str(claim.get("admission_reason") or "").lower()
    notes = str(claim.get("license_provenance_notes") or "").lower()
    return (
        operator_id == "lock_fixture"
        or source.startswith("fixture://")
        or "fixture" in reason
        or "fixture" in notes
    )


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:160]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hydrate an admitted ProgramBench cleanroom image into quarantine/cache."
    )
    parser.add_argument("admission_record", type=Path)
    parser.add_argument("--artifact-path", type=Path)
    parser.add_argument("--observed-digest", default="")
    parser.add_argument("--scan-result", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_image_hydration"),
    )
    parser.add_argument(
        "--quarantine-dir",
        type=Path,
        default=Path("T:/determinex_artifacts/quarantine/programbench"),
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path("T:/determinex_artifacts/cache/programbench")
    )
    args = parser.parse_args()
    scan = _read_json(args.scan_result) if args.scan_result else {}
    result = ProgramBenchCleanroomImageHydration(
        CleanroomImageHydrationConfig(
            root=args.root,
            output_dir=args.output_dir,
            quarantine_dir=args.quarantine_dir,
            cache_dir=args.cache_dir,
        )
    ).hydrate(
        args.admission_record,
        artifact_path=args.artifact_path,
        observed_digest=args.observed_digest,
        scan_result=scan,
    )
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
