"""Deterministic fake generation backend for CPU contract tests."""

from __future__ import annotations

import hashlib
import sys
import threading
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.identifiers import ArtifactId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.protocols import GeneratedArtifact
from specstyle.generation.requests import GenerationRequest
from specstyle.observability.hashing import hash_bytes


@dataclass(slots=True)
class FakeBackend:
    """Deterministic CPU backend that renders each attempt once per instance."""

    _lock: threading.Lock = field(init=False, repr=False)
    _seen_attempts: set[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._seen_attempts = set()

    def _render(self, request: GenerationRequest) -> bytes:
        digest = hashlib.sha256(
            request.generation_fingerprint.value.encode("ascii")
        ).digest()
        image = Image.new("RGB", request.graph.resolution, tuple(digest[:3]))
        try:
            output = BytesIO()
            image.save(output, format="PNG", optimize=False, compress_level=9)
            return output.getvalue()
        finally:
            if sys.exc_info()[0] is None:
                try:
                    image.close()
                except Exception as error:
                    raise InfrastructureError("image processing failed") from error
            else:
                try:
                    image.close()
                except Exception:
                    pass

    def generate(self, request: GenerationRequest) -> GeneratedArtifact:
        with self._lock:
            if request.attempt_id.value in self._seen_attempts:
                raise DomainError("attempt already claimed")
            self._seen_attempts.add(request.attempt_id.value)
        content = self._render(request)
        artifact_id = ArtifactId(f"artifact-{request.request_hash.value[:64]}")
        ref = ArtifactRef(artifact_id, hash_bytes(content))
        return GeneratedArtifact(
            ref, content, request.request_hash, request.generation_fingerprint
        )
