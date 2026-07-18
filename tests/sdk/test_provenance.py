from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from cortex.sdk.provenance import ProvenanceHelpers


def test_from_seed_autofills_run_id_and_timestamp():
    prov = ProvenanceHelpers.from_seed(
        {"producer_agent": "did:org:alpha#agent-1", "producer_org": "did:org:alpha"}
    )
    assert prov.producer_agent == "did:org:alpha#agent-1"
    assert prov.producer_org == "did:org:alpha"
    # run_id parses as UUID4
    parsed = UUID(prov.run_id)
    assert parsed.version == 4
    # timestamp is timezone-aware UTC
    assert isinstance(prov.timestamp, datetime)
    assert prov.timestamp.tzinfo == UTC


def test_from_seed_respects_caller_run_id_and_timestamp():
    fixed_ts = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
    prov = ProvenanceHelpers.from_seed(
        {
            "producer_agent": "a",
            "producer_org": "o",
            "run_id": "fixed-run",
            "timestamp": fixed_ts,
        }
    )
    assert prov.run_id == "fixed-run"
    assert prov.timestamp == fixed_ts


def test_with_source_hash_sets_sha256_and_schema():
    base = ProvenanceHelpers.from_seed(
        {"producer_agent": "a", "producer_org": "o"}
    )
    raw = b"sensor-telemetry:42"
    expected = hashlib.sha256(raw).hexdigest()

    prov = ProvenanceHelpers.with_source_hash(
        base, raw_data=raw, schema_desc="f1.sensor.v1"
    )

    assert prov.source_data_hash == expected
    assert prov.source_data_schema == "f1.sensor.v1"
    # base object untouched
    assert base.source_data_hash is None
    # other fields preserved
    assert prov.producer_agent == base.producer_agent
    assert prov.run_id == base.run_id
