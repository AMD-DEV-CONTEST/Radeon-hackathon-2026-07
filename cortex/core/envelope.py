from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from cortex.core.canonical import _json_default


class EnvelopeType(StrEnum):
    PUBLISH = "publish"
    QUERY = "query"
    QUERY_RESULT = "query_result"
    SUBSCRIBE = "subscribe"
    DERIVE = "derive"
    EVENT = "event"
    METRICS = "metrics"
    ACK = "ack"
    ERROR = "error"


@dataclass
class Envelope:
    type: EnvelopeType
    msg_id: str
    src: str
    dst: str
    ts: datetime
    payload: dict


def envelope_to_json(env: Envelope) -> str:
    obj = {
        "type": env.type.value,
        "msg_id": env.msg_id,
        "src": env.src,
        "dst": env.dst,
        "ts": env.ts,
        "payload": env.payload,
    }
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def envelope_from_json(s: str) -> Envelope:
    obj = json.loads(s)
    try:
        etype = EnvelopeType(obj["type"])
    except ValueError as exc:
        raise ValueError(f"unknown EnvelopeType: {obj['type']!r}") from exc
    ts = obj["ts"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return Envelope(
        type=etype,
        msg_id=obj["msg_id"],
        src=obj["src"],
        dst=obj["dst"],
        ts=ts,
        payload=obj["payload"],
    )
