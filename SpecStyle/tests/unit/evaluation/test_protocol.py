"""Formal five-arm preregistration and sealing contracts."""

from __future__ import annotations

import json

import pytest

from specstyle.calibration.evidence_io import canonical_json, evidence_sha256
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.evaluation.protocol import FORMAL_ARMS, prepare_protocol, seal_protocol

from tests.unit.evaluation._formal_fixtures import protocol_document, sha


def _sha(character: str) -> str:
    return sha(character)


def _draft() -> bytes:
    return protocol_document()


def test_prepare_protocol_accepts_canonical_complete_preregistration() -> None:
    prepared = prepare_protocol(_draft())

    assert prepared == _draft()
    assert json.loads(prepared)["arms"] == list(FORMAL_ARMS)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value["arms"].reverse(),
        lambda value: value["input_ids"].pop(),
        lambda value: value["seed_schedules"]["input-001"].pop(),
        lambda value: value["seed_schedules"].update({"extra": [1, 2, 3]}),
        lambda value: value["initial_request_sha256s"].pop("input-002"),
        lambda value: value["statistics"].update({"sample_size": 3}),
    ),
)
def test_prepare_protocol_rejects_unfair_or_incomplete_design(mutate) -> None:
    value = json.loads(_draft())
    mutate(value)

    with pytest.raises(DomainError, match="evaluation protocol"):
        prepare_protocol(canonical_json(value))


def test_seal_protocol_requires_validated_production_gate() -> None:
    with pytest.raises(DomainError, match="PRODUCTION_THRESHOLD_NOT_VALIDATED"):
        seal_protocol(
            _draft(),
            object(),
            sealed_at="2026-08-03T10:00:00Z",
            repo_sha=_sha("c"),
            production_context_sha256=_sha("d"),
        )


def test_sealed_protocol_cross_binds_preregistration_and_gate_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "specstyle.evaluation.protocol.require_validated_production_threshold",
        lambda _value: None,
    )

    class _Pin:
        def __init__(self, value: str) -> None:
            self.sha256 = Sha256(value)

    class _Binding:
        production_approval_sha256 = Sha256(_sha("d"))
        preprocessor_pin = _Pin(_sha("5"))

    class _Threshold:
        production_binding = _Binding()
        pin = _Pin(_sha("e"))

    class _Gate:
        compiler_pin = _Pin(_sha("2"))
        l2_threshold_profile = _Threshold()

    sealed = seal_protocol(
        _draft(),
        _Gate(),
        sealed_at="2026-08-03T10:00:00Z",
        repo_sha=_sha("c"),
        production_context_sha256=_sha("d"),
    )
    value = json.loads(sealed)

    assert value == {
        "schema_version": "specstyle.evaluation.sealed_protocol.v1",
        "protocol_sha256": evidence_sha256(_draft()).value,
        "production_approval_sha256": _sha("d"),
        "production_context_sha256": _sha("d"),
        "repo_sha": _sha("c"),
        "sealed_at": "2026-08-03T10:00:00Z",
        "threshold_profile_sha256": _sha("e"),
        "trust_level": "LOCAL_PROCESS_ONLY",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("minimum_effect", 0.0),
        ("minimum_effect", -0.1),
        ("noninferiority_margin", 1.0),
    ),
)
def test_protocol_rejects_trivial_success_thresholds(field: str, value: float) -> None:
    document = json.loads(_draft())
    document["statistics"][field] = value

    with pytest.raises(DomainError, match="evaluation protocol"):
        prepare_protocol(canonical_json(document))
