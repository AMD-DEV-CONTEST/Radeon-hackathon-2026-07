"""Boundaries for generation backends and control input builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.identifiers import ArtifactId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.preprocess import PreparedImage, _validate_output_png
from specstyle.generation.requests import GenerationRequest, PreparedControlInput
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import CompiledExecutionGraph


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    ref: ArtifactRef
    content: bytes
    request_hash: Sha256
    generation_fingerprint: Sha256

    def __post_init__(self) -> None:
        if type(self.ref) is not ArtifactRef or type(self.content) is not bytes:
            raise DomainError("invalid generated artifact")
        if (
            type(self.ref.artifact_id) is not ArtifactId
            or type(self.ref.sha256) is not Sha256
        ):
            raise DomainError("invalid generated artifact")
        ref = ArtifactRef(
            ArtifactId(self.ref.artifact_id.value), Sha256(self.ref.sha256.value)
        )
        request_hash = (
            Sha256(self.request_hash.value)
            if type(self.request_hash) is Sha256
            else None
        )
        fingerprint = (
            Sha256(self.generation_fingerprint.value)
            if type(self.generation_fingerprint) is Sha256
            else None
        )
        if (
            request_hash is None
            or fingerprint is None
            or hash_bytes(self.content) != ref.sha256
        ):
            raise DomainError("invalid generated artifact")
        object.__setattr__(self, "ref", ref)
        object.__setattr__(self, "request_hash", request_hash)
        object.__setattr__(self, "generation_fingerprint", fingerprint)


class GenerationBackend(Protocol):
    def generate(self, request: GenerationRequest) -> GeneratedArtifact: ...


class ControlInputBuilder(Protocol):
    def build(
        self, source: PreparedImage, graph: CompiledExecutionGraph
    ) -> PreparedControlInput: ...


def _contract_failure() -> InfrastructureError:
    return InfrastructureError("generation contract violation")


def _rebuild_prepared_image(value: object) -> PreparedImage:
    if type(value) is not PreparedImage:
        raise _contract_failure()
    rebuilt = PreparedImage(value.source, value.content, value.snapshot)
    if rebuilt != value:
        raise _contract_failure()
    return rebuilt


def _rebuild_request(value: object) -> GenerationRequest:
    if type(value) is not GenerationRequest:
        raise _contract_failure()
    rebuilt = GenerationRequest(
        value.job_id,
        value.attempt_id,
        value.parent_attempt_id,
        value.compiled_spec,
        value.generation_profile,
        value.output_profile,
        value.source,
        value.style_references,
        value.prompt,
        value.control_input,
        value.variation_index,
        value.environment_hash,
        value.execution_parameters,
    )
    if rebuilt != value:
        raise _contract_failure()
    return rebuilt


def _rebuild_artifact(value: object) -> GeneratedArtifact:
    if type(value) is not GeneratedArtifact:
        raise _contract_failure()
    if type(value.ref) is not ArtifactRef:
        raise _contract_failure()
    ref = ArtifactRef(
        ArtifactId(value.ref.artifact_id.value), Sha256(value.ref.sha256.value)
    )
    rebuilt = GeneratedArtifact(
        ref,
        value.content,
        Sha256(value.request_hash.value),
        Sha256(value.generation_fingerprint.value),
    )
    if rebuilt != value:
        raise _contract_failure()
    return rebuilt


def build_control_input(
    builder: ControlInputBuilder, source: PreparedImage, graph: CompiledExecutionGraph
) -> PreparedControlInput:
    try:
        source = _rebuild_prepared_image(source)
        if type(graph) is not CompiledExecutionGraph:
            raise _contract_failure()
    except (DomainError, InfrastructureError):
        raise _contract_failure() from None
    except Exception:
        raise _contract_failure() from None
    try:
        result = builder.build(source, graph)
    except (DomainError, InfrastructureError):
        raise
    except Exception as error:
        raise InfrastructureError("control input builder failure") from error
    try:
        if type(result) is not PreparedControlInput:
            raise _contract_failure()
        image = _rebuild_prepared_image(result.image)
        rebuilt = PreparedControlInput(result.kind, image)
        if (
            rebuilt != result
            or rebuilt.source != source.source
            or rebuilt.kind != graph.controlnet.controlnet_type
            or (rebuilt.image.width, rebuilt.image.height) != graph.resolution
        ):
            raise _contract_failure()
        return rebuilt
    except Exception:
        raise _contract_failure() from None


def run_generation(
    backend: GenerationBackend, request: GenerationRequest
) -> GeneratedArtifact:
    try:
        request = _rebuild_request(request)
    except Exception:
        raise _contract_failure() from None
    try:
        result = backend.generate(request)
    except (DomainError, InfrastructureError):
        raise
    except Exception as error:
        raise InfrastructureError("generation backend failure") from error
    try:
        rebuilt = _rebuild_artifact(result)
        if (
            rebuilt.request_hash != request.request_hash
            or rebuilt.generation_fingerprint != request.generation_fingerprint
            or hash_bytes(rebuilt.content) != rebuilt.ref.sha256
        ):
            raise _contract_failure()
        _validate_output_png(rebuilt.content, request.graph.resolution)
        return rebuilt
    except Exception:
        raise _contract_failure() from None
