from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from agent_factory.local_inference.config import load_local_embedding_endpoint
from agent_factory.local_inference.embedding import LocalEmbeddingModel


@dataclass(frozen=True, slots=True)
class EmbeddingModelSettings:
    profile_id: str | None
    model: str | None
    dims: int | None
    engine: str = "transformers_rocm"
    normalize_embeddings: bool = True
    timeout_seconds: float | None = None

    @property
    def available(self) -> bool:
        return bool(
            self.profile_id
            and self.model
            and self.dims
            and self.engine in {"transformers_rocm", "external"}
        )


def get_embedding_model() -> Embeddings | None:
    return _get_embedding_model()


def get_embedding_model_settings() -> EmbeddingModelSettings:
    return _embedding_settings()


def reset_embedding_model() -> None:
    _get_embedding_model.cache_clear()


@lru_cache(maxsize=1)
def _get_embedding_model() -> Embeddings | None:
    settings = _embedding_settings()
    if not settings.available:
        return None
    endpoint = load_local_embedding_endpoint(timeout_seconds=settings.timeout_seconds)
    return LocalEmbeddingModel(
        profile_id=str(settings.model),
        endpoint=endpoint,
        dimensions=int(settings.dims),
    )


def _embedding_settings() -> EmbeddingModelSettings:
    from agent_factory.model_pool.store import ModelPoolStore

    profile_id = str(ModelPoolStore().resolve_default_profile_id("embedding") or "")
    if not profile_id:
        return EmbeddingModelSettings(profile_id=None, model=None, dims=None)
    profile = ModelPoolStore().require_profile(profile_id)
    if profile.kind != "embedding":
        raise ValueError(f"local model profile {profile_id} is not an embedding profile")
    if not profile.enabled:
        raise ValueError(f"local embedding profile is disabled: {profile_id}")
    artifact = ModelPoolStore().require_artifact(profile.artifact_id)
    if not artifact.enabled:
        raise ValueError(f"local embedding artifact is disabled: {artifact.artifact_id}")
    return EmbeddingModelSettings(
        profile_id=profile.profile_id,
        model=profile.served_model_name,
        dims=profile.embedding_dimensions,
        engine=profile.engine,
        normalize_embeddings=profile.normalize_embeddings,
        timeout_seconds=profile.limits.timeout_seconds,
    )
