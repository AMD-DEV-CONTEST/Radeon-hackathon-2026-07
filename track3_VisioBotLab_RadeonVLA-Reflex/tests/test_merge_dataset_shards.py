import json
from pathlib import Path

import pytest

from radeonvla.merge_dataset_shards import _combined_manifest, _preflight_source


def _certificate(index: int, task: str, seed: int) -> dict:
    return {
        "episode_index": index,
        "task_id": task,
        "seed": seed,
        "instruction": f"put {task}",
        "success": True,
        "strict_physics": True,
        "rigid_pose_write_guard": True,
        "kinematic_intervention_count": 0,
        "source_commit": "abc123",
    }


def _manifest(task: str, seed: int, successes: int = 1) -> dict:
    return {
        "repo_id": f"owner/{task}",
        "staging_root": f"/tmp/{task}",
        "fps": 20,
        "image_size": [240, 320],
        "joint_names": ["joint"],
        "features": {},
        "successes": successes,
        "failures_saved": 0,
        "attempts": successes,
        "max_attempts": 5,
        "task_cycle": [task],
        "seed": seed,
        "backend": "amdgpu",
        "strict_physics": True,
        "rigid_pose_write_guard": True,
        "kinematic_grasp_assist": False,
        "placement_nudge": False,
        "source_commit": "abc123",
    }


def test_combined_manifest_requires_exact_quota_and_unique_seeds(tmp_path: Path) -> None:
    manifests = [_manifest("apple_left", 10), _manifest("banana_right", 20)]
    certificates = [[_certificate(0, "apple_left", 10)], [_certificate(0, "banana_right", 20)]]
    result = _combined_manifest(
        repo_id="owner/physical-2",
        output_root=tmp_path / "merged",
        source_roots=[tmp_path / "apple", tmp_path / "banana"],
        manifests=manifests,
        certificates=certificates,
        episodes_per_task=1,
    )
    assert result["successes"] == 2
    assert result["per_task_successes"] == {"apple_left": 1, "banana_right": 1}
    assert result["source_commit"] == "abc123"
    assert result["source_commits"] == ["abc123"]

    certificates[1][0]["seed"] = 10
    with pytest.raises(RuntimeError, match="duplicate rollout seeds"):
        _combined_manifest(
            repo_id="owner/physical-2",
            output_root=tmp_path / "merged",
            source_roots=[tmp_path / "apple", tmp_path / "banana"],
            manifests=manifests,
            certificates=certificates,
            episodes_per_task=1,
        )


def test_preflight_rejects_non_strict_source(tmp_path: Path) -> None:
    root = tmp_path / "source"
    (root / "meta").mkdir(parents=True)
    (root / "certificates").mkdir()
    (root / "meta" / "info.json").write_text(json.dumps({"total_episodes": 1}), encoding="utf-8")
    manifest = _manifest("apple_left", 10)
    manifest["strict_physics"] = False
    (root / "recording_progress.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "certificates" / "episode_000000.json").write_text(
        json.dumps(_certificate(0, "apple_left", 10)), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="does not prove strict"):
        _preflight_source(root)


def test_combined_manifest_preserves_multiple_audited_revisions(tmp_path: Path) -> None:
    manifests = [_manifest("apple_left", 10), _manifest("banana_right", 20)]
    certificates = [[_certificate(0, "apple_left", 10)], [_certificate(0, "banana_right", 20)]]
    manifests[1]["source_commit"] = "def456"
    certificates[1][0]["source_commit"] = "def456"

    result = _combined_manifest(
        repo_id="owner/physical-2",
        output_root=tmp_path / "merged",
        source_roots=[tmp_path / "apple", tmp_path / "banana"],
        manifests=manifests,
        certificates=certificates,
        episodes_per_task=1,
    )

    assert result["source_commit"] is None
    assert result["source_commits"] == ["abc123", "def456"]
    assert result["aggregation_sources"][0]["source_commits"] == ["abc123"]
    assert result["aggregation_sources"][1]["source_commits"] == ["def456"]


def test_preflight_rejects_manifest_certificate_revision_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "source"
    (root / "meta").mkdir(parents=True)
    (root / "certificates").mkdir()
    (root / "meta" / "info.json").write_text(json.dumps({"total_episodes": 1}), encoding="utf-8")
    manifest = _manifest("apple_left", 10)
    (root / "recording_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    certificate = _certificate(0, "apple_left", 10)
    certificate["source_commit"] = "unexpected"
    (root / "certificates" / "episode_000000.json").write_text(
        json.dumps(certificate), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="do not match manifest revisions"):
        _preflight_source(root)
