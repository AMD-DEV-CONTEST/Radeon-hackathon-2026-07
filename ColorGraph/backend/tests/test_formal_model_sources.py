from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from colorgraph.evaluation.formal_model_sources import (
    FormalModelArtifact,
    FormalModelSourceManifest,
    audit_formal_model_sources,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "docs" / "formal-model-source-registry-v1.json"


def _manifest() -> FormalModelSourceManifest:
    return FormalModelSourceManifest.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )


def _audit(manifest: FormalModelSourceManifest):
    payload = manifest.model_dump_json().encode()
    return audit_formal_model_sources(
        manifest,
        manifest_path=str(MANIFEST_PATH),
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def test_formal_registry_separates_license_clearance_from_runtime_readiness() -> None:
    report = _audit(_manifest())

    assert report.registry_integrity_passed is True
    assert report.project_execution_authorized is True
    assert report.project_authorization.public_redistribution_authorized is False
    assert report.project_authorization.human_gold_deferred is True
    assert set(report.license_cleared_candidates) == {
        "depth_anything_v2_small",
        "frame_depth_anything_v2_small",
        "sam21",
        "sam31",
        "sea_raft",
        "oneformer_ade20k_swin_large",
    }
    assert set(report.runtime_ready_candidates) == {
        "depth_anything_v2_small",
        "frame_depth_anything_v2_small",
        "sam21",
        "sea_raft",
        "oneformer_ade20k_swin_large",
    }


def test_noncommercial_and_ambiguous_weight_licenses_fail_closed() -> None:
    report = _audit(_manifest())
    audits = {audit.candidate_id: audit for audit in report.audits}

    assert audits["current_segformer_b0"].license_gate_passed is False
    assert audits["segformer_b5"].license_gate_passed is False
    assert "commercial_use_not_cleared" in audits[
        "segformer_b5"
    ].weights.blockers
    assert audits["cutie"].license_gate_passed is False
    assert "license_not_explicit" in audits["cutie"].weights.blockers
    assert audits["sam31"].source_gate_passed is True
    assert audits["sam31"].runtime_ready is False
    assert "weights_not_installed_and_hashed" in audits[
        "sam31"
    ].runtime_blockers


def test_stale_or_future_dated_official_sources_fail() -> None:
    manifest = _manifest()
    candidates = {
        candidate.candidate_id: candidate for candidate in manifest.candidates
    }
    candidates["sam21"].code.checked_on = date(2025, 1, 1)
    candidates["sam31"].weights.checked_on = date(2026, 8, 1)

    report = _audit(manifest)
    audits = {audit.candidate_id: audit for audit in report.audits}

    assert audits["sam21"].code.source_freshness_passed is False
    assert audits["sam31"].weights.source_freshness_passed is False


def test_installed_and_commercial_claims_require_hash_and_license() -> None:
    payload = {
        "kind": "weights",
        "url": "https://example.com/model",
        "revision": "a" * 40,
        "checked_on": "2026-07-30",
        "installed": True,
        "official_note": "Fixture.",
    }
    with pytest.raises(ValidationError, match="content SHA-256"):
        FormalModelArtifact.model_validate(payload)

    payload["installed"] = False
    payload["commercial_use_allowed"] = True
    with pytest.raises(ValidationError, match="explicit license"):
        FormalModelArtifact.model_validate(payload)
