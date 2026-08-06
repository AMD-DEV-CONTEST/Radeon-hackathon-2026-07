import hashlib
import math
import os
import random
import uuid
from pathlib import Path
from typing import List
from abc import ABC, abstractmethod
import requests
from app.config import get_runtime_path

from services.embedding_runtime import (
    BgeM3OnnxRuntime,
    DEFAULT_MANIFEST_PATH,
    EmbeddingRuntimeStatus,
    EmbeddingRuntimeUnavailable,
    load_bge_m3_manifest,
)

VECTOR_DIMS = 1024  # bge-m3
DEFAULT_EMBEDDING_LOAD_TIMEOUT_SECONDS = 45.0
DEFAULT_EMBEDDING_INFER_TIMEOUT_SECONDS = 60.0


def _bounded_timeout_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default
    return max(5.0, min(value, 600.0))

class EmbeddingProvider(ABC):
    is_aetherdb_local = False

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        pass
    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        pass
    @abstractmethod
    def dims(self) -> int:
        pass

    @abstractmethod
    def status(self) -> EmbeddingRuntimeStatus:
        pass

class MockEmbeddingProvider(EmbeddingProvider):
    is_aetherdb_local = True

    def __init__(self, dims: int = VECTOR_DIMS):
        self._dims = dims
    def embed(self, text: str) -> List[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest(), "big")
        r = random.Random(seed)
        vec = [r.random() - 0.5 for _ in range(self._dims)]
        mag = math.sqrt(sum(x*x for x in vec))
        return [x/mag for x in vec]
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]
    def dims(self) -> int:
        return self._dims
    def status(self) -> EmbeddingRuntimeStatus:
        return EmbeddingRuntimeStatus(True, "test/mock", "test-only", self._dims, "MockExecutionProvider")


class UnavailableEmbeddingProvider(EmbeddingProvider):
    is_aetherdb_local = True

    def __init__(self, model_id: str, revision: str, dims: int, detail: str):
        self.model_id = model_id
        self.revision = revision
        self._dims = dims
        self.detail = detail

    def embed(self, text: str) -> List[float]:
        raise EmbeddingRuntimeUnavailable(self.detail)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        raise EmbeddingRuntimeUnavailable(self.detail)

    def dims(self) -> int:
        return self._dims

    def status(self) -> EmbeddingRuntimeStatus:
        return EmbeddingRuntimeStatus(False, self.model_id, self.revision, self._dims, None, self.detail)


class BgeM3EmbeddingProvider(EmbeddingProvider):
    is_aetherdb_local = True

    def __init__(self, runtime: BgeM3OnnxRuntime):
        self.runtime = runtime

    def embed(self, text: str) -> List[float]:
        return self.runtime.embed_batch([text]).vectors[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self.runtime.embed_batch(texts).vectors

    def dims(self) -> int:
        return self.runtime.status().dimensions

    def status(self) -> EmbeddingRuntimeStatus:
        return self.runtime.status()


class WorkerEmbeddingProvider(EmbeddingProvider):
    """Lazy client for the isolated, trusted BGE-M3 native Worker."""

    is_aetherdb_local = True

    def __init__(self, manifest, manager=None):
        self.manifest = manifest
        self._manager = manager
        self._last_execution_provider = None
        self._last_detail = "BGE-M3 native Worker is cold"

    def _worker_manager(self):
        if self._manager is None:
            from services.model_runtime.manager import get_worker_manager

            self._manager = get_worker_manager()
        return self._manager

    def embed(self, text: str) -> List[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        accelerator = os.environ.get("AETHERDB_EMBEDDING_ACCELERATOR", "auto").strip().lower()
        backend = {
            "auto": "auto",
            "rocm": "rocm_migraphx",
            "migraphx": "rocm_migraphx",
            "cuda": "cuda",
            "cpu": "cpu",
        }.get(accelerator)
        if backend is None:
            raise EmbeddingRuntimeUnavailable(
                f"Unsupported embedding accelerator: {accelerator}"
            )
        from services.model_runtime.core_service import get_core_embedding_service

        core_service = get_core_embedding_service()
        core_service.before_request()
        load_timeout = _bounded_timeout_env(
            "AETHERDB_EMBEDDING_LOAD_TIMEOUT_SECONDS",
            DEFAULT_EMBEDDING_LOAD_TIMEOUT_SECONDS,
        )
        infer_timeout = _bounded_timeout_env(
            "AETHERDB_EMBEDDING_INFER_TIMEOUT_SECONDS",
            DEFAULT_EMBEDDING_INFER_TIMEOUT_SECONDS,
        )
        try:
            execution = self._worker_manager().execute(
                "aetherdb.bge-m3",
                task_id=f"embedding:{uuid.uuid4().hex}",
                operation="embedding",
                payload={"texts": texts},
                requested_backend=backend,
                priority=60,
                load_timeout=load_timeout,
                timeout=infer_timeout,
            )
        except Exception as exc:
            core_service.record_failure(exc)
            message = getattr(
                exc,
                "safe_message",
                f"BGE-M3 native Worker failed: {type(exc).__name__}",
            )
            raise EmbeddingRuntimeUnavailable(message) from exc
        result = execution["result"]
        vectors = result.get("vectors")
        if (
            not isinstance(vectors, list)
            or len(vectors) != len(texts)
            or any(len(vector) != self.manifest.dimensions for vector in vectors)
        ):
            raise EmbeddingRuntimeUnavailable(
                "BGE-M3 Worker returned an invalid vector result"
            )
        self._last_execution_provider = result.get("execution_provider")
        self._last_detail = ""
        core_service.record_execution(result)
        return vectors

    def record_execution(self, result: dict) -> None:
        self._last_execution_provider = result.get("execution_provider")
        self._last_detail = ""

    def dims(self) -> int:
        return self.manifest.dimensions

    def status(self) -> EmbeddingRuntimeStatus:
        return EmbeddingRuntimeStatus(
            True,
            self.manifest.model_id,
            self.manifest.revision,
            self.manifest.dimensions,
            self._last_execution_provider,
            self._last_detail,
        )

class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(self, base_url: str = 'http://localhost:11434', model: str = 'bge-m3'):
        self.base_url = base_url
        self.model = model
        self._dims = VECTOR_DIMS
    def embed(self, text: str) -> List[float]:
        resp = requests.post(f'{self.base_url}/api/embeddings', json={'model': self.model, 'prompt': text}, timeout=30)
        resp.raise_for_status()
        return resp.json()['embedding']
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(text) for text in texts]
    def dims(self) -> int:
        return self._dims
    def status(self) -> EmbeddingRuntimeStatus:
        return EmbeddingRuntimeStatus(True, self.model, "external", self._dims, "Ollama")


def create_embedding_provider(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    model_root: Path | None = None,
) -> EmbeddingProvider:
    manifest = load_bge_m3_manifest(manifest_path)
    mode = os.environ.get("AETHERDB_EMBEDDING_PROVIDER", "bge-m3").strip().lower()
    environment = os.environ.get("AETHERDB_ENV", "production").strip().lower()

    if mode == "mock":
        if environment in {"test", "testing"}:
            return MockEmbeddingProvider(manifest.dimensions)
        return UnavailableEmbeddingProvider(
            manifest.model_id,
            manifest.revision,
            manifest.dimensions,
            "Mock embeddings are disabled outside the explicit test environment",
        )

    if mode != "bge-m3":
        return UnavailableEmbeddingProvider(
            manifest.model_id,
            manifest.revision,
            manifest.dimensions,
            f"Unsupported embedding provider mode: {mode}",
        )

    root = model_root or Path(
        os.environ.get(
            "AETHERDB_MODEL_ROOT",
            str(get_runtime_path("app_data", "models", "bge-m3")),
        )
    )
    missing = manifest.missing_artifacts(root)
    if missing:
        return UnavailableEmbeddingProvider(
            manifest.model_id,
            manifest.revision,
            manifest.dimensions,
            f"BGE-M3 model artifacts are missing ({len(missing)} files)",
        )

    if not manifest.verification_record_is_current(root):
        return UnavailableEmbeddingProvider(
            manifest.model_id,
            manifest.revision,
            manifest.dimensions,
            "BGE-M3 model artifacts have not passed local checksum verification",
        )
    return WorkerEmbeddingProvider(manifest)
