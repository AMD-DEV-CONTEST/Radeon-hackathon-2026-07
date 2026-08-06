from __future__ import annotations

from hashlib import sha256
from uuid import uuid4


SOURCE_ID_PREFIX = "source"


def new_source_id() -> str:
    return f"{SOURCE_ID_PREFIX}_{uuid4().hex}"


def stable_source_id(identity: str) -> str:
    digest = sha256(str(identity).encode("utf-8")).hexdigest()[:24]
    return f"{SOURCE_ID_PREFIX}_{digest}"
