from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

import trusted_katago_artifacts as trusted  # noqa: E402


def valid_artifact() -> dict:
    return {
        "schemaVersion": trusted.ARTIFACT_SCHEMA,
        "source": "katago",
        "demo": False,
        "engine": {
            "name": "KataGo",
            "version": "1.16.5",
            "backend": "OpenCL",
            "binarySha256": "1" * 64,
        },
        "model": {
            "name": "kata1-b18c384nbt-s9996604416-d4316597426",
            "sha256": "2" * 64,
        },
        "config": {
            "sha256": "3" * 64,
            "maxVisits": 128,
            "analysisPVLen": 12,
        },
        "rules": {
            "name": "chinese",
            "komi": 7.5,
            "boardSize": 19,
        },
        "position": {
            "analysisPositionHashBefore": "4" * 64,
            "moveNumber": 0,
        },
        "subjectColor": "B",
        "valuePerspective": "subject",
        "visits": 128,
        "bestMove": "Q16",
        "candidates": [
            {
                "move": "Q16",
                "visits": 96,
                "winrate": 0.55,
                "scoreLead": 1.3,
                "pv": ["Q16", "D16"],
            },
            {
                "move": "D4",
                "visits": 32,
                "winrate": 0.48,
                "scoreLead": -0.8,
                "pv": ["D4", "Q16"],
            },
        ],
    }


def write_registry(tmp_path: Path, artifact: dict | None = None):
    entry = trusted.make_registry_entry(
        artifact or valid_artifact(),
        registered_at="2026-08-01T00:00:00Z",
        instance_id="pytest-backend",
    )
    path = tmp_path / "trusted-katago.jsonl"
    snapshot_sha = trusted.write_registry_snapshot(path, [entry])
    return path, snapshot_sha, entry


def test_registry_is_bound_to_explicit_snapshot_hash(tmp_path: Path) -> None:
    path, snapshot_sha, entry = write_registry(tmp_path)
    registry = trusted.load_registry_snapshot(path, expected_sha256=snapshot_sha)
    artifact = registry.resolve(
        {
            "artifactId": entry["artifactId"],
            "artifactSha256": entry["artifactSha256"],
            "registrySnapshotSha256": snapshot_sha,
        }
    )
    assert artifact["bestMove"] == "Q16"

    with pytest.raises(trusted.RegistryError, match="registry.*SHA-256"):
        trusted.load_registry_snapshot(path, expected_sha256="f" * 64)


def test_forged_values_with_recomputed_artifact_hash_are_not_registered(
    tmp_path: Path,
) -> None:
    path, snapshot_sha, entry = write_registry(tmp_path)
    registry = trusted.load_registry_snapshot(path, expected_sha256=snapshot_sha)

    forged = copy.deepcopy(entry["artifact"])
    forged["candidates"][0]["winrate"] = 0.99
    forged_sha = trusted.canonical_json_sha256(forged)
    forged_ref = {
        "artifactId": f"katago:{forged_sha}",
        "artifactSha256": forged_sha,
        "registrySnapshotSha256": snapshot_sha,
    }
    with pytest.raises(trusted.RegistryError, match="未登记"):
        registry.resolve(forged_ref)


def test_loader_rejects_entry_tampering_even_if_artifact_hash_is_recomputed(
    tmp_path: Path,
) -> None:
    path, snapshot_sha, entry = write_registry(tmp_path)
    forged = copy.deepcopy(entry)
    forged["artifact"]["candidates"][0]["scoreLead"] = 99.0
    forged["artifactSha256"] = trusted.canonical_json_sha256(forged["artifact"])
    forged["artifactId"] = f"katago:{forged['artifactSha256']}"
    # 攻击者同时重算 artifact 哈希，但无法伪造原登记条目的 entry 哈希。
    path.write_text(json.dumps(forged, ensure_ascii=False) + "\n", encoding="utf-8")
    forged_snapshot = trusted.sha256_file(path)
    assert forged_snapshot != snapshot_sha
    with pytest.raises(trusted.RegistryError, match="entrySha256"):
        trusted.load_registry_snapshot(path, expected_sha256=forged_snapshot)


def test_sqlite_registration_exports_a_pinned_registry_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "server.db"
    entry = trusted.register_artifact_sqlite(
        database,
        valid_artifact(),
        registered_at="2026-08-01T00:00:00Z",
        instance_id="pytest-backend",
    )
    output = tmp_path / "export.jsonl"
    snapshot_sha = trusted.export_registry_snapshot(database, output)
    registry = trusted.load_registry_snapshot(output, expected_sha256=snapshot_sha)
    assert registry.get(entry["artifactId"])["model"]["sha256"] == "2" * 64


def test_server_projection_converts_black_values_to_white_subject_perspective() -> None:
    artifact = trusted.artifact_from_server_analysis(
        {
            "visits": 128,
            "recommendations": [
                {
                    "move": "Q16",
                    "visits": 96,
                    "winrateBlack": 0.35,
                    "scoreLeadBlack": -2.5,
                    "pv": ["Q16", "D16"],
                },
                {
                    "move": "D4",
                    "visits": 32,
                    "winrateBlack": 0.55,
                    "scoreLeadBlack": 1.0,
                    "pv": ["D4", "Q16"],
                },
            ],
        },
        engine_version="1.16.5",
        engine_backend="OpenCL",
        engine_binary_sha256="1" * 64,
        model_name="kata1-b18",
        model_sha256="2" * 64,
        config_sha256="3" * 64,
        max_visits=128,
        analysis_pv_len=12,
        rules_name="chinese",
        komi=7.5,
        board_size=19,
        analysis_position_hash_before="4" * 64,
        move_number=0,
        subject_color="W",
    )
    assert artifact["subjectColor"] == "W"
    assert artifact["candidates"][0]["winrate"] == pytest.approx(0.65)
    assert artifact["candidates"][0]["scoreLead"] == pytest.approx(2.5)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("engine", "binarySha256"), "", "binarySha256"),
        (("model", "sha256"), "", "model.sha256"),
        (("config", "sha256"), "", "config.sha256"),
        (("rules", "name"), "", "rules.name"),
        (("position", "analysisPositionHashBefore"), "", "position.*Hash"),
        (("valuePerspective",), "black", "valuePerspective.*subjectColor"),
        (("visits",), 32, "visits.*128"),
    ],
)
def test_canonical_artifact_requires_full_authority_identity(
    path: tuple[str, ...], value: object, message: str
) -> None:
    artifact = valid_artifact()
    cursor = artifact
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(trusted.RegistryError, match=message):
        trusted.canonicalize_artifact(artifact)
