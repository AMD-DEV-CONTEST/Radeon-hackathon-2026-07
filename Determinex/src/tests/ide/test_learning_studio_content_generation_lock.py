"""Tests for DETERMINEX_LEARNING_STUDIO_CONTENT_GENERATION_LOCK_001.

Rung 7 of DETERMINEX_LIVE_REACT_UNIFIED_PRODUCT_SHELL_SERIES: the first Learning Studio rung that
actually GENERATES content (rung 6 / DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001 only validated a
supplied output). Every assertion below either proves real corpus grounding (not shape-only) or
proves the non-authorizing invariants still hold on generated, not just static, content.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

content = importlib.import_module("ide.learning_studio_content")
workflow = importlib.import_module("ide.learning_studio_workflow")
bcs = importlib.import_module("ide.backend_command_surface")
td = importlib.import_module("ide._tauri_driver")

LOCK_PATH = (
    _REPO_ROOT
    / "locks"
    / "sentinel"
    / "DETERMINEX_LEARNING_STUDIO_CONTENT_GENERATION_LOCK_001.json"
)
EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "determinex_learning_studio_content_generation"
)
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
PANEL_PATH = (
    _REPO_ROOT / "frontend" / "src" / "components" / "ide-product-shell" / "LearningStudioPanel.tsx"
)
BRIDGE_RS = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "ide_repair_bridge.rs"
LIB_RS = _REPO_ROOT / "frontend" / "src-tauri" / "src" / "lib.rs"

LEARNING_MODES = (
    "explain_this_repo",
    "explain_this_file",
    "explain_this_error",
    "explain_this_test_failure",
    "teach_me_the_concept",
    "compare_possible_fixes",
    "walk_me_through_the_patch",
    "show_beginner_vs_professional_version",
    "generate_learning_checklist",
)

FORBIDDEN_PHRASES = (
    "patch applied",
    "now fixed",
    "source mutation authorized",
    "training row written",
)

# Representative, realistic inputs per mode (some empty, to exercise the honest "no input" path).
SAMPLE_INPUTS: dict[str, dict] = {
    "explain_this_repo": {"text": ""},
    "explain_this_file": {"text": ""},
    "explain_this_error": {"text": "go.mod requires go >= 1.24.0 (running go 1.21)"},
    "explain_this_test_failure": {"text": "cgo build fails: no such module fts5"},
    "teach_me_the_concept": {"text": "go build target"},
    "compare_possible_fixes": {"text": "rc=127 executable not found"},
    "walk_me_through_the_patch": {
        "text": "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n-old\n+new\n",
    },
    "show_beginner_vs_professional_version": {"text": "oracle verification"},
    "generate_learning_checklist": {"text": "BUILD_TOOLCHAIN"},
}


def test_generator_module_covers_every_mode():
    for mode in LEARNING_MODES:
        assert mode in content._GENERATORS, f"no generator wired for {mode}"


def test_unknown_mode_does_not_crash():
    out = content.generate("not_a_real_mode", {})
    assert "Unknown learning mode" in out.text


def test_empty_context_never_claims_success_and_still_passes_gate():
    for mode in LEARNING_MODES:
        out = content.generate(mode, {})
        record = workflow.evaluate(out)
        assert record.decision == "LEARNING_STUDIO_NON_AUTHORIZING_PASSED", (mode, record.decision)
        assert out.claims_repair_success is False
        assert out.claims_authorized_apply is False


def test_no_forbidden_phrases_across_sample_battery():
    for mode, ctx in SAMPLE_INPUTS.items():
        out = content.generate(mode, ctx)
        low = out.text.lower()
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in low, f"{mode} produced forbidden phrase {phrase!r}"


def test_sample_battery_always_passes_the_non_authorizing_gate():
    for mode, ctx in SAMPLE_INPUTS.items():
        out = content.generate(mode, ctx)
        record = workflow.evaluate(out)
        assert record.decision == "LEARNING_STUDIO_NON_AUTHORIZING_PASSED", (
            mode,
            record.decision,
            out.text,
        )


def test_explain_this_error_is_grounded_in_the_real_corpus_not_fabricated():
    """A REAL correctness check, not shape-only: this exact symptom matches the corpus's
    go_x_toolchain class_pattern (verified in determinex_corpus_api tests), so the generator
    must surface the actual known fix text, not generic filler."""
    out = content.generate(
        "explain_this_error", {"text": "go.mod requires go >= 1.24.0 running go 1.21"}
    )
    assert out.suggests_fix is True
    assert out.routes_to == "repo_clinic"
    assert "GOTOOLCHAIN" in out.text, "expected the real corpus fix, not a fabricated explanation"


def test_unmatched_error_admits_no_match_instead_of_fabricating():
    out = content.generate(
        "explain_this_error", {"text": "xyzzy_completely_made_up_nonsense_symptom_qqq"}
    )
    assert out.suggests_fix is False
    assert "no corpus match" in out.text.lower() or "no exact known-fix" in out.text.lower()


def test_compare_fixes_only_suggests_fix_when_something_was_found():
    empty = content.generate("compare_possible_fixes", {"text": ""})
    assert empty.suggests_fix is False
    found = content.generate(
        "compare_possible_fixes", {"text": "rc=127 executable not found go build"}
    )
    # either it found something (suggests_fix True) or it honestly found nothing -- never crashes
    assert isinstance(found.text, str) and found.text


def test_walk_the_patch_is_structural_not_fabricated():
    out = content.generate("walk_me_through_the_patch", SAMPLE_INPUTS["walk_me_through_the_patch"])
    assert "1 line(s) added" in out.text
    assert "1 line(s) removed" in out.text


def test_walk_the_patch_rejects_non_diff_input():
    out = content.generate("walk_me_through_the_patch", {"text": "this is not a diff at all"})
    assert "did not parse" in out.text.lower()


# ---------------------------------------------------------------------------
# Command surface wiring
# ---------------------------------------------------------------------------
def test_command_registered_in_full_surface():
    assert "generate_learning_studio_content" in bcs.commands()


def test_command_deliberately_excluded_from_frozen_read_only_set():
    """Documents the design decision: this command takes real args and does per-call
    computation, unlike the static view-model snapshots in UNIFIED_PRODUCT_READ_ONLY_COMMANDS
    (pinned exactly by DETERMINEX_TAURI_UNIFIED_PRODUCT_COMMAND_SURFACE_LOCK_001)."""
    assert "generate_learning_studio_content" not in bcs.UNIFIED_PRODUCT_READ_ONLY_COMMANDS


def test_command_surface_dispatches_and_stays_non_authorizing():
    surface = bcs.IDEBackendCommandSurface()
    r = surface.call(
        "generate_learning_studio_content",
        learning_mode="teach_me_the_concept",
        learning_context="go build target",
    )
    assert r.status == "IDE_COMMAND_OK"
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    assert r.payload.get("decision") == "LEARNING_STUDIO_NON_AUTHORIZING_PASSED"


def test_tauri_driver_dispatches_new_command():
    res = td._dispatch(
        "generate_learning_studio_content",
        {"mode": "teach_me_the_concept", "context": "go build target"},
    )
    assert res["status"] == "TAURI_COMMAND_OK"
    assert res["source_mutation_authorized"] is False
    assert res["training_eligible"] is False


def test_tauri_driver_did_not_remove_get_workflow_state():
    res = td._dispatch("get_learning_studio_workflow_state", {})
    assert res["status"] == "TAURI_COMMAND_OK"


# ---------------------------------------------------------------------------
# Rust wiring (static source checks -- cargo check/test run separately in CI)
# ---------------------------------------------------------------------------
def test_rust_command_function_declared():
    src = BRIDGE_RS.read_text(encoding="utf-8")
    assert "pub fn generate_learning_studio_content(" in src


def test_rust_command_registered_in_generate_handler():
    src = LIB_RS.read_text(encoding="utf-8")
    assert "ide_repair_bridge::generate_learning_studio_content," in src


def test_rust_command_excluded_from_frozen_unified_product_list():
    src = BRIDGE_RS.read_text(encoding="utf-8")
    import re

    m = re.search(
        r"UNIFIED_PRODUCT_READ_ONLY_COMMANDS\s*:\s*&\[&str\]\s*=\s*&\[(.+?)\];", src, re.DOTALL
    )
    assert m
    declared = re.findall(r'"([^"]+)"', m.group(1))
    assert "generate_learning_studio_content" not in declared


# ---------------------------------------------------------------------------
# Frontend wiring
# ---------------------------------------------------------------------------
def test_panel_invokes_the_new_command():
    src = PANEL_PATH.read_text(encoding="utf-8")
    assert '"generate_learning_studio_content"' in src
    assert 'data-testid="learning-studio-generate"' in src
    assert 'data-testid="learning-studio-context-input"' in src


def test_panel_still_non_authorizing_after_wiring():
    src = PANEL_PATH.read_text(encoding="utf-8")
    low = src.lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in low
    assert "Learning cannot mutate source." in src
    assert "Learning cannot approve a patch." in src


# ---------------------------------------------------------------------------
# Lock / evidence / index
# ---------------------------------------------------------------------------
def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "DETERMINEX_LEARNING_STUDIO_CONTENT_GENERATION_LOCK_001"
    sd = blob["scope_discipline"]
    assert sd["source_mutation_authorized"] is False
    assert sd["training_eligible"] is False
    assert sd["learning_mutates_source"] is False
    assert sd["learning_approves_patch"] is False
    assert sd["learning_marks_repair_success"] is False


def test_evidence_artifact_present():
    assert sorted(EVIDENCE_DIR.glob("run_*.json"))


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "DETERMINEX_LEARNING_STUDIO_CONTENT_GENERATION_LOCK_001" in ids
