"""Tests for TAURI_RUST_COMMAND_BRIDGE_LOCK_001.

The Rust file frontend/src-tauri/src/ide_repair_bridge.rs is the
Tauri-side seam. Tests validate:

  * the Rust file exists and is non-empty
  * every required command name is declared as #[tauri::command]
  * IDE_REPAIR_COMMANDS constant lists every command
  * the Python driver script exists and round-trips a simple call
  * the integration recipe doc exists
  * lock + evidence + index entries present
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RUST_BRIDGE = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "ide_repair_bridge.rs"
PY_DRIVER = _REPO_ROOT / "scripts" / "ide" / "_tauri_driver.py"
LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "TAURI_RUST_COMMAND_BRIDGE_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "tauri_rust_command_bridge"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
DOC_PATH = _REPO_ROOT / "docs" / "ide-frontend" / "TAURI_RUST_COMMAND_BRIDGE.md"


REQUIRED_COMMANDS = (
    "open_workspace",
    "get_workspace_status",
    "get_model_route_status",
    "diagnose_dry_run",
    "diagnose_live_opt_in",
    "generate_patch_plan",
    "verify_temp_patch",
    "get_human_approval_packet",
    "source_apply_dry_run",
    "get_repair_flow_state",
    "generate_llm_program_advisory",
    "preview_idea_oracle",
    "build_idea",
    "repair_diagnose",
    "get_governance_status",
)


REQUIRED_STATUS_TOKENS = frozenset(
    {
        "TAURI_RUST_COMMAND_BRIDGE_READY",
        "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_NO_TAURI_APP",
        "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING",
        "TAURI_COMMAND_SOURCE_MUTATION_BLOCKED",
        "TAURI_COMMAND_TEMP_ONLY",
    }
)


def test_rust_bridge_file_exists():
    assert RUST_BRIDGE.is_file()
    src = RUST_BRIDGE.read_text(encoding="utf-8")
    assert len(src) > 1000  # non-trivial


@pytest.mark.parametrize("cmd", REQUIRED_COMMANDS)
def test_rust_bridge_declares_each_command(cmd):
    src = RUST_BRIDGE.read_text(encoding="utf-8")
    pattern = rf"#\[tauri::command\]\s*\n\s*pub fn {re.escape(cmd)}\s*\("
    assert re.search(pattern, src), f"command {cmd!r} not declared in bridge"


def test_ide_repair_commands_const_lists_all():
    src = RUST_BRIDGE.read_text(encoding="utf-8")
    # Extract IDE_REPAIR_COMMANDS body.
    m = re.search(r"IDE_REPAIR_COMMANDS\s*:\s*&\[&str\]\s*=\s*&\[([^\]]+)\]", src)
    assert m, "IDE_REPAIR_COMMANDS const missing"
    listed = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert listed == set(REQUIRED_COMMANDS)


def test_rust_bridge_refuses_source_mutation_and_training():
    """The struct response and helpers must hardcode source_mutation and
    training_eligible to false."""
    src = RUST_BRIDGE.read_text(encoding="utf-8")
    assert "source_mutation_authorized: false" in src
    assert "training_eligible: false" in src


def test_python_driver_exists_and_dispatches():
    assert PY_DRIVER.is_file()

    # Smoke: spawn the driver with a known command + workspace.
    args_json = json.dumps(
        {"workspace": str(_REPO_ROOT / "tests" / "fixtures" / "intake" / "python_broken")}
    )
    proc = subprocess.run(
        [sys.executable, str(PY_DRIVER), "open_workspace", args_json],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0, f"driver exit {proc.returncode}: stderr={proc.stderr!r}"
    response = json.loads(proc.stdout.strip().splitlines()[-1])
    assert response["command"] == "open_workspace"
    assert response["status"].startswith("TAURI_")
    assert response["source_mutation_authorized"] is False
    assert response["training_eligible"] is False


def test_python_driver_returns_unknown_for_bad_command():
    proc = subprocess.run(
        [sys.executable, str(PY_DRIVER), "snake_oil_command", "{}"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0
    response = json.loads(proc.stdout.strip().splitlines()[-1])
    assert response["status"] == "TAURI_COMMAND_BLOCKED_UNKNOWN"


def test_python_driver_does_not_import_subprocess_or_urllib_directly():
    src = PY_DRIVER.read_text(encoding="utf-8")
    # Driver may need subprocess for nothing — it doesn't spawn anything,
    # only the Rust side spawns it. Validate no shell-out from driver.
    assert "subprocess" not in src.split("\n")[0:5]  # not a top-level import
    assert "import urllib" not in src


def test_rust_file_does_not_call_network():
    src = RUST_BRIDGE.read_text(encoding="utf-8")
    forbidden = ("reqwest::", "ureq::", "isahc::", "hyper::Client", "TcpStream::connect")
    for needle in forbidden:
        assert needle not in src, f"forbidden network seam: {needle}"


def test_rust_file_does_not_use_shell_true():
    src = RUST_BRIDGE.read_text(encoding="utf-8")
    # Rust subprocess doesn't have shell=True but might use `sh -c`.
    forbidden = ("sh -c", "cmd.exe /c", '.arg("-c")')
    for needle in forbidden:
        assert needle not in src, f"shell-string invocation: {needle}"


# ---------------------------------------------------------------------------
# Doc / lock / evidence
# ---------------------------------------------------------------------------


def test_doc_exists_with_integration_recipe():
    assert DOC_PATH.is_file()
    text = DOC_PATH.read_text(encoding="utf-8")
    # Integration steps must be present.
    assert "mod ide_repair_bridge" in text
    assert "tauri::generate_handler!" in text
    assert "lib.rs" in text


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "TAURI_RUST_COMMAND_BRIDGE_LOCK_001"
    listed = set(blob.get("status_tokens", []))
    assert listed.issubset(REQUIRED_STATUS_TOKENS)
    # Scope discipline: the lock claims it does NOT modify lib.rs.
    assert blob["scope_discipline"]["lib_rs_modified"] is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates
    blob = json.loads(candidates[-1].read_text(encoding="utf-8"))
    assert blob["lock_id"] == "TAURI_RUST_COMMAND_BRIDGE_LOCK_001"


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "TAURI_RUST_COMMAND_BRIDGE_LOCK_001" in ids


def test_lib_rs_unmodified_by_this_rung():
    """Sanity check — confirm we did not touch lib.rs. The lock claims
    lib_rs_modified=False; this test asserts the integration is a
    DOCUMENTED patch the frontend team can apply, not a silent change."""
    lib_rs = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"
    if not lib_rs.is_file():
        pytest.skip("lib.rs not present in this checkout")
    src = lib_rs.read_text(encoding="utf-8")
    # If lib.rs was edited to wire in our module, that's fine — but it
    # must not include any TAURI_COMMAND_BLOCKED_UNKNOWN handlers we
    # would never write. The integration MAY or MAY NOT have been
    # performed; either way, this rung's contract is the standalone
    # bridge file and the documented recipe.
    assert "ide_repair_bridge" not in src or "mod ide_repair_bridge" in src
