"""Optional real model loaders for the RAM-aware registry."""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from app.runtime.artifact_store import ArtifactStore


Loader = Callable[[], dict[str, Any]]


def _missing(name: str, reason: str, artifact: dict | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "unavailable",
        "reason": reason,
        "artifact": artifact,
        "loaded_at": time.time(),
    }


def ocr_mobile_loader(store: ArtifactStore) -> Loader:
    """Load ONNX OCR artifacts first; fall back to PaddleOCR if installed."""

    def load() -> dict[str, Any]:
        artifact = store.find("ocr-mobile")
        onnx_paths = [path for path in store.find_all("ocr-mobile") if path.suffix.lower() == ".onnx"]
        if onnx_paths:
            try:
                import onnxruntime as ort
            except Exception as exc:
                return _missing(
                    "ocr-mobile",
                    f"onnxruntime not installed or failed to import: {exc}",
                    artifact.to_dict() if artifact else None,
                )

            sessions = {
                path.name: ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
                for path in onnx_paths
            }
            return {
                "name": "ocr-mobile",
                "status": "loaded",
                "backend": "onnxruntime",
                "artifacts": [
                    {
                        "path": str(path),
                        "size_mb": round(path.stat().st_size / (1024**2), 2),
                    }
                    for path in onnx_paths
                ],
                "model": sessions,
                "loaded_at": time.time(),
            }

        try:
            from paddleocr import PaddleOCR
        except Exception as exc:
            return _missing(
                "ocr-mobile",
                f"paddleocr not installed or failed to import: {exc}",
                artifact.to_dict() if artifact else None,
            )

        model = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
        return {
            "name": "ocr-mobile",
            "status": "loaded",
            "backend": "paddleocr",
            "artifact": artifact.to_dict() if artifact else None,
            "model": model,
            "loaded_at": time.time(),
        }

    return load


def ui_detector_loader(store: ArtifactStore) -> Loader:
    """Load an INT8 ONNX UI detector exported by the cloud pipeline."""

    def load() -> dict[str, Any]:
        artifact = store.find("ui-detector-int8")
        if artifact is None:
            return _missing(
                "ui-detector-int8",
                "no ONNX artifact found in ai_pc_operator/data/models or hackathon outputs",
            )

        try:
            import onnxruntime as ort
        except Exception as exc:
            return _missing(
                "ui-detector-int8",
                f"onnxruntime not installed or failed to import: {exc}",
                artifact.to_dict(),
            )

        session = ort.InferenceSession(
            artifact.path,
            providers=["CPUExecutionProvider"],
        )
        return {
            "name": "ui-detector-int8",
            "status": "loaded",
            "backend": "onnxruntime",
            "artifact": artifact.to_dict(),
            "model": session,
            "loaded_at": time.time(),
        }

    return load


def qwen_gguf_loader(store: ArtifactStore) -> Loader:
    """Load a local Qwen GGUF through llama.cpp bindings when available."""

    def load() -> dict[str, Any]:
        artifact = store.find("qwen-1.5b-q4")
        if artifact is None:
            return _missing(
                "qwen-1.5b-q4",
                "no GGUF artifact found; place Qwen Q4 GGUF under ai_pc_operator/data/models",
            )

        try:
            from llama_cpp import Llama
        except Exception as exc:
            return _missing(
                "qwen-1.5b-q4",
                f"llama-cpp-python not installed or failed to import: {exc}",
                artifact.to_dict(),
            )

        n_ctx = int(os.environ.get("SCREEN_AI_LLM_CTX", "768"))
        n_threads = int(os.environ.get("SCREEN_AI_LLM_THREADS", "2"))
        model = Llama(
            model_path=artifact.path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=0,
            use_mmap=os.environ.get("SCREEN_AI_MMAP", "1") != "0",
            use_mlock=False,
            n_batch=128,
            verbose=False,
        )
        return {
            "name": "qwen-1.5b-q4",
            "status": "loaded",
            "backend": "llama.cpp",
            "artifact": artifact.to_dict(),
            "mmap": os.environ.get("SCREEN_AI_MMAP", "1") != "0",
            "n_ctx": n_ctx,
            "n_threads": n_threads,
            "model": model,
            "loaded_at": time.time(),
        }

    return load


def vault_crypto_loader(_: ArtifactStore) -> Loader:
    """Warm the crypto modules used by the vault."""

    def load() -> dict[str, Any]:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
            try:
                from cryptography.hazmat.primitives.kdf.argon2 import Argon2id  # noqa: F401
                kdf = "argon2id"
            except Exception:
                kdf = "pbkdf2-fallback"
        except Exception as exc:
            return _missing("vault-crypto", f"cryptography import failed: {exc}")

        return {
            "name": "vault-crypto",
            "status": "loaded",
            "backend": "cryptography",
            "kdf": kdf,
            "loaded_at": time.time(),
        }

    return load


def browser_warmup_loader(_: ArtifactStore) -> Loader:
    """Warm Playwright imports without launching a browser window."""

    def load() -> dict[str, Any]:
        try:
            import playwright.async_api  # noqa: F401
        except Exception as exc:
            return _missing("browser-warmup", f"playwright import failed: {exc}")

        return {
            "name": "browser-warmup",
            "status": "loaded",
            "backend": "playwright",
            "loaded_at": time.time(),
        }

    return load
