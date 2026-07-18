from datetime import UTC, datetime

from cortex.core.envelope import (
    Envelope,
    EnvelopeType,
    envelope_from_json,
    envelope_to_json,
)


def _ts() -> datetime:
    return datetime(2026, 7, 15, 12, 34, 56, 789012, tzinfo=UTC)


def test_envelope_type_members():
    assert EnvelopeType.PUBLISH.value == "publish"
    assert EnvelopeType.QUERY.value == "query"
    assert EnvelopeType.QUERY_RESULT.value == "query_result"
    assert EnvelopeType.SUBSCRIBE.value == "subscribe"
    assert EnvelopeType.DERIVE.value == "derive"
    assert EnvelopeType.EVENT.value == "event"
    assert EnvelopeType.METRICS.value == "metrics"
    assert EnvelopeType.ACK.value == "ack"
    assert EnvelopeType.ERROR.value == "error"


def test_envelope_to_json_canonical_order_invariant():
    e1 = Envelope(
        type=EnvelopeType.PUBLISH,
        msg_id="11111111-1111-4111-8111-111111111111",
        src="did:percq:org:alpha",
        dst="*",
        ts=_ts(),
        payload={"b": 2, "a": 1},
    )
    e2 = Envelope(
        type=EnvelopeType.PUBLISH,
        msg_id="11111111-1111-4111-8111-111111111111",
        src="did:percq:org:alpha",
        dst="*",
        ts=_ts(),
        payload={"a": 1, "b": 2},
    )
    assert envelope_to_json(e1).encode("utf-8") == envelope_to_json(e2).encode("utf-8")


def test_envelope_to_json_known_shape():
    e = Envelope(
        type=EnvelopeType.QUERY,
        msg_id="11111111-1111-4111-8111-111111111111",
        src="did:percq:org:alpha",
        dst="did:percq:org:beta",
        ts=_ts(),
        payload={"k": 1},
    )
    expected = (
        b'{"dst":"did:percq:org:beta","msg_id":"11111111-1111-4111-8111-111111111111",'
        b'"payload":{"k":1},"src":"did:percq:org:alpha",'
        b'"ts":"2026-07-15T12:34:56.789012Z","type":"query"}'
    )
    assert envelope_to_json(e).encode("utf-8") == expected


def test_envelope_roundtrip_via_json():
    e = Envelope(
        type=EnvelopeType.EVENT,
        msg_id="22222222-2222-4222-8222-222222222222",
        src="broker",
        dst="did:percq:org:alpha",
        ts=_ts(),
        payload={"nested": {"y": 2, "x": 1}, "list": [3, 2, 1]},
    )
    s = envelope_to_json(e)
    back = envelope_from_json(s)
    assert back.type == EnvelopeType.EVENT
    assert back.msg_id == e.msg_id
    assert back.src == "broker"
    assert back.dst == "did:percq:org:alpha"
    assert back.ts == _ts()
    assert back.payload == e.payload


def test_envelope_from_json_rejects_unknown_type():
    import pytest
    with pytest.raises(ValueError):
        envelope_from_json(
            '{"dst":"*","msg_id":"x","payload":{},"src":"a",'
            '"ts":"2026-07-15T12:34:56.789012Z","type":"bogus"}'
        )
