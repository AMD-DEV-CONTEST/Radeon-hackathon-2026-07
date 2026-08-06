import json
from datetime import datetime

import pytest

try:
    from cortex.core.envelope import Envelope, EnvelopeType, envelope_from_json, envelope_to_json
except ImportError:
    pytest.skip("cortex-core envelope not yet available", allow_module_level=True)


def test_publish_envelope_roundtrip_preserves_required_fields():
    ts = datetime.fromisoformat("2026-07-18T12:00:00+00:00")
    env = Envelope(
        type=EnvelopeType.PUBLISH,
        msg_id="11111111-1111-4111-8111-111111111111",
        src="did:percq:org:soc-alpha",
        dst="*",
        ts=ts,
        payload={"article": {"id": "deadbeef", "scope": "public", "content": "TTP"}},
    )
    s = envelope_to_json(env)
    assert isinstance(s, str)
    obj = json.loads(s)
    for k in ("type", "msg_id", "src", "dst", "ts", "payload"):
        assert k in obj, f"missing {k}"
    back = envelope_from_json(s)
    assert back.type == EnvelopeType.PUBLISH
    assert back.msg_id == env.msg_id
    assert back.src == env.src
    assert back.dst == env.dst
    assert back.payload == env.payload


def test_envelope_to_json_is_canonical_string():
    ts = datetime.fromisoformat("2026-07-18T12:00:00+00:00")
    env = Envelope(
        type=EnvelopeType.ACK,
        msg_id="22222222-2222-4222-8222-222222222222",
        src="broker",
        dst="did:percq:org:soc-alpha",
        ts=ts,
        payload={},
    )
    s = envelope_to_json(env)
    assert s == envelope_to_json(env)
