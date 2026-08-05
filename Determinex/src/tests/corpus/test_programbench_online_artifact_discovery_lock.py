from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.corpus_manager import verify_signature  # noqa: E402
from corpus.legacy_recovery.online_artifact_discovery import (  # noqa: E402
    OnlineArtifactDiscovery,
    OnlineArtifactDiscoveryConfig,
    OnlineArtifactStatus,
)


def _registry(tmp_path: Path) -> Path:
    path = tmp_path / "artifact_sources.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "name": "docker_hub",
                        "type": "oci_registry",
                        "trust_level": "public_untrusted",
                        "allowed_for": ["image_metadata", "image_pull_if_digest_pinned"],
                        "requires_digest": True,
                        "requires_security_scan": True,
                    },
                    {
                        "name": "ghcr",
                        "type": "oci_registry",
                        "trust_level": "public_untrusted",
                        "allowed_for": ["image_metadata", "image_pull_if_digest_pinned"],
                        "requires_digest": True,
                        "requires_security_scan": True,
                    },
                    {
                        "name": "huggingface",
                        "type": "hf_hub",
                        "trust_level": "public_untrusted",
                        "allowed_for": ["artifact_snapshot"],
                        "requires_revision_pin": True,
                        "requires_license": True,
                    },
                    {
                        "name": "blocked_source",
                        "type": "oci_registry",
                        "trust_level": "blocked",
                        "allowed_for": ["image"],
                        "requires_digest": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _candidate(**extra) -> dict:
    row = {
        "artifact_id": "programbench/bat:task_cleanroom",
        "artifact_type": "oci_image",
        "source": "docker_hub",
        "image": "programbench/bat:task_cleanroom",
        "resolved_digest": "sha256:" + "a" * 64,
        "security_scan": {"scanner": "mock", "critical": 0, "high": 0, "policy": "pass"},
        "official_source": True,
    }
    row.update(extra)
    return row


def _discovery(tmp_path: Path, searcher):
    return OnlineArtifactDiscovery(
        OnlineArtifactDiscoveryConfig(
            source_registry_path=_registry(tmp_path),
            provenance_root=tmp_path / "provenance",
            quarantine_root=tmp_path / "quarantine",
            cache_root=tmp_path / "cache",
            output_path=tmp_path / "online_discovery.json",
            searcher=searcher,
        )
    )


def test_missing_local_image_triggers_online_discovery_and_pins_digest(tmp_path):
    request = {"tool": "bat"}
    discovery = _discovery(tmp_path, lambda _request: [_candidate()])

    result = discovery.discover_for_candidate(request)

    assert result.status == OnlineArtifactStatus.ONLINE_ARTIFACT_PINNED.value
    assert result.resolved_digest.startswith("sha256:")
    assert Path(result.provenance_path).exists()
    provenance = json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))
    assert verify_signature(provenance)


def test_tag_only_image_is_rejected(tmp_path):
    discovery = _discovery(tmp_path, lambda _request: [_candidate(resolved_digest="", digest="")])

    result = discovery.discover_for_candidate({"tool": "bat"})

    assert result.status == OnlineArtifactStatus.ONLINE_ARTIFACT_REJECTED.value
    assert result.reason in {"digest_required", "oci_digest_required"}


def test_ambiguous_equal_candidates_are_rejected(tmp_path):
    candidate_a = _candidate(artifact_id="programbench/bat:a", resolved_digest="sha256:" + "a" * 64)
    candidate_b = _candidate(artifact_id="programbench/bat:b", resolved_digest="sha256:" + "b" * 64)
    discovery = _discovery(tmp_path, lambda _request: [candidate_a, candidate_b])

    result = discovery.discover_for_candidate({"tool": "bat"})

    assert result.status == OnlineArtifactStatus.ONLINE_ARTIFACT_AMBIGUOUS.value


def test_public_untrusted_source_cannot_execute_without_scan(tmp_path):
    discovery = _discovery(tmp_path, lambda _request: [_candidate(security_scan=None)])

    result = discovery.discover_for_candidate({"tool": "bat"})

    assert result.status == OnlineArtifactStatus.ONLINE_ARTIFACT_REJECTED.value
    assert result.reason == "security_scan_missing"


def test_security_scan_failure_blocks_hydration(tmp_path):
    discovery = _discovery(
        tmp_path,
        lambda _request: [
            _candidate(
                security_scan={"scanner": "mock", "critical": 1, "high": 0, "policy": "fail"}
            )
        ],
    )

    result = discovery.discover_for_candidate({"tool": "bat"})

    assert result.status == OnlineArtifactStatus.ONLINE_ARTIFACT_REJECTED.value
    assert result.reason == "critical_or_high_findings"


def test_digest_mismatch_blocks_hydration(tmp_path):
    discovery = _discovery(
        tmp_path,
        lambda _request: [_candidate(expected_digest="sha256:" + "b" * 64)],
    )

    result = discovery.discover_for_candidate({"tool": "bat"})

    assert result.status == OnlineArtifactStatus.ONLINE_ARTIFACT_REJECTED.value
    assert result.reason == "digest_mismatch"


def test_huggingface_artifact_requires_exact_revision(tmp_path):
    hf = {
        "artifact_id": "org/programbench-fixtures",
        "artifact_type": "hf_snapshot",
        "source": "huggingface",
        "repo_id": "org/programbench-fixtures",
        "revision": "main",
        "license": "apache-2.0",
        "security_scan": {"scanner": "mock", "critical": 0, "high": 0, "policy": "pass"},
    }
    discovery = _discovery(tmp_path, lambda _request: [hf])

    result = discovery.discover_for_candidate({"tool": "bat"})

    assert result.status == OnlineArtifactStatus.ONLINE_ARTIFACT_REJECTED.value
    assert result.reason == "exact_revision_required"


def test_blocked_source_is_rejected(tmp_path):
    discovery = _discovery(tmp_path, lambda _request: [_candidate(source="blocked_source")])

    result = discovery.discover_for_candidate({"tool": "bat"})

    assert result.status == OnlineArtifactStatus.ONLINE_ARTIFACT_REJECTED.value
    assert result.reason == "source_blocked"


def test_existing_pinned_artifact_is_not_replaced_in_place(tmp_path):
    discovery = _discovery(tmp_path, lambda _request: [_candidate()])
    first = discovery.discover_for_candidate({"tool": "bat"})
    assert first.status == OnlineArtifactStatus.ONLINE_ARTIFACT_PINNED.value
    path = Path(first.provenance_path)
    original = path.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        _discovery(
            tmp_path,
            lambda _request: [_candidate(tag="mutated-after-pin")],
        ).discover_for_candidate({"tool": "bat"})

    assert path.read_text(encoding="utf-8") == original


def test_batch_report_written(tmp_path):
    discovery = _discovery(tmp_path, lambda _request: [_candidate()])

    report = discovery.discover_batch([{"tool": "bat"}])

    assert report["candidates"] == 1
    assert report["online_artifacts_pinned"] == 1
    assert (tmp_path / "online_discovery.json").exists()
