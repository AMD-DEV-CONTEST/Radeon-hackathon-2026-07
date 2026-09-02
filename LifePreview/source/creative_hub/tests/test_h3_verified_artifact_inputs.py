from __future__ import annotations

import hashlib
import json
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from shared_contracts import AtomicArtifactRef

from creative_hub.h3_artifact_inputs import (
    H3ArtifactInputError,
    VerifiedH3ArtifactInputs,
)


PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str
    value: str


class _FloatEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: float


class _NestedEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    payload: dict[str, object]


class _Gateway:
    def __init__(self, payloads: dict[UUID, object]) -> None:
        self.payloads = payloads
        self.calls: list[UUID] = []

    def read_bytes(self, artifact: AtomicArtifactRef, /) -> object:
        self.calls.append(artifact.artifact_id)
        return self.payloads[artifact.artifact_id]


def _ref(
    payload: bytes,
    *,
    role: str = "h3.authority",
    mime: str = "application/json",
    project_id: UUID = PROJECT_ID,
    artifact_id: UUID | None = None,
    digest: str | None = None,
    byte_size: int | None = None,
) -> AtomicArtifactRef:
    return AtomicArtifactRef(
        artifact_id=artifact_id or uuid4(),
        project_id=project_id,
        content_digest=digest or hashlib.sha256(payload).hexdigest(),
        mime_type=mime,
        byte_size=len(payload) if byte_size is None else byte_size,
        logical_role=role,
    )


def test_verified_h3_inputs_read_strict_json_once_by_unique_role() -> None:
    payload = b'{"schema_version":"fixture.v1","value":"safe"}'
    ref = _ref(payload)
    gateway = _Gateway({ref.artifact_id: payload})
    inputs = VerifiedH3ArtifactInputs(
        project_id=PROJECT_ID,
        artifact_refs=(ref,),
        gateway=gateway,
    )

    first = inputs.read_json_model("h3.authority", _Envelope)
    second = inputs.read_json_model("h3.authority", _Envelope)

    assert first == second == _Envelope(schema_version="fixture.v1", value="safe")
    assert gateway.calls == [ref.artifact_id]


def test_verified_h3_inputs_reject_duplicate_roles_and_cross_project_before_io() -> None:
    payload = b"{}"
    first = _ref(payload)
    duplicate = _ref(payload)
    foreign = _ref(payload, role="h3.foreign", project_id=uuid4())
    gateway = _Gateway(
        {
            first.artifact_id: payload,
            duplicate.artifact_id: payload,
            foreign.artifact_id: payload,
        }
    )

    with pytest.raises(H3ArtifactInputError, match="duplicate|role"):
        VerifiedH3ArtifactInputs(
            project_id=PROJECT_ID,
            artifact_refs=(first, duplicate),
            gateway=gateway,
        )
    with pytest.raises(H3ArtifactInputError, match="project"):
        VerifiedH3ArtifactInputs(
            project_id=PROJECT_ID,
            artifact_refs=(first, foreign),
            gateway=gateway,
        )

    assert gateway.calls == []


@pytest.mark.parametrize(
    ("ref_kwargs", "gateway_payload", "message"),
    [
        ({"digest": "f" * 64}, b"actual", "digest"),
        ({"byte_size": 999}, b"actual", "size"),
        ({}, "not-bytes", "bytes"),
    ],
)
def test_verified_h3_inputs_recheck_gateway_bytes_against_ref(
    ref_kwargs: dict[str, object],
    gateway_payload: object,
    message: str,
) -> None:
    payload = b"actual"
    ref = _ref(payload, mime="video/mp4", **ref_kwargs)
    inputs = VerifiedH3ArtifactInputs(
        project_id=PROJECT_ID,
        artifact_refs=(ref,),
        gateway=_Gateway({ref.artifact_id: gateway_payload}),
    )

    with pytest.raises(H3ArtifactInputError, match=message):
        inputs.read_bytes(
            "h3.authority",
            allowed_mime_types=frozenset({"video/mp4"}),
        )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":"fixture.v1","value":"C:\\\\secret\\\\x"}',
        b'{"schema_version":"fixture.v1","value":"safe","physical_path":"/tmp/x"}',
        b'{"schema_version":"fixture.v1","value":"a","value":"b"}',
    ],
)
def test_verified_h3_json_rejects_paths_unknown_fields_and_duplicate_keys(
    payload: bytes,
) -> None:
    ref = _ref(payload)
    inputs = VerifiedH3ArtifactInputs(
        project_id=PROJECT_ID,
        artifact_refs=(ref,),
        gateway=_Gateway({ref.artifact_id: payload}),
    )

    with pytest.raises(H3ArtifactInputError, match="JSON|path|duplicate|schema"):
        inputs.read_json_model("h3.authority", _Envelope)


def test_verified_h3_inputs_enforce_role_mime_and_size_bounds() -> None:
    payload = b"123456"
    ref = _ref(payload, mime="image/png")
    inputs = VerifiedH3ArtifactInputs(
        project_id=PROJECT_ID,
        artifact_refs=(ref,),
        gateway=_Gateway({ref.artifact_id: payload}),
    )

    with pytest.raises(H3ArtifactInputError, match="role"):
        inputs.read_bytes("missing", allowed_mime_types=frozenset({"image/png"}))
    with pytest.raises(H3ArtifactInputError, match="MIME"):
        inputs.read_bytes(
            "h3.authority",
            allowed_mime_types=frozenset({"video/mp4"}),
        )
    with pytest.raises(H3ArtifactInputError, match="size|large"):
        inputs.read_bytes(
            "h3.authority",
            allowed_mime_types=frozenset({"image/png"}),
            maximum_bytes=5,
        )


@pytest.mark.parametrize(
    "dangerous",
    ["../secret", r"C:\secret\x", "file:///tmp/secret"],
)
def test_verified_h3_json_rejects_deeply_percent_encoded_paths(
    dangerous: str,
) -> None:
    encoded = dangerous
    for _ in range(5):
        encoded = quote(encoded, safe="")
    payload = json.dumps(
        {"schema_version": "fixture.v1", "value": encoded},
        separators=(",", ":"),
    ).encode("utf-8")
    ref = _ref(payload)
    inputs = VerifiedH3ArtifactInputs(
        project_id=PROJECT_ID,
        artifact_refs=(ref,),
        gateway=_Gateway({ref.artifact_id: payload}),
    )

    with pytest.raises(H3ArtifactInputError, match="path|JSON"):
        inputs.read_json_model("h3.authority", _Envelope)


def test_verified_h3_json_rejects_non_finite_exponent_results() -> None:
    payload = b'{"value":1e9999}'
    ref = _ref(payload)
    inputs = VerifiedH3ArtifactInputs(
        project_id=PROJECT_ID,
        artifact_refs=(ref,),
        gateway=_Gateway({ref.artifact_id: payload}),
    )

    with pytest.raises(H3ArtifactInputError, match="JSON"):
        inputs.read_json_model("h3.authority", _FloatEnvelope)


def test_verified_h3_json_rejects_protocol_depth_before_model_validation() -> None:
    nested: dict[str, object] = {"leaf": "safe"}
    for ordinal in range(70):
        nested = {f"level_{ordinal}": nested}
    payload = json.dumps(
        {"payload": nested},
        separators=(",", ":"),
    ).encode("utf-8")
    ref = _ref(payload)
    inputs = VerifiedH3ArtifactInputs(
        project_id=PROJECT_ID,
        artifact_refs=(ref,),
        gateway=_Gateway({ref.artifact_id: payload}),
    )

    with pytest.raises(H3ArtifactInputError, match="depth|complex|JSON"):
        inputs.read_json_model("h3.authority", _NestedEnvelope)
