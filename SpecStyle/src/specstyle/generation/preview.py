"""Preview backend + versioned user_strength → profile parameter mapping."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.errors import DomainError
from specstyle.generation.pipeline_factory import PipelineGraph
from specstyle.generation.protocols import GeneratedArtifact, GenerationBackend
from specstyle.generation.requests import GenerationRequest


@dataclass(frozen=True, slots=True)
class StrengthMapping:
    mapping_version: str
    preview_steps: int
    production_steps: int
    preview_guidance: float
    production_guidance: float

    def __post_init__(self) -> None:
        if type(self.mapping_version) is not str or not self.mapping_version:
            raise DomainError("invalid strength mapping")
        for name in ("preview_steps", "production_steps"):
            v = getattr(self, name)
            if type(v) is not int or isinstance(v, bool) or v < 1:
                raise DomainError("invalid strength mapping")
        for name in ("preview_guidance", "production_guidance"):
            v = getattr(self, name)
            if type(v) is not float or v != v:
                raise DomainError("invalid strength mapping")


def map_user_strength(
    user_strength: float, mapping: StrengthMapping, profile: str
) -> dict[str, float | int]:
    if type(user_strength) is not float or not 0.0 <= user_strength <= 1.0:
        raise DomainError("invalid user strength")
    if type(mapping) is not StrengthMapping:
        raise DomainError("invalid mapping")
    if profile not in ("preview", "production"):
        raise DomainError("invalid profile")
    # Monotone: higher strength → higher ip scale; steps fixed per profile.
    ip = 0.3 + 0.6 * user_strength
    if profile == "preview":
        return {
            "steps": mapping.preview_steps,
            "guidance_scale": mapping.preview_guidance,
            "ip_adapter_scale": ip,
            "mapping_version": mapping.mapping_version,
        }
    return {
        "steps": mapping.production_steps,
        "guidance_scale": mapping.production_guidance,
        "ip_adapter_scale": ip,
        "mapping_version": mapping.mapping_version,
    }


@dataclass(slots=True)
class PreviewBackend:
    """Thin wrapper: forces generation_profile preview and injects mapping pin."""

    graph: PipelineGraph
    backend: GenerationBackend
    mapping: StrengthMapping

    def generate(self, request: GenerationRequest) -> GeneratedArtifact:
        if self.graph.profile != "preview":
            raise DomainError("preview backend requires preview graph")
        if request.generation_profile != "preview":
            raise DomainError("preview backend requires preview request")
        # Mapping version must match Spec pin when present (1.1).
        source = request.compiled_spec.source_spec
        if hasattr(source.style, "strength_mapping_version"):
            if source.style.strength_mapping_version != self.mapping.mapping_version:
                if source.style.strength_mapping_version != "legacy-unversioned":
                    raise DomainError("strength mapping version mismatch")
        return self.backend.generate(request)
