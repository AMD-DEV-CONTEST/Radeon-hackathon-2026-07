from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from glass_gateway.external_services.contracts import (
    CONTRACT_VERSION,
    DEFAULT_MAX_IMAGE_BYTES,
)
from glass_gateway.external_services.media import (
    EncodedMedia,
    IMAGE_MEDIA_TYPES,
    materialize_media,
)

from .yoloe_engine import YOLOEEngine


class DetectionRequest(BaseModel):
    job_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    media: EncodedMedia
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    vocabulary: list[str] = Field(min_length=1, max_length=120)
    vocabulary_hash: str = Field(min_length=1)


class WorkerMetrics:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests = 0
        self.errors = 0
        self.queue_depth = 0
        self.queue_high_water = 0
        self.latencies: list[float] = []

    def begin(self) -> None:
        with self.lock:
            self.requests += 1
            self.queue_depth += 1
            self.queue_high_water = max(self.queue_high_water, self.queue_depth)

    def finish(self, *, latency_ms: float | None, error: bool) -> None:
        with self.lock:
            self.queue_depth = max(0, self.queue_depth - 1)
            self.errors += int(error)
            if latency_ms is not None:
                self.latencies.append(float(latency_ms))
                self.latencies = self.latencies[-5000:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            values = sorted(self.latencies)
            return {
                "requests": self.requests,
                "errors": self.errors,
                "queue_depth": self.queue_depth,
                "queue_high_water": self.queue_high_water,
                "p50_latency_ms": _percentile(values, 0.50),
                "p95_latency_ms": _percentile(values, 0.95),
            }


def create_worker_app(engine: YOLOEEngine | Any | None = None) -> FastAPI:
    warmup_enabled = engine is None and os.getenv("OBJECT_PERCEPTION_WARMUP", "1") != "0"
    worker_engine = engine or YOLOEEngine(
        weight_path=os.getenv(
            "OBJECT_PERCEPTION_WEIGHT_PATH",
            str(Path(__file__).resolve().parents[3] / ".runtime/models/object-perception/weights/yoloe-26s-seg.pt"),
        ),
        device=os.getenv("OBJECT_PERCEPTION_DEVICE", "cuda:0"),
        image_size=int(os.getenv("OBJECT_PERCEPTION_IMAGE_SIZE", "640")),
        confidence=float(os.getenv("OBJECT_PERCEPTION_CONFIDENCE", "0.15")),
    )
    metrics = WorkerMetrics()
    startup: dict[str, Any] = {"status": "starting" if warmup_enabled else "ready"}
    media_root = Path(
        os.getenv(
            "OBJECT_PERCEPTION_MEDIA_TEMP_DIR",
            "/tmp/beaver-object-perception",
        )
    )
    max_media_bytes = int(
        os.getenv("OBJECT_PERCEPTION_MAX_MEDIA_BYTES", str(DEFAULT_MAX_IMAGE_BYTES))
    )
    api_key = os.getenv("OBJECT_PERCEPTION_API_KEY") or os.getenv(
        "EXTERNAL_SERVICE_API_KEY", ""
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if warmup_enabled:
            try:
                vocabulary_path = Path(
                    os.getenv(
                        "OBJECT_PERCEPTION_VOCABULARY_PATH",
                        str(Path(__file__).resolve().parent / "vocabulary.v2.json"),
                    )
                )
                vocabulary_payload = json.loads(vocabulary_path.read_text(encoding="utf-8"))
                vocabulary = [
                    str(item.get("prompt") or item.get("label"))
                    for item in vocabulary_payload.get("objects") or []
                    if item.get("prompt") or item.get("label")
                ]
                vocabulary_hash = hashlib.sha256(
                    json.dumps(
                        vocabulary,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                result = await asyncio.to_thread(
                    worker_engine.warmup,
                    vocabulary=vocabulary,
                    vocabulary_hash=vocabulary_hash,
                )
                startup.update(
                    {
                        "status": "ready",
                        "warmup_status": result.get("status"),
                        "warmup_latency_ms": result.get("latency_ms"),
                    }
                )
            except Exception as exc:
                startup.update(
                    {
                        "status": "degraded",
                        "warmup_status": "failed",
                        "warmup_error": f"{type(exc).__name__}: {exc}",
                    }
                )
        yield

    app = FastAPI(
        title="YOLOE Object Perception Worker",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _authorize(api_key, authorization)
        return {**startup, "engine": worker_engine.health(), **metrics.snapshot()}

    @app.get("/v1/models")
    async def models(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorize(api_key, authorization)
        return {"data": [worker_engine.health()]}

    @app.post("/v1/detections")
    async def detect(
        request: DetectionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _authorize(api_key, authorization)
        if request.contract_version != CONTRACT_VERSION:
            raise HTTPException(status_code=409, detail="unsupported contract_version")
        metrics.begin()
        try:
            with materialize_media(
                request.media,
                directory=media_root,
                max_bytes=max_media_bytes,
                allowed_media_types=IMAGE_MEDIA_TYPES,
                prefix="object-",
            ) as image_path:
                result = await asyncio.to_thread(
                    worker_engine.detect,
                    image_path=str(image_path),
                    media_type=request.media.media_type,
                    width=request.width,
                    height=request.height,
                    vocabulary=request.vocabulary,
                    vocabulary_hash=request.vocabulary_hash,
                )
            metrics.finish(latency_ms=result.get("latency_ms"), error=False)
            return {"job_id": request.job_id, **result}
        except Exception as exc:
            metrics.finish(latency_ms=None, error=True)
            raise HTTPException(
                status_code=503,
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc

    return app


def _authorize(expected: str, authorization: str | None) -> None:
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid bearer token")


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, round((len(values) - 1) * quantile)))
    return round(values[index], 3)


app = create_worker_app()
