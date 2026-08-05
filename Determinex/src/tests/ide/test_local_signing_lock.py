"""Tests for the local-signing helper underpinning
APPROVAL_SIGNATURE_CRYPTOGRAPHIC_BINDING_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ls = importlib.import_module("ide.local_signing")

LOCK_PATH = (
    _REPO_ROOT / "locks" / "sentinel" / "APPROVAL_SIGNATURE_CRYPTOGRAPHIC_BINDING_LOCK_001.json"
)
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "approval_signature_cryptographic_binding"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _payload(**overrides):
    base = dict(
        trace_id="t-1",
        canonical_patch_body_hash="d" * 64,
        diff_hash="e" * 64,
        verifier_status="PATCH_VERIFIER_PASSED_TEMP_ONLY",
        rollback_snapshot_ref="/tmp/snap",
        workspace_identity="/ws",
        operator_identity="ryan",
        stale_after="2026-05-29T00:00:00+00:00",
    )
    base.update(overrides)
    return ls.canonical_payload(**base)


def test_sign_and_verify_round_trip(tmp_path):
    p = _payload()
    sig = ls.sign(p, secret_path=tmp_path / "sec")
    assert ls.verify(p, sig, secret_path=tmp_path / "sec") is True


def test_signature_is_64_hex(tmp_path):
    sig = ls.sign(_payload(), secret_path=tmp_path / "sec")
    assert len(sig) == 64
    int(sig, 16)  # parses as hex


def test_tampered_payload_invalid(tmp_path):
    p = _payload()
    sig = ls.sign(p, secret_path=tmp_path / "sec")
    tampered = _payload(operator_identity="mallory")
    assert ls.verify(tampered, sig, secret_path=tmp_path / "sec") is False


def test_different_secret_invalid(tmp_path):
    p = _payload()
    sig = ls.sign(p, secret_path=tmp_path / "secA")
    # Different secret directory ⇒ different secret ⇒ verify fails.
    assert ls.verify(p, sig, secret_path=tmp_path / "secB") is False


def test_workspace_identity_does_not_appear_in_payload():
    """The raw workspace_identity must be hashed, not embedded."""
    raw = "/c/Users/secret/private"
    p = ls.canonical_payload(
        trace_id="t",
        canonical_patch_body_hash="",
        diff_hash="",
        verifier_status="",
        rollback_snapshot_ref="",
        workspace_identity=raw,
        operator_identity="x",
        stale_after="0",
    )
    assert b"secret" not in p
    assert b"private" not in p
    # But the hash should be there.
    import hashlib

    assert hashlib.sha256(raw.encode("utf-8")).hexdigest().encode() in p


def test_signature_kind_constant_exposed():
    assert ls.SIGNATURE_KIND_HMAC == "real_local_hmac"


def test_invalid_signature_shape_verify_returns_false(tmp_path):
    assert ls.verify(b"x", "", secret_path=tmp_path / "sec") is False
    assert ls.verify(b"x", "short", secret_path=tmp_path / "sec") is False


def test_module_does_not_open_network():
    src = Path(ls.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "urllib.request",
    ):
        assert forbidden not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "APPROVAL_SIGNATURE_CRYPTOGRAPHIC_BINDING_LOCK_001"
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "APPROVAL_SIGNATURE_CRYPTOGRAPHIC_BINDING_LOCK_001" in ids
