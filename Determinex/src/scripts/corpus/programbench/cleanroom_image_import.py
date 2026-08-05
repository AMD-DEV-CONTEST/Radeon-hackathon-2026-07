#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_image_import_record import (
    make_cleanroom_image_import_record,
    write_cleanroom_image_import_record,
)
from corpus.programbench.dockerhub_manifest_provenance_record import (
    verify_dockerhub_manifest_provenance_record,
)
from corpus.programbench.operator_artifact_admission import OperatorArtifactAdmissionStatus
from corpus.programbench.operator_artifact_admission_record import (
    verify_operator_artifact_admission_record,
)


class CleanroomImageImportStatus(str, Enum):
    CLEANROOM_IMAGE_IMPORT_READY = "CLEANROOM_IMAGE_IMPORT_READY"
    CLEANROOM_IMAGE_IMPORTED_TO_QUARANTINE = "CLEANROOM_IMAGE_IMPORTED_TO_QUARANTINE"
    CLEANROOM_IMAGE_IMPORT_DIGEST_VERIFIED = "CLEANROOM_IMAGE_IMPORT_DIGEST_VERIFIED"
    CLEANROOM_IMAGE_IMPORT_DIGEST_MISMATCH = "CLEANROOM_IMAGE_IMPORT_DIGEST_MISMATCH"
    CLEANROOM_IMAGE_IMPORT_SCAN_PASSED = "CLEANROOM_IMAGE_IMPORT_SCAN_PASSED"
    CLEANROOM_IMAGE_IMPORT_SCAN_FAILED = "CLEANROOM_IMAGE_IMPORT_SCAN_FAILED"
    CLEANROOM_IMAGE_IMPORT_SCAN_UNAVAILABLE = "CLEANROOM_IMAGE_IMPORT_SCAN_UNAVAILABLE"
    CLEANROOM_IMAGE_IMPORT_POLICY_ADMITTED = "CLEANROOM_IMAGE_IMPORT_POLICY_ADMITTED"
    CLEANROOM_IMAGE_IMPORT_POLICY_BLOCKED = "CLEANROOM_IMAGE_IMPORT_POLICY_BLOCKED"
    CLEANROOM_IMAGE_IMPORT_NOT_EXECUTABLE = "CLEANROOM_IMAGE_IMPORT_NOT_EXECUTABLE"
    CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_PROVENANCE = "CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_PROVENANCE"
    CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ADMISSION = "CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ADMISSION"
    CLEANROOM_IMAGE_IMPORT_BLOCKED_FIXTURE_ADMISSION = (
        "CLEANROOM_IMAGE_IMPORT_BLOCKED_FIXTURE_ADMISSION"
    )
    CLEANROOM_IMAGE_IMPORT_BLOCKED_IMAGE_MISMATCH = "CLEANROOM_IMAGE_IMPORT_BLOCKED_IMAGE_MISMATCH"
    CLEANROOM_IMAGE_IMPORT_BLOCKED_DIGEST_MISMATCH = (
        "CLEANROOM_IMAGE_IMPORT_BLOCKED_DIGEST_MISMATCH"
    )
    CLEANROOM_IMAGE_IMPORT_BLOCKED_UNPINNED = "CLEANROOM_IMAGE_IMPORT_BLOCKED_UNPINNED"
    CLEANROOM_IMAGE_IMPORT_BLOCKED_PULL_DISABLED = "CLEANROOM_IMAGE_IMPORT_BLOCKED_PULL_DISABLED"
    CLEANROOM_IMAGE_IMPORT_PULL_FAILED = "CLEANROOM_IMAGE_IMPORT_PULL_FAILED"
    CLEANROOM_IMAGE_IMPORT_SAVE_FAILED = "CLEANROOM_IMAGE_IMPORT_SAVE_FAILED"
    CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ARTIFACT = "CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ARTIFACT"
    TRAINING_INELIGIBLE = "TRAINING_INELIGIBLE"


@dataclass(slots=True)
class CleanroomImageImportConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_cleanroom_image_import")
    quarantine_dir: Path = Path("T:/determinex_artifacts/quarantine/programbench")


class ProgramBenchCleanroomImageImport:
    def __init__(self, config: CleanroomImageImportConfig | None = None) -> None:
        self.config = config or CleanroomImageImportConfig()

    def import_image(
        self,
        provenance_record_path: Path,
        admission_record_path: Path,
        *,
        artifact_path: Path | None = None,
        observed_digest: str = "",
        scan_result: dict[str, Any] | None = None,
        live_docker_pull: bool = False,
    ) -> dict[str, Any]:
        provenance_path = self._resolve(provenance_record_path)
        admission_path = self._resolve(admission_record_path)
        provenance = self._load_provenance(provenance_path)
        if not provenance:
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_PROVENANCE.value,
                provenance_path,
                admission_path,
                {},
                {},
                observed_digest,
                scan_result or {},
                ["provenance_record_missing_or_invalid"],
            )
        admission = self._load_admission(admission_path)
        if not admission:
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ADMISSION.value,
                provenance_path,
                admission_path,
                provenance,
                {},
                observed_digest,
                scan_result or {},
                ["admission_record_missing_or_invalid"],
            )
        admission_block = _validate_admission(admission)
        if admission_block:
            return self._blocked(
                admission_block[0],
                provenance_path,
                admission_path,
                provenance,
                admission,
                observed_digest,
                scan_result or {},
                [admission_block[1]],
            )

        expected_digest = str(provenance.get("manifest_digest") or "")
        claim = (
            admission.get("operator_claim")
            if isinstance(admission.get("operator_claim"), dict)
            else {}
        )
        admitted_digest = str(claim.get("digest") or "")
        image = str(provenance.get("image_reference") or "")
        if image != str(admission.get("image_reference") or ""):
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_IMAGE_MISMATCH.value,
                provenance_path,
                admission_path,
                provenance,
                admission,
                observed_digest,
                scan_result or {},
                ["admission_image_does_not_match_provenance_image"],
            )
        if not expected_digest.startswith("sha256:") or admitted_digest != expected_digest:
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_DIGEST_MISMATCH.value,
                provenance_path,
                admission_path,
                provenance,
                admission,
                observed_digest,
                scan_result or {},
                ["admission_digest_does_not_match_provenance_digest"],
            )
        if str(provenance.get("tag") or "").lower() == "latest":
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_UNPINNED.value,
                provenance_path,
                admission_path,
                provenance,
                admission,
                observed_digest,
                scan_result or {},
                ["floating_latest_tag_blocked"],
            )

        pull_command = ["docker", "pull", _pinned_ref(provenance)]
        save_command: list[str] = []
        import_source = self._resolve(artifact_path) if artifact_path else None
        pulled_layers = False
        if import_source is None:
            if not live_docker_pull:
                return self._blocked(
                    CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_PULL_DISABLED.value,
                    provenance_path,
                    admission_path,
                    provenance,
                    admission,
                    observed_digest,
                    scan_result or {},
                    ["live_docker_pull_disabled_and_no_artifact_path_supplied"],
                    pull_command=pull_command,
                )
            pull = _run(pull_command, cwd=self.config.root)
            if pull.returncode != 0:
                return self._blocked(
                    CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_PULL_FAILED.value,
                    provenance_path,
                    admission_path,
                    provenance,
                    admission,
                    observed_digest,
                    scan_result or {},
                    [f"docker_pull_failed:{pull.stderr[-500:]}"],
                    pull_command=pull_command,
                )
            pulled_layers = True
            quarantine_root = self._resolve(self.config.quarantine_dir)
            quarantine_root.mkdir(parents=True, exist_ok=True)
            import_source = quarantine_root / f"{_safe(expected_digest)}.tar"
            save_command = ["docker", "save", "-o", str(import_source), _pinned_ref(provenance)]
            save = _run(save_command, cwd=self.config.root)
            if save.returncode != 0:
                return self._blocked(
                    CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_SAVE_FAILED.value,
                    provenance_path,
                    admission_path,
                    provenance,
                    admission,
                    observed_digest,
                    scan_result or {},
                    [f"docker_save_failed:{save.stderr[-500:]}"],
                    pull_command=pull_command,
                    save_command=save_command,
                    pulled_layers=pulled_layers,
                )
            observed_digest = expected_digest

        if not import_source.is_file():
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ARTIFACT.value,
                provenance_path,
                admission_path,
                provenance,
                admission,
                observed_digest,
                scan_result or {},
                ["artifact_import_path_missing"],
                pull_command=pull_command,
                save_command=save_command,
                pulled_layers=pulled_layers,
            )
        if observed_digest != expected_digest:
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_DIGEST_MISMATCH.value,
                provenance_path,
                admission_path,
                provenance,
                admission,
                observed_digest,
                scan_result or {},
                ["observed_digest_does_not_match_manifest_digest"],
                pull_command=pull_command,
                save_command=save_command,
                pulled_layers=pulled_layers,
            )
        scan = scan_result or {}
        if not scan:
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_SCAN_UNAVAILABLE.value,
                provenance_path,
                admission_path,
                provenance,
                admission,
                observed_digest,
                scan,
                ["scan_result_required_before_import_policy_admission"],
                pull_command=pull_command,
                save_command=save_command,
                pulled_layers=pulled_layers,
                artifact_import_path=import_source,
            )
        if not _scan_passes(scan):
            return self._blocked(
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_SCAN_FAILED.value,
                provenance_path,
                admission_path,
                provenance,
                admission,
                observed_digest,
                scan,
                ["scan_result_policy_failed"],
                pull_command=pull_command,
                save_command=save_command,
                pulled_layers=pulled_layers,
                artifact_import_path=import_source,
            )

        quarantine = self._copy_to_quarantine(import_source, expected_digest)
        record = make_cleanroom_image_import_record(
            status=CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORTED_TO_QUARANTINE.value,
            provenance_record=_rel(self.config.root, provenance_path),
            admission_record=_rel(self.config.root, admission_path),
            image_reference=image,
            source_url_or_registry=str(claim.get("source_url_or_registry") or ""),
            expected_digest=expected_digest,
            observed_digest=observed_digest,
            target=dict(provenance.get("target") or {}),
            import_statuses=[
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_READY.value,
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORTED_TO_QUARANTINE.value,
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_DIGEST_VERIFIED.value,
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_SCAN_PASSED.value,
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_POLICY_ADMITTED.value,
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_NOT_EXECUTABLE.value,
                CleanroomImageImportStatus.TRAINING_INELIGIBLE.value,
            ],
            artifact_import_path=_rel(self.config.root, quarantine),
            quarantine_path=_rel(self.config.root, quarantine),
            scan_result=_compact_scan(scan),
            policy_result=CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_POLICY_ADMITTED.value,
            pull_command=pull_command,
            save_command=save_command,
            pulled_layers=pulled_layers,
            docker_executed=False,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_image_import_record(record, self._resolve(self.config.output_dir))
        return {"record_path": str(path), "record": record}

    def _blocked(
        self,
        status: str,
        provenance_path: Path,
        admission_path: Path,
        provenance: dict[str, Any],
        admission: dict[str, Any],
        observed_digest: str,
        scan_result: dict[str, Any],
        reasons: list[str],
        *,
        pull_command: list[str] | None = None,
        save_command: list[str] | None = None,
        pulled_layers: bool = False,
        artifact_import_path: Path | None = None,
    ) -> dict[str, Any]:
        claim = (
            admission.get("operator_claim")
            if isinstance(admission.get("operator_claim"), dict)
            else {}
        )
        record = make_cleanroom_image_import_record(
            status=status,
            provenance_record=_rel(self.config.root, provenance_path),
            admission_record=_rel(self.config.root, admission_path),
            image_reference=str(
                provenance.get("image_reference") or admission.get("image_reference") or ""
            ),
            source_url_or_registry=str(claim.get("source_url_or_registry") or ""),
            expected_digest=str(provenance.get("manifest_digest") or claim.get("digest") or ""),
            observed_digest=observed_digest,
            target=dict(provenance.get("target") or admission.get("target") or {}),
            import_statuses=[
                status,
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_POLICY_BLOCKED.value,
                CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_NOT_EXECUTABLE.value,
                CleanroomImageImportStatus.TRAINING_INELIGIBLE.value,
            ],
            artifact_import_path=_rel(self.config.root, artifact_import_path)
            if artifact_import_path
            else "",
            quarantine_path=_rel(self.config.root, artifact_import_path)
            if artifact_import_path
            else "",
            scan_result=_compact_scan(scan_result),
            policy_result=CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_POLICY_BLOCKED.value,
            pull_command=pull_command or [],
            save_command=save_command or [],
            reasons=reasons,
            pulled_layers=pulled_layers,
            docker_executed=False,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_image_import_record(record, self._resolve(self.config.output_dir))
        return {"record_path": str(path), "record": record}

    def _load_provenance(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        data = _read_json(path)
        if not verify_dockerhub_manifest_provenance_record(data):
            return {}
        return data

    def _load_admission(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        data = _read_json(path)
        if not verify_operator_artifact_admission_record(data):
            return {}
        return data

    def _copy_to_quarantine(self, source: Path, digest: str) -> Path:
        target_dir = self._resolve(self.config.quarantine_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{_safe(digest)}{source.suffix or '.artifact'}"
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _validate_admission(admission: dict[str, Any]) -> tuple[str, str] | None:
    if _is_fixture_admission(admission):
        return (
            CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_FIXTURE_ADMISSION.value,
            "fixture_admission_cannot_import",
        )
    if (
        str(admission.get("status") or "")
        != OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_ADMISSION_ACCEPTED.value
    ):
        return (
            CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ADMISSION.value,
            "admission_not_accepted",
        )
    if not bool(admission.get("hydration_candidate")):
        return (
            CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ADMISSION.value,
            "admission_not_hydration_candidate",
        )
    if bool(admission.get("executable")):
        return (
            CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ADMISSION.value,
            "admission_must_not_be_executable",
        )
    if bool(admission.get("training_eligible")):
        return (
            CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ADMISSION.value,
            "admission_must_not_be_training_eligible",
        )
    return None


def _scan_passes(scan: dict[str, Any]) -> bool:
    if str(scan.get("policy") or "").lower() != "pass":
        return False
    return int(scan.get("critical") or 0) == 0 and int(scan.get("high") or 0) == 0


def _compact_scan(scan: dict[str, Any]) -> dict[str, Any]:
    allowed = ("scanner", "policy", "critical", "high", "medium", "low", "artifact")
    return {key: scan.get(key) for key in allowed if key in scan}


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


def _pinned_ref(provenance: dict[str, Any]) -> str:
    registry = str(provenance.get("registry") or "docker.io")
    repository = str(provenance.get("repository") or "")
    digest = str(provenance.get("manifest_digest") or "")
    return f"{registry}/{repository}@{digest}"


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=900, check=False
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
        description="Import an admitted ProgramBench cleanroom image artifact."
    )
    parser.add_argument("provenance_record", type=Path)
    parser.add_argument("admission_record", type=Path)
    parser.add_argument("--artifact-path", type=Path)
    parser.add_argument("--observed-digest", default="")
    parser.add_argument("--scan-result", type=Path)
    parser.add_argument("--live-docker-pull", action="store_true")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_image_import"),
    )
    parser.add_argument(
        "--quarantine-dir",
        type=Path,
        default=Path("T:/determinex_artifacts/quarantine/programbench"),
    )
    args = parser.parse_args()
    scan = _read_json(args.scan_result) if args.scan_result else {}
    result = ProgramBenchCleanroomImageImport(
        CleanroomImageImportConfig(
            root=args.root, output_dir=args.output_dir, quarantine_dir=args.quarantine_dir
        )
    ).import_image(
        args.provenance_record,
        args.admission_record,
        artifact_path=args.artifact_path,
        observed_digest=args.observed_digest,
        scan_result=scan,
        live_docker_pull=args.live_docker_pull,
    )
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
