from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
from typing import Any, Callable
import zlib


class YOLOEEngine:
    """CUDA-side engine. This module itself does not import CUDA frameworks."""

    model_id = "yoloe-26s"

    def __init__(
        self,
        *,
        weight_path: str,
        device: str | int = "cuda:0",
        image_size: int = 640,
        confidence: float = 0.15,
        model_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.weight_path = str(Path(weight_path).expanduser())
        self.device = device
        self.image_size = int(image_size)
        self.confidence = float(confidence)
        self.model_version = _weight_version(self.weight_path)
        self._model_factory = model_factory
        self._model: Any = None
        self._vocabulary_hash: str | None = None
        self._vocabulary: list[str] = []
        self._loaded_at_ms: int | None = None
        self._inference_lock = threading.RLock()

    def detect(
        self,
        *,
        image_path: str,
        media_type: str,
        width: int | None,
        height: int | None,
        vocabulary: list[str],
        vocabulary_hash: str,
    ) -> dict[str, Any]:
        with self._inference_lock:
            return self._detect_serialized(
                image_path=image_path,
                media_type=media_type,
                width=width,
                height=height,
                vocabulary=vocabulary,
                vocabulary_hash=vocabulary_hash,
            )

    def _detect_serialized(
        self,
        *,
        image_path: str,
        media_type: str,
        width: int | None,
        height: int | None,
        vocabulary: list[str],
        vocabulary_hash: str,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if not vocabulary:
            raise ValueError("YOLOE vocabulary cannot be empty")
        model = self._load_model()
        if vocabulary_hash != self._vocabulary_hash:
            model.set_classes(list(vocabulary))
            self._vocabulary_hash = vocabulary_hash
            self._vocabulary = list(vocabulary)

        source_path, temporary = self._prepare_source(
            path,
            media_type=media_type,
            width=width,
            height=height,
        )
        try:
            results = model.predict(
                source=str(source_path),
                imgsz=self.image_size,
                conf=self.confidence,
                device=self.device,
                verbose=False,
            )
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if not results:
            raise RuntimeError("Ultralytics returned no result")
        detections, result_width, result_height = map_ultralytics_detections(results[0])
        return {
            "status": "ready" if detections else "ready_empty",
            "model_id": self.model_id,
            "model_version": self.model_version,
            "device": str(self.device),
            "vocabulary_hash": vocabulary_hash,
            "input_width": result_width or width,
            "input_height": result_height or height,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "detections": detections,
        }

    def health(self) -> dict[str, Any]:
        cuda = _cuda_memory()
        return {
            "status": "ready",
            "loaded": self._model is not None,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "weight_path": self.weight_path,
            "device": str(self.device),
            "vocabulary_hash": self._vocabulary_hash,
            "class_count": len(self._vocabulary),
            "loaded_at_ms": self._loaded_at_ms,
            **cuda,
        }

    def warmup(
        self,
        *,
        vocabulary: list[str],
        vocabulary_hash: str,
    ) -> dict[str, Any]:
        """Load weights, build text classes, and execute one synthetic frame."""
        handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        warmup_path = Path(handle.name)
        try:
            handle.write(_black_png(width=64, height=64))
            handle.close()
            return self.detect(
                image_path=str(warmup_path),
                media_type="image/png",
                width=64,
                height=64,
                vocabulary=vocabulary,
                vocabulary_hash=vocabulary_hash,
            )
        finally:
            try:
                handle.close()
            finally:
                warmup_path.unlink(missing_ok=True)

    def _load_model(self):
        if self._model is not None:
            return self._model
        if self._model_factory is not None:
            self._model = self._model_factory(self.weight_path)
        else:
            try:
                from ultralytics import YOLOE
            except ImportError as exc:
                raise RuntimeError(
                    "Ultralytics runtime missing; run tools/setup_object_perception_runtime.sh"
                ) from exc
            self._model = YOLOE(self.weight_path)
        self._loaded_at_ms = int(time.time() * 1000)
        return self._model

    @staticmethod
    def _prepare_source(
        path: Path,
        *,
        media_type: str,
        width: int | None,
        height: int | None,
    ) -> tuple[Path, Path | None]:
        if media_type in {"image/jpeg", "image/jpg", "image/png"}:
            return path, None
        if media_type not in {"image/nv12", "image/yuv"}:
            raise ValueError(f"unsupported image media type: {media_type}")
        if not width or not height:
            raise ValueError("NV12 inference requires width and height")
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("NV12 conversion requires numpy and opencv") from exc
        expected = width * height * 3 // 2
        raw = path.read_bytes()
        if len(raw) != expected:
            raise ValueError(f"NV12 byte size mismatch: expected {expected}, got {len(raw)}")
        frame = np.frombuffer(raw, dtype=np.uint8).reshape((height * 3 // 2, width))
        bgr = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_NV12)
        handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        handle.close()
        output = Path(handle.name)
        if not cv2.imwrite(str(output), bgr):
            output.unlink(missing_ok=True)
            raise RuntimeError("failed to convert NV12 evidence to JPEG")
        return output, output


def map_ultralytics_detections(result: Any) -> tuple[list[dict[str, Any]], int | None, int | None]:
    shape = getattr(result, "orig_shape", None)
    height = int(shape[0]) if isinstance(shape, (list, tuple)) and len(shape) >= 2 else None
    width = int(shape[1]) if isinstance(shape, (list, tuple)) and len(shape) >= 2 else None
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return [], width, height
    boxes_xyxy = _tensor_list(getattr(boxes, "xyxy", []))
    confidences = _tensor_list(getattr(boxes, "conf", []))
    class_ids = [int(item) for item in _tensor_list(getattr(boxes, "cls", []))]
    names = getattr(result, "names", {}) or {}
    detections = []
    for bbox, confidence, class_id in zip(boxes_xyxy, confidences, class_ids):
        if isinstance(names, dict):
            label = str(names.get(class_id, class_id))
        elif isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
            label = str(names[class_id])
        else:
            label = str(class_id)
        detections.append(
            {
                "label": label,
                "confidence": float(confidence),
                "bbox_xyxy": [float(item) for item in bbox],
                "attributes": {"class_id": class_id},
            }
        )
    return detections, width, height


def _tensor_list(value: Any) -> list[Any]:
    for method_name in ("detach", "cpu"):
        method = getattr(value, method_name, None)
        if callable(method):
            value = method()
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()
    return list(value or [])


def _weight_version(path_value: str) -> str:
    override = os.getenv("OBJECT_PERCEPTION_MODEL_VERSION")
    if override:
        return override
    path = Path(path_value)
    if not path.is_file():
        return path.name
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cuda_memory() -> dict[str, Any]:
    try:
        import torch
    except ImportError:
        return {"cuda_available": False, "cuda_allocated_mib": None, "cuda_reserved_mib": None}
    available = bool(torch.cuda.is_available())
    if not available:
        return {"cuda_available": False, "cuda_allocated_mib": None, "cuda_reserved_mib": None}
    return {
        "cuda_available": True,
        "cuda_allocated_mib": round(torch.cuda.memory_allocated() / 1024 / 1024, 3),
        "cuda_reserved_mib": round(torch.cuda.memory_reserved() / 1024 / 1024, 3),
    }


def _black_png(*, width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind)
        crc = zlib.crc32(payload, crc)
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\0" + b"\0" * (width * 3) for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(
        b"IDAT", zlib.compress(scanlines)
    ) + chunk(b"IEND", b"")
