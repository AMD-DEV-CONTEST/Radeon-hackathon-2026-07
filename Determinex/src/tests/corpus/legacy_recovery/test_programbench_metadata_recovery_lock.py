from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.legacy_recovery.programbench_metadata_recovery import (  # noqa: E402
    MetadataRecoveryConfig,
    MetadataRecoveryStatus,
    ProgramBenchMetadataRecovery,
)


def _root(tmp_path: Path, tool: str = "bat") -> Path:
    root = tmp_path / "roots" / tool
    root.mkdir(parents=True)
    return root


def _row(root: Path, tool: str = "bat", **extra) -> dict:
    row = {
        "tool": tool,
        "selected_root": str(root),
        "legacy_row_hash": "legacy_cluster:bat-001",
        "language_guess": "rust",
        "expected_verifier": "programbench eval",
    }
    row.update(extra)
    return row


def _recovery(tmp_path: Path) -> ProgramBenchMetadataRecovery:
    return ProgramBenchMetadataRecovery(
        MetadataRecoveryConfig(
            output_path=tmp_path / "metadata_recovery.json",
            manifest_root=tmp_path / "manifests",
        )
    )


def test_task_image_found_unlocks_hydration(tmp_path):
    root = _root(tmp_path)
    (root / "manifest.json").write_text(
        json.dumps({"task_image": "programbench/bat@sha256:" + "a" * 64}),
        encoding="utf-8",
    )

    result = _recovery(tmp_path).recover_candidate(_row(root))

    assert result.status == MetadataRecoveryStatus.TASK_IMAGE_FOUND.value
    assert result.qualifies_hydration is True
    assert result.confidence == 1.0
    assert Path(result.replay_manifest).exists()


def test_local_verifier_metadata_found_unlocks_hydration(tmp_path):
    root = _root(tmp_path)
    (root / "local_verifier.json").write_text(
        json.dumps(
            {
                "local_verifier_allowed": True,
                "local_verifier_command": "python replay.py",
                "deterministic": True,
            }
        ),
        encoding="utf-8",
    )

    result = _recovery(tmp_path).recover_candidate(_row(root))

    assert result.status == MetadataRecoveryStatus.LOCAL_VERIFIER_METADATA_FOUND.value
    assert result.qualifies_hydration is True
    assert result.expected_verifier_mode == "local_replay"
    assert result.local_replay_command == "python replay.py"


def test_conflicting_task_image_metadata_blocks_hydration(tmp_path):
    root = _root(tmp_path)
    (root / "manifest.json").write_text(
        json.dumps({"task_image": "image-a@sha256:" + "a" * 64}), encoding="utf-8"
    )
    row = _row(root, task_image="image-b@sha256:" + "b" * 64)

    result = _recovery(tmp_path).recover_candidate(row)

    assert result.status == MetadataRecoveryStatus.METADATA_CONFLICT.value
    assert result.qualifies_hydration is False
    assert result.artifact_source_candidates


def test_dockerfile_creates_source_candidate_not_execution(tmp_path):
    root = _root(tmp_path)
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    result = _recovery(tmp_path).recover_candidate(_row(root))

    assert result.status == MetadataRecoveryStatus.TASK_IMAGE_SOURCE_CANDIDATE_FOUND.value
    assert result.qualifies_hydration is False
    assert result.quarantine_only is True
    assert result.artifact_source_candidates[0]["use"] == "quarantine_build_candidate"


def test_binary_plus_build_metadata_is_high_confidence_quarantine_only(tmp_path):
    root = _root(tmp_path)
    (root / "compile.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "bat").write_text("binary", encoding="utf-8")

    result = _recovery(tmp_path).recover_candidate(_row(root))

    assert result.status == MetadataRecoveryStatus.METADATA_RECONSTRUCTED_HIGH_CONFIDENCE.value
    assert result.qualifies_hydration is False
    assert result.quarantine_only is True


def test_source_shape_is_low_confidence_quarantine_only(tmp_path):
    root = _root(tmp_path)
    (root / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")

    result = _recovery(tmp_path).recover_candidate(_row(root))

    assert result.status == MetadataRecoveryStatus.METADATA_RECONSTRUCTED_LOW_CONFIDENCE.value
    assert result.qualifies_hydration is False
    assert result.quarantine_only is True


def test_missing_root_fails_recovery(tmp_path):
    missing = tmp_path / "missing"

    result = _recovery(tmp_path).recover_candidate(_row(missing))

    assert result.status == MetadataRecoveryStatus.METADATA_RECOVERY_FAILED.value


def test_batch_report_written(tmp_path):
    root = _root(tmp_path)
    (root / "manifest.json").write_text(
        json.dumps({"task_image": "programbench/bat@sha256:" + "a" * 64}),
        encoding="utf-8",
    )
    image_report = tmp_path / "image_hydration.json"
    image_report.write_text(
        json.dumps({"batch_id": "batch-001", "results": [_row(root)]}),
        encoding="utf-8",
    )

    report = _recovery(tmp_path).recover_batch(image_report)

    assert report["candidates"] == 1
    assert report["hydration_unlocked"] == 1
    assert report["status_counts"][MetadataRecoveryStatus.TASK_IMAGE_FOUND.value] == 1
    assert (tmp_path / "metadata_recovery.json").exists()
