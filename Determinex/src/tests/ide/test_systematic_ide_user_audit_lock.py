"""Tests for the systematic user-facing IDE audit."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

audit_mod = importlib.import_module("ide.systematic_ide_user_audit")


def _evidence_artefacts_present() -> bool:
    """True only when the evidence ARTEFACTS are here, not merely the index.

    The index is 1.2 MB and publishable on its own (determinex evidence validate needs it,
    and its 1,837 manifests live under locks/sentinel/); the artefacts are 273 MB and are
    not published. So `.is_dir()` on assurance/evidence became true in a checkout holding
    none of what release_gates actually reads.
    """
    ev = _REPO_ROOT / "assurance" / "evidence"
    return ev.is_dir() and any(c.is_dir() for c in ev.iterdir())


def test_systematic_audit_sections_pass_for_current_checkout():
    report = audit_mod.collect(_REPO_ROOT)
    payload = report.to_dict()

    assert payload["schema_version"] == "determinex-systematic-ide-user-audit-v1"
    assert payload["release_ready"] is False
    assert payload["authority_granted"] is False
    # `release_gates` reads assurance/evidence/determinex_release_gate_status/, and
    # assurance/ is on publish_mirror.NEVER -- so in the public checkout that section is
    # blocked for a structural reason, not a regression. Everything else must still be
    # unblocked, which is what this assertion is actually protecting.
    # Artefact DIRECTORIES, not just the index: the index alone is publishable and is now
    # published, so `.is_dir()` on the evidence folder became true in a checkout that has
    # none of the artefacts release_gates actually reads.
    expected_blocked = [] if _evidence_artefacts_present() else ["release_gates"]
    assert payload["blocked_section_ids"] == expected_blocked
    section_ids = {section["section_id"] for section in payload["sections"]}
    assert section_ids == {
        "mission_control",
        "tools_and_providers",
        "backend_commands",
        "release_gates",
        "repair_panels",
        "llm_program_advisor",
    }


def test_audit_report_written_with_non_authorizing_notes(tmp_path: Path):
    output = tmp_path / "audit.json"
    report = audit_mod.write_report(output, _REPO_ROOT)
    text = output.read_text(encoding="utf-8")

    # Same structural exemption as above: assurance/ is never published, so release_gates
    # is blocked in a public checkout. Tuple here, list there -- the two assertions read the
    # same field through different accessors, which is why fixing only one left CI red.
    assert report.blocked_section_ids == (
        () if _evidence_artefacts_present() else ("release_gates",)
    )
    assert "does not prove public release readiness" in text
    assert "universal verified support" in text
    assert '"authority_granted": false' in text
