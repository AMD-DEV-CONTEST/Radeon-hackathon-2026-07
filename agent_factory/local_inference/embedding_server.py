from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.local_inference.rocm import RocmRuntimeInfo, inspect_rocm_runtime
from agent_factory.model_pool.schema import TransformersInferenceConfig
from agent_factory.model_pool.store import ModelPoolStore


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    texts: list[str] = Field(min_length=1)


@dataclass(slots=True)
class EmbeddingRuntime:
    profile_id: str
    model_id: str
    model_format: str
    model: Any
    dimensions: int
    normalize_embeddings: bool
    rocm: RocmRuntimeInfo


def create_app(profile_id: str) -> FastAPI:
    runtime: EmbeddingRuntime | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal runtime
        del app
        runtime = _load_runtime(profile_id)
        yield
        runtime = None

    app = FastAPI(title="FastAgentFactory Local Embedding", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        if runtime is None:
            raise HTTPException(status_code=503, detail="embedding model is not loaded")
        return {
            "status": "ready",
            "profile_id": runtime.profile_id,
            "model_id": runtime.model_id,
            "kind": "embedding",
            "format": runtime.model_format,
            "dimensions": runtime.dimensions,
            "rocm": runtime.rocm.payload(),
        }

    @app.post("/embed")
    async def embed(request: EmbeddingRequest) -> dict[str, Any]:
        if runtime is None:
            raise HTTPException(status_code=503, detail="embedding model is not loaded")
        if request.profile_id not in {runtime.profile_id, runtime.model_id}:
            raise HTTPException(status_code=409, detail="requested embedding profile is not loaded")
        vectors = runtime.model.encode(
            request.texts,
            normalize_embeddings=runtime.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        values = vectors.tolist()
        if any(len(item) != runtime.dimensions for item in values):
            raise HTTPException(status_code=500, detail="embedding model returned unexpected dimensions")
        return {"profile_id": runtime.profile_id, "embeddings": values}

    return app


def _load_runtime(profile_id: str) -> EmbeddingRuntime:
    rocm = inspect_rocm_runtime(require_available=True)
    store = ModelPoolStore(setup=False)
    profile = store.require_profile(profile_id)
    if profile.kind != "embedding" or profile.engine != "transformers_rocm":
        raise ValueError(f"profile {profile_id} is not a local Transformers embedding profile")
    if not profile.enabled or profile.embedding_dimensions is None:
        raise ValueError(f"embedding profile is disabled or incomplete: {profile_id}")
    artifact = store.require_artifact(profile.artifact_id)
    if not artifact.enabled:
        raise ValueError(f"embedding artifact is disabled: {artifact.artifact_id}")
    model_path = artifact.resolved_path()
    if not model_path.is_dir():
        raise ValueError(f"embedding model directory does not exist: {model_path}")
    if not isinstance(profile.inference, TransformersInferenceConfig):
        raise ValueError(f"profile {profile.profile_id} does not contain Transformers inference settings")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        str(model_path),
        device="cuda",
        trust_remote_code=profile.inference.trust_remote_code,
    )
    actual_dimensions = int(model.get_sentence_embedding_dimension())
    if actual_dimensions != profile.embedding_dimensions:
        raise ValueError(
            f"registered embedding dimensions {profile.embedding_dimensions} do not match model dimensions {actual_dimensions}"
        )
    return EmbeddingRuntime(
        profile_id=profile.profile_id,
        model_id=profile.served_model_name,
        model_format=artifact.model_format,
        model=model,
        dimensions=actual_dimensions,
        normalize_embeddings=profile.normalize_embeddings,
        rocm=rocm,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local ROCm embedding service")
    parser.add_argument("--profile-id")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    import uvicorn

    profile_id = args.profile_id or ModelPoolStore().resolve_default_profile_id("embedding")
    if not profile_id:
        raise ValueError("no enabled default embedding profile is configured in the local model pool")
    uvicorn.run(create_app(profile_id), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
