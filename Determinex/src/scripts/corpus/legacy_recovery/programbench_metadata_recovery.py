#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.programbench_metadata_sources import collect_metadata_evidence
from corpus.legacy_recovery.programbench_replay_manifest import (
    ReplayManifest,
    write_replay_manifest,
)


class MetadataRecoveryStatus(str, Enum):
    METADATA_EXACT_MATCH = "METADATA_EXACT_MATCH"
    METADATA_RECONSTRUCTED_HIGH_CONFIDENCE = "METADATA_RECONSTRUCTED_HIGH_CONFIDENCE"
    METADATA_RECONSTRUCTED_LOW_CONFIDENCE = "METADATA_RECONSTRUCTED_LOW_CONFIDENCE"
    LOCAL_VERIFIER_METADATA_FOUND = "LOCAL_VERIFIER_METADATA_FOUND"
    TASK_IMAGE_FOUND = "TASK_IMAGE_FOUND"
    TASK_IMAGE_SOURCE_CANDIDATE_FOUND = "TASK_IMAGE_SOURCE_CANDIDATE_FOUND"
    TASK_IMAGE_UNRESOLVED = "TASK_IMAGE_UNRESOLVED"
    METADATA_CONFLICT = "METADATA_CONFLICT"
    METADATA_RECOVERY_FAILED = "METADATA_RECOVERY_FAILED"


HYDRATION_UNLOCK_STATUSES = {
    MetadataRecoveryStatus.METADATA_EXACT_MATCH.value,
    MetadataRecoveryStatus.LOCAL_VERIFIER_METADATA_FOUND.value,
    MetadataRecoveryStatus.TASK_IMAGE_FOUND.value,
}


@dataclass(slots=True)
class MetadataRecoveryConfig:
    output_path: Path = Path(
        "assurance/evidence/programbench_replay_batch_001_metadata_recovery.json"
    )
    manifest_root: Path = Path("assurance/evidence/programbench_replay_manifests")


@dataclass(slots=True)
class MetadataRecoveryResult:
    tool: str
    status: str = ""
    selected_root: str = ""
    task_image: str = ""
    local_replay_command: str = ""
    expected_verifier_mode: str = ""
    benchmark_provenance: dict[str, Any] = field(default_factory=dict)
    artifact_source_candidates: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    qualifies_hydration: bool = False
    quarantine_only: bool = False
    reason: str = ""
    replay_manifest: str = ""


class ProgramBenchMetadataRecovery:
    def __init__(self, config: MetadataRecoveryConfig | None = None) -> None:
        self.config = config or MetadataRecoveryConfig()

    def recover_batch(self, image_hydration_report: Path) -> dict[str, Any]:
        data = json.loads(image_hydration_report.read_text(encoding="utf-8"))
        rows = list(data.get("results") or [])
        results = [self.recover_candidate(row) for row in rows]
        counts = _counts(result.status for result in results)
        report = {
            "schema_version": "determinex-programbench-metadata-recovery-v1",
            "batch_id": str(data.get("batch_id") or "legacy_replay_promotion_batch_001"),
            "source_report": str(image_hydration_report),
            "candidates": len(results),
            "hydration_unlocked": sum(1 for result in results if result.qualifies_hydration),
            "quarantine_only": sum(1 for result in results if result.quarantine_only),
            "status_counts": counts,
            "results": [asdict(result) for result in results],
            "policy": "Recovered metadata may qualify replay. Guessed metadata only creates candidate records. Nothing executes from a guess.",
        }
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report

    def recover_candidate(self, row: dict[str, Any]) -> MetadataRecoveryResult:
        tool = str(row.get("tool") or "")
        root = Path(str(row.get("selected_root") or ""))
        result = MetadataRecoveryResult(
            tool=tool, selected_root=str(root) if str(root) != "." else ""
        )
        if not tool or not root or not root.exists():
            result.status = MetadataRecoveryStatus.METADATA_RECOVERY_FAILED.value
            result.reason = "selected_root_missing"
            return result

        evidence = collect_metadata_evidence(row, root)
        result.benchmark_provenance = dict(evidence.provenance)
        result.benchmark_provenance.setdefault("selected_root", str(root))
        result.benchmark_provenance.setdefault("tool", tool)

        images = sorted(set(evidence.task_images.values()))
        if len(images) > 1:
            result.status = MetadataRecoveryStatus.METADATA_CONFLICT.value
            result.reason = "conflicting_task_image_metadata"
            result.artifact_source_candidates = [
                {"task_image": image, "source": source}
                for source, image in sorted(evidence.task_images.items())
            ]
            return self._write_manifest(result)
        if images:
            result.task_image = images[0]
            result.status = MetadataRecoveryStatus.TASK_IMAGE_FOUND.value
            result.expected_verifier_mode = "programbench_image"
            result.confidence = 1.0
            result.qualifies_hydration = True
            result.reason = "explicit_task_image_metadata"
            return self._write_manifest(result)

        verifier = _first_local_verifier(evidence.local_verifiers)
        if verifier:
            command = str(
                verifier.get("local_verifier_command") or verifier.get("command") or ""
            ).strip()
            if command:
                result.local_replay_command = command
                result.status = MetadataRecoveryStatus.LOCAL_VERIFIER_METADATA_FOUND.value
                result.expected_verifier_mode = "local_replay"
                result.confidence = 1.0
                result.qualifies_hydration = True
                result.reason = "explicit_local_verifier_metadata"
                return self._write_manifest(result)

        if evidence.dockerfiles:
            result.status = MetadataRecoveryStatus.TASK_IMAGE_SOURCE_CANDIDATE_FOUND.value
            result.expected_verifier_mode = "candidate_image_build"
            result.confidence = 0.75
            result.quarantine_only = True
            result.reason = "dockerfile_candidate_requires_pinning_and_scan"
            result.artifact_source_candidates = [
                {
                    "artifact_type": "dockerfile",
                    "path": dockerfile,
                    "use": "quarantine_build_candidate",
                }
                for dockerfile in evidence.dockerfiles[:5]
            ]
            return self._write_manifest(result)

        if evidence.executables and evidence.build_files:
            result.status = MetadataRecoveryStatus.METADATA_RECONSTRUCTED_HIGH_CONFIDENCE.value
            result.expected_verifier_mode = "local_replay_candidate"
            result.local_replay_command = f".\\{evidence.executables[0]}"
            result.confidence = 0.7
            result.quarantine_only = True
            result.reason = "root_has_binary_and_build_metadata_but_no_explicit_verifier"
            return self._write_manifest(result)

        if evidence.build_files or evidence.module_files:
            result.status = MetadataRecoveryStatus.METADATA_RECONSTRUCTED_LOW_CONFIDENCE.value
            result.expected_verifier_mode = "source_shape_candidate"
            result.confidence = 0.35
            result.quarantine_only = True
            result.reason = "source_shape_detected_without_executable_metadata"
            return self._write_manifest(result)

        result.status = MetadataRecoveryStatus.TASK_IMAGE_UNRESOLVED.value
        result.reason = "no_task_image_local_verifier_or_reconstructable_source_shape"
        return self._write_manifest(result)

    def _write_manifest(self, result: MetadataRecoveryResult) -> MetadataRecoveryResult:
        manifest = ReplayManifest(
            tool=result.tool,
            selected_root=result.selected_root,
            metadata_status=result.status,
            qualifies_hydration=result.qualifies_hydration,
            quarantine_only=result.quarantine_only,
            task_image=result.task_image,
            local_replay_command=result.local_replay_command,
            verifier_mode=result.expected_verifier_mode,
            benchmark_provenance=result.benchmark_provenance,
            artifact_source_candidates=result.artifact_source_candidates,
            confidence=result.confidence,
            reason=result.reason,
        )
        result.replay_manifest = str(write_replay_manifest(manifest, self.config.manifest_root))
        return result


def _first_local_verifier(verifiers: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for _source, data in sorted(verifiers.items()):
        if (
            data.get("local_verifier_allowed") is True
            or data.get("command")
            or data.get("local_verifier_command")
        ):
            return data
    return None


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover ProgramBench replay metadata without executing guesses."
    )
    parser.add_argument("image_hydration_report", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/programbench_replay_batch_001_metadata_recovery.json"),
    )
    parser.add_argument(
        "--manifest-root",
        type=Path,
        default=Path("assurance/evidence/programbench_replay_manifests"),
    )
    args = parser.parse_args()
    report = ProgramBenchMetadataRecovery(
        MetadataRecoveryConfig(output_path=args.output, manifest_root=args.manifest_root)
    ).recover_batch(args.image_hydration_report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
