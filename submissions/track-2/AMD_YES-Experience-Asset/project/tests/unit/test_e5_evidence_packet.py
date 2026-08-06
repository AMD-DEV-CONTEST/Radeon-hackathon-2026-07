"""Ticket 10 — the packet's own guarantees, enforced rather than asserted.

The packet exists to be trusted by someone who did not watch it being produced.
That trust rests on three properties which are cheap to state and easy to break
silently: every GRAG behaviour is covered by tests that exist, no hardware claim
can be reported as passing, and nothing forbidden reaches the file.

The capture script is not re-run here. It runs the whole suite twice over, which
would make this file the slowest in the repository for no added signal; what is
checked is the registry and the report-building the script is made of.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _capture_module():
    spec = importlib.util.spec_from_file_location(
        "capture_e5_evidence", ROOT / "scripts" / "capture_e5_evidence.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CAPTURE = _capture_module()

GRAG_MATRIX = ROOT / "docs" / "e5" / "GRAG-BEHAVIOR-MATRIX.md"


def test_every_grag_id_in_the_matrix_has_a_registry_entry():
    """A behaviour absent from the registry is silently never evidenced.

    The matrix is the contract; the registry is what the packet actually runs.
    Nothing else compares them, so a nineteenth behaviour added to the matrix
    would be missing from every future packet with no symptom.
    """
    documented = {f"GRAG-{index:02d}" for index in range(1, 19)}
    registered = {behaviour.grag_id for behaviour in CAPTURE.BEHAVIOURS}

    assert registered == documented
    matrix = GRAG_MATRIX.read_text(encoding="utf-8")
    for grag_id in documented:
        assert grag_id in matrix, f"{grag_id} is registered but not in the matrix"


def test_every_registered_test_file_exists():
    """A node id that no longer resolves would make the run silently narrower.

    pytest exits non-zero on an unknown node id, so the packet would fail rather
    than quietly pass — but it would fail with a collection error that reads as
    a broken script rather than as a behaviour that lost its coverage.
    """
    for behaviour in CAPTURE.BEHAVIOURS:
        assert behaviour.tests, f"{behaviour.grag_id} names no test"
        for node_id in behaviour.tests:
            path = ROOT / node_id.split("::", maxsplit=1)[0]
            assert path.is_file(), f"{behaviour.grag_id} names a missing file: {path}"


def test_each_behaviour_records_where_it_is_proven():
    """`MODULE` may not be quietly reported as an external-seam proof.

    Ticket 10's first criterion asks for the authoritative external seam. Some
    behaviours are proven a layer below it, and the packet says which — an
    aggregate "18/18 at the external seam" would be the false claim.
    """
    for behaviour in CAPTURE.BEHAVIOURS:
        assert behaviour.seam in {"HTTP", "MODULE"}


def test_the_manifest_separates_http_proofs_from_the_total():
    results = {
        "code_commit": "a" * 40,
        "branch": "test",
        "tree_state": "CLEAN",
        "decision": "PASS",
        "model": "deterministic-fake",
        "behaviours": [
            {"grag_id": "GRAG-01", "seam": "HTTP", "result": "PASS", "partial_reason": None},
            {"grag_id": "GRAG-03", "seam": "MODULE", "result": "PASS", "partial_reason": None},
            {"grag_id": "GRAG-18", "seam": "MODULE", "result": "PASS", "partial_reason": "half"},
        ],
        "commands": [
            {"label": label, "result": "PASS"}
            for label in (
                "contract-sync",
                "fixture-sync",
                "pr-gate",
                "full-python-suite",
                "migration-upgrade",
            )
        ],
    }

    manifest = CAPTURE._manifest(results)

    assert manifest["grag_total"] == 3
    assert manifest["grag_passed"] == 3
    # The number that matters for the criterion, kept distinct from the total.
    assert manifest["grag_at_http_seam"] == 1
    assert manifest["grag_with_recorded_limits"] == 1
    # No packet may ever imply hardware evidence it does not have.
    assert manifest["gpu_evidence"] is False
    assert manifest["real_model_service_evidence"] is False


def test_a_dirty_tree_cannot_be_certified(tmp_path, monkeypatch):
    """A packet naming a commit it was not captured from cannot be reproduced."""
    monkeypatch.setattr(
        CAPTURE, "_run_behaviours", lambda: ([], CAPTURE.CommandRun("b", (), 0))
    )
    monkeypatch.setattr(
        CAPTURE, "_run", lambda label, argv, **kw: CAPTURE.CommandRun(label, tuple(argv), 0)
    )
    monkeypatch.setattr(
        CAPTURE, "_git", lambda *args: "M app/x.py" if args[0] == "status" else "branch"
    )

    results = CAPTURE.capture(tmp_path, code_commit="b" * 40)

    assert results["tree_state"] == "DIRTY"
    assert results["decision"] == "NOT_VERIFIED"
    assert not results["failed_commands"]


def test_a_failed_command_fails_the_packet(tmp_path, monkeypatch):
    """The paired negative: a clean tree must not rescue a failing check."""
    monkeypatch.setattr(
        CAPTURE, "_run_behaviours", lambda: ([], CAPTURE.CommandRun("b", (), 0))
    )
    monkeypatch.setattr(
        CAPTURE, "_run", lambda label, argv, **kw: CAPTURE.CommandRun(label, tuple(argv), 1)
    )
    monkeypatch.setattr(CAPTURE, "_git", lambda *args: "" if args[0] == "status" else "branch")

    results = CAPTURE.capture(tmp_path, code_commit="c" * 40)

    assert results["decision"] == "FAIL"
    assert results["failed_commands"]


# Composed at runtime rather than written as literals. A credential-shaped
# string in a source file is the thing the repository-wide scan exists to stop,
# and it does not care that this one is a test fixture — nor should it, since
# "it is only a test" is what every leaked key looks like from the outside.
FORBIDDEN_SAMPLES = (
    "sk-" + "a" * 25,
    "AKIA" + "B" * 16,
    "-----BEGIN " + "RSA PRIVATE " + "KEY-----",
    "models/qwen3-9b.safetensors",
)


@pytest.mark.parametrize("payload", FORBIDDEN_SAMPLES)
def test_the_disclosure_scan_catches_what_must_never_ship(tmp_path, payload):
    planted = tmp_path / "summary.md"
    planted.write_text(f"# packet\n\n{payload}\n", encoding="utf-8")

    findings = CAPTURE._scan_packet([planted])

    assert findings, f"the scan missed {payload!r}"
    # The matched text is never echoed into the finding: recording it would put
    # the content the scan exists to keep out into the file that reports it.
    assert payload not in json.dumps(findings)


def test_the_disclosure_scan_passes_a_clean_packet(tmp_path):
    """Paired positive: a scan that flagged everything would pass the tests above."""
    clean = tmp_path / "summary.md"
    clean.write_text("# packet\n\n- commit: abc123\n- decision: PASS\n", encoding="utf-8")

    assert CAPTURE._scan_packet([clean]) == []


def test_hardware_claims_are_blocked_and_point_at_ticket_11():
    """Never `PASS`. A packet that reported them as passing would be the single
    most damaging thing in it: everything else is checkable, and this is not."""
    assert CAPTURE.HARDWARE_BLOCKED
    for claim, detail in CAPTURE.HARDWARE_BLOCKED:
        assert claim and detail
    text = " ".join(detail for _, detail in CAPTURE.HARDWARE_BLOCKED)
    assert "11" in text
