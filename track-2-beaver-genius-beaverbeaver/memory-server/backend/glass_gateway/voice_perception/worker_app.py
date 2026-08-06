from __future__ import annotations

import asyncio
import os
from pathlib import Path
import threading
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from glass_gateway.external_services.contracts import (
    CONTRACT_VERSION,
    DEFAULT_MAX_AUDIO_BYTES,
)
from glass_gateway.external_services.media import (
    AUDIO_MEDIA_TYPES,
    EncodedMedia,
    materialize_media,
)

from .contracts import StaleVoiceModelRevisionError, VoiceAudioDecodeError
from .engine import ProductionVoiceEngine


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class VoiceRequest(BaseModel):
    job_id: str = Field(min_length=1)
    audio_evidence_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    media: EncodedMedia
    speech_present: bool | None = None
    expected_model_revision: str = Field(min_length=1)
    expected_config_version: str = Field(min_length=1)


class WorkerMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.errors = 0
        self.queue_depth = 0
        self.queue_high_water = 0
        self.latencies: list[float] = []

    def begin(self) -> None:
        with self._lock:
            self.requests += 1
            self.queue_depth += 1
            self.queue_high_water = max(self.queue_high_water, self.queue_depth)

    def finish(self, *, latency_ms: float | None, error: bool) -> None:
        with self._lock:
            self.queue_depth = max(0, self.queue_depth - 1)
            self.errors += int(error)
            if latency_ms is not None:
                self.latencies.append(float(latency_ms))
                self.latencies = self.latencies[-5000:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            ordered = sorted(self.latencies)
            return {
                "requests": self.requests,
                "errors": self.errors,
                "queue_depth": self.queue_depth,
                "queue_high_water": self.queue_high_water,
                "p95_latency_ms": _percentile(ordered, 0.95),
            }


def create_worker_app(engine: ProductionVoiceEngine | Any | None = None) -> FastAPI:
    allowed_media_root = Path(
        os.getenv(
            "VOICE_ALLOWED_MEDIA_ROOT", str(PROJECT_ROOT / ".runtime/raw-media")
        )
    )
    worker_engine = engine or ProductionVoiceEngine(
        config_path=os.getenv(
            "VOICE_CONFIG_PATH",
            str(
                PROJECT_ROOT
                / "evaluation/speaker/configs/speaker-candidate-production-v1.json"
            ),
        ),
        allowed_media_root=str(allowed_media_root),
        runtime_root=os.getenv("VOICE_MODEL_ROOT", "/opt/beaver/models/speaker"),
    )
    metrics = WorkerMetrics()
    max_media_bytes = int(
        os.getenv("VOICE_MAX_MEDIA_BYTES", str(DEFAULT_MAX_AUDIO_BYTES))
    )
    api_key = os.getenv("VOICE_API_KEY") or os.getenv(
        "EXTERNAL_SERVICE_API_KEY", ""
    )
    app = FastAPI(title="Beaver Memory Voice Worker", version="1.0.0")

    @app.get("/health")
    async def health(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _authorize(api_key, authorization)
        return {"worker": worker_engine.health(), **metrics.snapshot()}

    @app.get("/v1/models")
    async def models(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorize(api_key, authorization)
        return {"data": [worker_engine.health()]}

    @app.post("/v1/voices/analyze")
    async def process(
        request: VoiceRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _authorize(api_key, authorization)
        if request.contract_version != CONTRACT_VERSION:
            raise HTTPException(status_code=409, detail="unsupported contract_version")
        metrics.begin()
        try:
            with materialize_media(
                request.media,
                directory=allowed_media_root,
                max_bytes=max_media_bytes,
                allowed_media_types=AUDIO_MEDIA_TYPES,
                prefix="voice-",
            ) as audio_path:
                result = await asyncio.to_thread(
                    worker_engine.process,
                    audio_path=str(audio_path),
                    media_type=request.media.media_type,
                    speech_present=request.speech_present,
                    expected_model_revision=request.expected_model_revision,
                    expected_config_version=request.expected_config_version,
                )
            metrics.finish(latency_ms=result.get("latency_ms"), error=False)
            return {
                "job_id": request.job_id,
                "audio_evidence_id": request.audio_evidence_id,
                **result,
            }
        except StaleVoiceModelRevisionError as exc:
            metrics.finish(latency_ms=None, error=True)
            raise _http_error(409, "stale_model_revision", exc) from exc
        except FileNotFoundError as exc:
            metrics.finish(latency_ms=None, error=True)
            raise _http_error(404, "failed_missing_evidence", exc) from exc
        except VoiceAudioDecodeError as exc:
            metrics.finish(latency_ms=None, error=True)
            raise _http_error(422, "failed_audio_decode", exc) from exc
        except Exception as exc:
            metrics.finish(latency_ms=None, error=True)
            message = f"{type(exc).__name__}: {exc}"
            code = (
                "failed_oom"
                if "out of memory" in message.lower() or "cuda error" in message.lower()
                else "failed_model"
            )
            raise HTTPException(
                status_code=503,
                detail={"error_code": code, "message": message[:1000]},
            ) from exc

    return app


def _authorize(expected: str, authorization: str | None) -> None:
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid bearer token")


def _http_error(status: int, code: str, exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error_code": code, "message": f"{type(exc).__name__}: {exc}"[:1000]},
    )


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, round((len(values) - 1) * quantile)))
    return round(values[index], 3)


app = create_worker_app()
