"""Tests for DIAGNOSE_PROMPT_OPACITY_ENFORCEMENT_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.real_model_diagnose_with_build_verifier")
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "DIAGNOSE_PROMPT_OPACITY_ENFORCEMENT_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "diagnose_prompt_opacity_enforcement"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"


def _build_prompt(workspace_identity):
    return mod._build_prompt(
        build_system_id="pip",
        verifier_argv=("pytest", "-q"),
        workspace_identity=workspace_identity,
    )


def test_opacify_helper_exists_and_returns_safe_prefix():
    assert hasattr(mod, "_opacify_workspace_identity")
    out = mod._opacify_workspace_identity("/c/Users/secret/private")
    assert out.startswith("ws-")
    assert len(out) == 19  # "ws-" + 16 hex


def test_same_input_same_opaque_id():
    assert mod._opacify_workspace_identity("x") == mod._opacify_workspace_identity("x")


def test_different_input_different_opaque_id():
    assert mod._opacify_workspace_identity("a") != mod._opacify_workspace_identity("b")


def test_secrets_do_not_appear_in_prompt():
    """A workspace identity that looks like a secret/code/PII must
    not appear in the prompt body."""
    secret = "/home/alice/api_key=sk-LIVE-1234567890abcdef"
    p = _build_prompt(secret)
    assert "sk-LIVE" not in p
    assert "api_key" not in p
    assert "alice" not in p
    assert "/home/" not in p


def test_code_like_identity_does_not_leak():
    sneaky = "def evil():\n    import os\n    os.system('rm -rf /')\n"
    p = _build_prompt(sneaky)
    for forbidden in ("def evil", "import os", "os.system", "rm -rf"):
        assert forbidden not in p


def test_newlines_in_identity_do_not_leak():
    multi = "line1\nline2\nline3"
    p = _build_prompt(multi)
    assert "line1" not in p
    assert "line2" not in p
    assert "line3" not in p


def test_opaque_id_is_present_in_prompt():
    p = _build_prompt("/c/Dev/Determinex")
    opaque = mod._opacify_workspace_identity("/c/Dev/Determinex")
    assert opaque in p


def test_non_string_identity_is_coerced_safely():
    # Defensive: even if caller passes a non-string, opacify must not crash.
    p = _build_prompt(12345)  # type: ignore[arg-type]
    opaque = mod._opacify_workspace_identity("12345")
    assert opaque in p


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DIAGNOSE_PROMPT_OPACITY_ENFORCEMENT_LOCK_001"
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DIAGNOSE_PROMPT_OPACITY_ENFORCEMENT_LOCK_001" in ids
