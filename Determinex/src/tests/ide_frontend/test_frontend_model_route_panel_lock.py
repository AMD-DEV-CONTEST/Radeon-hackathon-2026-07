"""Tests for FRONTEND_MODEL_ROUTE_PANEL_LOCK_001."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

PANEL = _REPO_ROOT / "frontend" / "src" / "components" / "ide-repair" / "ModelRoutePanel.tsx"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "FRONTEND_MODEL_ROUTE_PANEL_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "frontend_model_route_panel"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

STATUS_TOKENS = frozenset(
    {
        "MODEL_ROUTE_PANEL_READY",
        "MODEL_ROUTE_DRY_RUN_VISIBLE",
        "MODEL_ROUTE_LIVE_OPT_IN_VISIBLE",
        "MODEL_ROUTE_BLOCKED_NO_MODEL_VISIBLE",
        "MODEL_ROUTE_NETWORK_BLOCKED_VISIBLE",
    }
)


def test_panel_exists():
    assert PANEL.is_file()


def test_panel_status_tokens_exact():
    src = PANEL.read_text(encoding="utf-8")
    m = re.search(r"FRONTEND_MODEL_ROUTE_PANEL_STATUS_TOKENS\s*=\s*\[([^\]]+)\]\s*as\s*const", src)
    assert m
    declared = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert declared == STATUS_TOKENS


def test_panel_calls_get_model_route_status():
    src = PANEL.read_text(encoding="utf-8")
    assert '"get_model_route_status"' in src


def test_panel_shows_dry_run_default():
    src = PANEL.read_text(encoding="utf-8")
    assert "Dry-run default" in src
    assert 'data-testid="model-route-dry-run-note"' in src


def test_panel_shows_live_opt_in_advisory():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="model-route-live-opt-in-note"' in src
    assert "advisory" in src.lower()


def test_panel_shows_blocked_no_model():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="model-route-blocked-note"' in src


def test_panel_shows_network_blocked():
    src = PANEL.read_text(encoding="utf-8")
    assert 'data-testid="model-route-network-blocked-note"' in src
    assert "Network" in src


def test_panel_no_source_apply():
    src = PANEL.read_text(encoding="utf-8")
    for n in ("Apply to Source", "Commit", "source_apply"):
        assert n not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "FRONTEND_MODEL_ROUTE_PANEL_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(STATUS_TOKENS)


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "FRONTEND_MODEL_ROUTE_PANEL_LOCK_001" in ids
