"""SEC-001B provenance audit."""

from __future__ import annotations

from specstyle.domain.identifiers import Sha256
from specstyle.security.provenance import ProvenanceRecord, audit_provenance


def test_audit_incomplete_and_complete() -> None:
    rec = ProvenanceRecord(
        "a1", Sha256("a" * 64), "input", "https://x", None, "attr", "not_applicable"
    )
    audit = audit_provenance((rec,))
    assert audit.complete is False
    assert any("missing_license" in i for i in audit.issues)
    good = ProvenanceRecord(
        "a1", Sha256("a" * 64), "input", "https://x", "CC0", "attr", "not_applicable"
    )
    assert audit_provenance((good,)).complete is True
