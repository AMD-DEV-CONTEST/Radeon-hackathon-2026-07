import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Sequence, Tuple

from services.embedding_runtime.contracts import (
    EmbeddingBatchResult,
    EmbeddingRuntimeStatus,
    EmbeddingRuntimeUnavailable,
)
from services.embedding_runtime.manifest import BgeM3Manifest, load_bge_m3_manifest


_PROVIDER_ALIASES = {
    "auto": None,
    "rocm": "MIGraphXExecutionProvider",
    "migraphx": "MIGraphXExecutionProvider",
    "cuda": "CUDAExecutionProvider",
    "cpu": "CPUExecutionProvider",
}


def select_execution_providers(
    available: Iterable[str],
    preference: Sequence[str],
    requested: str = "auto",
) -> Tuple[str, ...]:
    available_set = set(available)
    requested_name = requested.strip().lower()
    if requested_name not in _PROVIDER_ALIASES:
        raise EmbeddingRuntimeUnavailable(f"Unsupported embedding accelerator: {requested}")

    explicit_provider = _PROVIDER_ALIASES[requested_name]
    if explicit_provider is not None:
        if explicit_provider not in available_set:
            raise EmbeddingRuntimeUnavailable(
                f"Requested execution provider is unavailable: {explicit_provider}"
            )
        selected = explicit_provider
    else:
        selected = next((item for item in preference if item in available_set), None)
        if selected is None:
            raise EmbeddingRuntimeUnavailable("No supported ONNX Runtime execution provider is available")

    providers = [selected]
    if selected != "CPUExecutionProvider" and "CPUExecutionProvider" in available_set:
        providers.append("CPUExecutionProvider")
    return tuple(providers)


class BgeM3OnnxRuntime:
    def __init__(
        self,
        model_root: Path,
        manifest: BgeM3Manifest | None = None,
        batch_size: int = 8,
        accelerator: str | None = None,
        ort_module: Any = None,
        numpy_module: Any = None,
        tokenizer_class: Any = None,
    ):
        self.manifest = manifest or load_bge_m3_manifest()
        self.model_root = Path(model_root)
        self.batch_size = max(1, batch_size)
        self._lock = threading.RLock()

        missing = self.manifest.missing_artifacts(self.model_root)
        if missing:
            raise EmbeddingRuntimeUnavailable(
                f"BGE-M3 model artifacts are missing ({len(missing)} files)"
            )
        if not self.manifest.verification_record_is_current(self.model_root):
            raise EmbeddingRuntimeUnavailable(
                "BGE-M3 model artifacts have not passed local checksum verification"
            )

        try:
            if ort_module is None:
                import onnxruntime as ort_module
            if numpy_module is None:
                import numpy as numpy_module
            if tokenizer_class is None:
                from tokenizers import Tokenizer as tokenizer_class
        except ImportError as exc:
            raise EmbeddingRuntimeUnavailable(
                f"Embedding runtime dependency is unavailable: {exc.name}"
            ) from exc

        self._ort = ort_module
        self._np = numpy_module
        accelerator = accelerator or os.environ.get("AETHERDB_EMBEDDING_ACCELERATOR", "auto")
        providers = select_execution_providers(
            self._ort.get_available_providers(),
            self.manifest.provider_preference,
            accelerator,
        )
        self._requested_providers = providers
        self._status_detail = ""

        model_path = self.model_root / "onnx" / "model.onnx"
        self._session = self._create_session(model_path, providers, accelerator)
        active_providers = tuple(self._session.get_providers())
        self._execution_provider = active_providers[0] if active_providers else providers[0]
        self._input_names = {item.name for item in self._session.get_inputs()}
        if not {"input_ids", "attention_mask"}.issubset(self._input_names):
            raise EmbeddingRuntimeUnavailable("BGE-M3 ONNX inputs are incompatible")

        tokenizer_path = self.model_root / "onnx" / "tokenizer.json"
        self._tokenizer = tokenizer_class.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=self.manifest.max_tokens)
        self._tokenizer.enable_padding(pad_id=1, pad_token="<pad>")

    def _create_session(self, model_path: Path, providers: Tuple[str, ...], accelerator: str):
        try:
            return self._ort.InferenceSession(str(model_path), providers=list(providers))
        except Exception as exc:
            explicit = accelerator.strip().lower() != "auto"
            can_fallback = "CPUExecutionProvider" in self._ort.get_available_providers()
            if explicit or providers[0] == "CPUExecutionProvider" or not can_fallback:
                raise EmbeddingRuntimeUnavailable(
                    f"Failed to initialize ONNX execution provider: {providers[0]}"
                ) from exc
            self._status_detail = f"{providers[0]} initialization failed; using CPU fallback"
            return self._ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )

    def status(self) -> EmbeddingRuntimeStatus:
        return EmbeddingRuntimeStatus(
            available=True,
            model_id=self.manifest.model_id,
            revision=self.manifest.revision,
            dimensions=self.manifest.dimensions,
            execution_provider=self._execution_provider,
            detail=self._status_detail,
        )

    def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatchResult:
        if not texts:
            return EmbeddingBatchResult(
                vectors=[],
                model_id=self.manifest.model_id,
                revision=self.manifest.revision,
                dimensions=self.manifest.dimensions,
                execution_provider=self._execution_provider,
                normalized=True,
                elapsed_ms=0.0,
            )
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding input texts must be non-empty strings")

        started = time.perf_counter()
        batches = []
        with self._lock:
            for offset in range(0, len(texts), self.batch_size):
                batches.append(self._embed_chunk(texts[offset:offset + self.batch_size]))
        dense = self._np.concatenate(batches, axis=0)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return EmbeddingBatchResult(
            vectors=dense.astype(self._np.float32).tolist(),
            model_id=self.manifest.model_id,
            revision=self.manifest.revision,
            dimensions=self.manifest.dimensions,
            execution_provider=self._execution_provider,
            normalized=True,
            elapsed_ms=elapsed_ms,
        )

    def _embed_chunk(self, texts: Sequence[str]):
        encodings = self._tokenizer.encode_batch(list(texts))
        input_ids = self._np.asarray([item.ids for item in encodings], dtype=self._np.int64)
        attention_mask = self._np.asarray(
            [item.attention_mask for item in encodings],
            dtype=self._np.int64,
        )
        feeds = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = self._np.asarray(
                [item.type_ids for item in encodings],
                dtype=self._np.int64,
            )

        outputs = self._session.run(None, feeds)
        if not outputs:
            raise EmbeddingRuntimeUnavailable("BGE-M3 ONNX runtime returned no outputs")
        hidden = self._np.asarray(outputs[0])
        if hidden.ndim == 3:
            dense = hidden[:, 0, :]
        elif hidden.ndim == 2:
            dense = hidden
        else:
            raise EmbeddingRuntimeUnavailable("BGE-M3 ONNX output rank is incompatible")
        if dense.shape[1] != self.manifest.dimensions:
            raise EmbeddingRuntimeUnavailable("BGE-M3 ONNX output dimension is incompatible")

        norms = self._np.linalg.norm(dense, axis=1, keepdims=True)
        if self._np.any(norms <= 0):
            raise EmbeddingRuntimeUnavailable("BGE-M3 ONNX runtime returned a zero vector")
        return dense / norms
