"""Style Spec JSON Schema Draft 2020-12 generation.

``build_style_spec_schema`` returns an independent object on every call.
``$schema`` is fixed to the official Draft 2020-12 URI, ``$id`` equals the
instance ``schema_uri``, and dumping uses canonical JSON with ``sort_keys``,
compact separators, and ``ensure_ascii=False``.
"""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from specstyle.spec.models import StyleSpecV1

_DRAFT_URI = "https://json-schema.org/draft/2020-12/schema"
_SCHEMA_ID = "schemas/style-spec-1.0.schema.json"


def build_style_spec_schema() -> dict[str, object]:
    schema: dict[str, object] = TypeAdapter(StyleSpecV1).json_schema()
    schema["$schema"] = _DRAFT_URI
    schema["$id"] = _SCHEMA_ID
    return schema


def dump_style_spec_schema() -> str:
    return json.dumps(
        build_style_spec_schema(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
