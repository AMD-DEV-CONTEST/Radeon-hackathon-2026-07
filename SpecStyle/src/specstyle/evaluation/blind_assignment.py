"""Structural validation for untrusted external blind assignments."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from specstyle.calibration.evidence_io import _exact, _text, canonical_json
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes


def _timestamp(value: object) -> datetime:
    text = _text(value, "blind assignment time")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise DomainError("invalid machine evaluation ledger") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise DomainError("invalid machine evaluation ledger")
    return parsed


def validate_blind_assignment(
    ledger: dict[str, Any],
    protocol: dict[str, Any],
    assignments: tuple[tuple[str, str], ...],
    latest_observed_at: datetime,
) -> None:
    receipt = _exact(
        ledger["blind_assignment_receipt"],
        {
            "issued_at",
            "mapping_sha256",
            "presentation_order_sha256",
            "randomization_protocol_sha256",
            "randomizer_id",
            "schema_version",
            "trust_level",
        },
        "blind assignment receipt",
    )
    mapping = [
        {"artifact_sha256": artifact, "blind_artifact_id": blind_id}
        for artifact, blind_id in assignments
    ]
    canonical_order = [blind_id for _artifact, blind_id in assignments]
    presentation = ledger["blind_presentation_order"]
    if type(presentation) is not list:
        raise DomainError("invalid machine evaluation ledger")
    presentation_ids = [_text(item, "blind presentation id") for item in presentation]
    valid = (
        receipt["schema_version"] == "specstyle.evaluation.blind_assignment_receipt.v1"
        and receipt["trust_level"] == "UNVERIFIED_EXTERNAL_RANDOMIZER"
        and receipt["randomization_protocol_sha256"]
        == protocol["blind"]["randomization_protocol_sha256"]
        and receipt["mapping_sha256"] == hash_bytes(canonical_json(mapping)).value
        and receipt["presentation_order_sha256"]
        == hash_bytes(canonical_json(presentation_ids)).value
        and _timestamp(receipt["issued_at"]) >= latest_observed_at
        and len(presentation_ids) == len(canonical_order)
        and set(presentation_ids) == set(canonical_order)
        and (len(canonical_order) <= 1 or presentation_ids != canonical_order)
    )
    if not valid:
        raise DomainError("invalid machine evaluation ledger")
    _text(receipt["randomizer_id"], "blind randomizer id")
