"""English-first TTS service with OpenAI and MiniMax-compatible APIs."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError


MODEL_PATH = Path(os.getenv("TTS_MODEL_PATH", "/persistent/silent-core/models/Kokoro-82M"))
ONNX_MODEL_PATH = Path(
    os.getenv(
        "TTS_ONNX_MODEL_PATH",
        "/persistent/silent-core/models/kokoro-int8-multi-lang-v1_0-git",
    )
)
BACKEND = os.getenv("TTS_BACKEND", "sherpa").lower()
DEVICE = os.getenv("TTS_DEVICE", "cpu").lower()
NUM_THREADS = int(os.getenv("TTS_NUM_THREADS", "8"))
MAX_CHUNK_CHARS = int(os.getenv("TTS_MAX_CHUNK_CHARS", "240"))

VOICE_MAP = {
    "alloy": "af_alloy",
    "heart": "af_heart",
    "bella": "af_bella",
    "jessica": "af_jessica",
    "michael": "am_michael",
    "puck": "am_puck",
    "george": "bm_george",
    "emma": "bf_emma",
    # Existing application defaults and common MiniMax aliases.
    "male-qn-qingse": "am_michael",
    "male-qn-jingying": "bm_george",
    "female-shaonv": "af_heart",
    "female-yujie": "bf_emma",
}

# Speaker ordering used by the official Kokoro v1.0 voice pack. Unknown voices
# fall back to af_heart so application-specific aliases never fail a request.
SHERPA_SPEAKER_IDS = {
    "af_alloy": 0,
    "af_aoede": 1,
    "af_bella": 2,
    "af_heart": 3,
    "af_jessica": 4,
    "af_kore": 5,
    "af_nicole": 6,
    "af_nova": 7,
    "af_river": 8,
    "af_sarah": 9,
    "af_sky": 10,
    "am_adam": 11,
    "am_echo": 12,
    "am_eric": 13,
    "am_fenrir": 14,
    "am_liam": 15,
    "am_michael": 16,
    "am_onyx": 17,
    "am_puck": 18,
    "am_santa": 19,
    "bf_alice": 20,
    "bf_emma": 21,
    "bf_isabella": 22,
    "bf_lily": 23,
    "bm_daniel": 24,
    "bm_fable": 25,
    "bm_george": 26,
    "bm_lewis": 27,
}

_model: Any = None
_pipelines: dict[str, Any] = {}
_torch_threads_configured = False
_load_lock = threading.Lock()
_inference_lock = threading.Lock()

app = FastAPI(title="Silent Core TTS API", version="1.1.0")


class SpeechRequest(BaseModel):
    model: str = "silent-core/tts"
    input: str = Field(min_length=1, max_length=10_000)
    voice: str = "heart"
    response_format: str = "mp3"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


class MiniMaxSpeechRequest(BaseModel):
    model: str = "silent-core/tts"
    text: str = Field(min_length=1, max_length=10_000)
    stream: bool = False
    voice_setting: dict[str, Any] = Field(default_factory=dict)
    audio_setting: dict[str, Any] = Field(default_factory=dict)
    output_format: str = "hex"


def _find_onnx_model() -> Path:
    candidates = [
        ONNX_MODEL_PATH / "model.int8.onnx",
        ONNX_MODEL_PATH / "model.onnx",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No Kokoro ONNX model found under {ONNX_MODEL_PATH}")


def _load_sherpa():
    global _model
    import sherpa_onnx

    with _load_lock:
        if _model is None:
            lexicons = [
                ONNX_MODEL_PATH / "lexicon-us-en.txt",
                ONNX_MODEL_PATH / "lexicon-zh.txt",
            ]
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                        model=str(_find_onnx_model()),
                        voices=str(ONNX_MODEL_PATH / "voices.bin"),
                        tokens=str(ONNX_MODEL_PATH / "tokens.txt"),
                        data_dir=str(ONNX_MODEL_PATH / "espeak-ng-data"),
                        lexicon=",".join(str(path) for path in lexicons if path.exists()),
                    ),
                    provider="cpu",
                    debug=False,
                    num_threads=NUM_THREADS,
                ),
                max_num_sentences=1,
            )
            if not config.validate():
                raise RuntimeError("Invalid sherpa-onnx Kokoro configuration")
            _model = sherpa_onnx.OfflineTts(config)
    return _model


def _load_torch_pipeline(voice: str):
    global _model, _torch_threads_configured
    from kokoro import KModel, KPipeline

    lang_code = "b" if voice.startswith("b") else "a"
    with _load_lock:
        if not _torch_threads_configured:
            import torch

            torch.set_num_threads(NUM_THREADS)
            torch.set_num_interop_threads(1)
            _torch_threads_configured = True
        if _model is None:
            _model = KModel(
                repo_id="hexgrad/Kokoro-82M",
                config=str(MODEL_PATH / "config.json"),
                model=str(MODEL_PATH / "kokoro-v1_0.pth"),
            ).to(DEVICE).eval()
        if lang_code not in _pipelines:
            _pipelines[lang_code] = KPipeline(
                lang_code=lang_code,
                repo_id="hexgrad/Kokoro-82M",
                model=_model,
            )
    return _pipelines[lang_code]


def _split_text(text: str) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?;:])\s+", text) if part.strip()]
    chunks: list[str] = []
    for sentence in sentences or [text.strip()]:
        while len(sentence) > MAX_CHUNK_CHARS:
            split_at = sentence.rfind(" ", 0, MAX_CHUNK_CHARS + 1)
            if split_at < MAX_CHUNK_CHARS // 2:
                split_at = MAX_CHUNK_CHARS
            chunks.append(sentence[:split_at].strip())
            sentence = sentence[split_at:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


def _resolve_voice(voice: str) -> str:
    return VOICE_MAP.get(voice, voice)


def _generate_segment(text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
    voice = _resolve_voice(voice)
    with _inference_lock:
        if BACKEND == "sherpa":
            import sherpa_onnx

            tts = _load_sherpa()
            config = sherpa_onnx.GenerationConfig()
            config.sid = SHERPA_SPEAKER_IDS.get(voice, SHERPA_SPEAKER_IDS["af_heart"])
            config.speed = speed
            config.silence_scale = 0.2
            audio = tts.generate(text, config)
            samples = np.asarray(audio.samples, dtype=np.float32)
            sample_rate = int(audio.sample_rate)
        elif BACKEND == "torch":
            import torch

            pipeline = _load_torch_pipeline(voice)
            voice_path = MODEL_PATH / "voices" / f"{voice}.pt"
            if not voice_path.exists():
                raise ValueError(f"unknown voice: {voice}")
            parts = []
            with torch.inference_mode():
                for _, _, audio in pipeline(text, voice=str(voice_path), speed=speed):
                    parts.append(np.asarray(audio, dtype=np.float32))
            samples = np.concatenate(parts) if parts else np.empty(0, dtype=np.float32)
            sample_rate = 24_000
        else:
            raise RuntimeError(f"Unsupported TTS_BACKEND: {BACKEND}")
    if samples.size == 0:
        raise RuntimeError("TTS model returned no audio")
    return samples, sample_rate


def _encode_audio(samples: np.ndarray, sample_rate: int, audio_format: str) -> tuple[bytes, str]:
    output = io.BytesIO()
    if audio_format == "wav":
        sf.write(output, samples, sample_rate, format="WAV", subtype="PCM_16")
        return output.getvalue(), "audio/wav"
    if audio_format == "mp3":
        sf.write(output, samples, sample_rate, format="MP3")
        return output.getvalue(), "audio/mpeg"
    raise ValueError("response_format must be mp3 or wav")


def _synthesize_all(text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
    parts: list[np.ndarray] = []
    sample_rate = 24_000
    for segment in _split_text(text):
        audio, sample_rate = _generate_segment(segment, voice, speed)
        parts.append(audio)
    return np.concatenate(parts), sample_rate


def _minimax_payload(
    audio: bytes,
    *,
    status: int,
    audio_format: str,
    sample_rate: int,
    text: str,
    duration_ms: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "data": {"audio": audio.hex(), "status": status},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }
    if status == 2:
        payload["extra_info"] = {
            "audio_format": audio_format,
            "audio_length": duration_ms,
            "audio_size": len(audio),
            "audio_sample_rate": sample_rate,
            "word_count": len(text.split()),
            "usage_characters": len(text),
        }
    return payload


async def _openai_response(payload: dict[str, Any]) -> Response:
    request = SpeechRequest.model_validate(payload)
    try:
        samples, sample_rate = await asyncio.to_thread(
            _synthesize_all, request.input, request.voice, request.speed
        )
        data, media_type = _encode_audio(samples, sample_rate, request.response_format)
        return Response(content=data, media_type=media_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _minimax_stream(request: MiniMaxSpeechRequest):
    voice = str(request.voice_setting.get("voice_id", "heart"))
    speed = float(request.voice_setting.get("speed", 1.0))
    audio_format = str(request.audio_setting.get("format", "mp3"))
    chunks = _split_text(request.text)
    for index, text in enumerate(chunks):
        try:
            samples, sample_rate = await asyncio.to_thread(
                _generate_segment, text, voice, speed
            )
            data, _ = _encode_audio(samples, sample_rate, audio_format)
            status = 2 if index == len(chunks) - 1 else 1
            duration_ms = round(len(samples) / sample_rate * 1000)
            yield json.dumps(
                _minimax_payload(
                    data,
                    status=status,
                    audio_format=audio_format,
                    sample_rate=sample_rate,
                    text=request.text,
                    duration_ms=duration_ms,
                ),
                separators=(",", ":"),
            ) + "\n"
        except Exception as exc:
            yield json.dumps(
                {"base_resp": {"status_code": 1001, "status_msg": str(exc)}},
                separators=(",", ":"),
            ) + "\n"
            return


async def _minimax_response(payload: dict[str, Any]):
    request = MiniMaxSpeechRequest.model_validate(payload)
    if request.output_format != "hex":
        raise HTTPException(status_code=400, detail="only output_format=hex is supported")
    if request.stream:
        return StreamingResponse(
            _minimax_stream(request),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    voice = str(request.voice_setting.get("voice_id", "heart"))
    speed = float(request.voice_setting.get("speed", 1.0))
    audio_format = str(request.audio_setting.get("format", "mp3"))
    try:
        samples, sample_rate = await asyncio.to_thread(
            _synthesize_all, request.text, voice, speed
        )
        data, _ = _encode_audio(samples, sample_rate, audio_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    duration_ms = round(len(samples) / sample_rate * 1000)
    return JSONResponse(
        _minimax_payload(
            data,
            status=2,
            audio_format=audio_format,
            sample_rate=sample_rate,
            text=request.text,
            duration_ms=duration_ms,
        )
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "backend": BACKEND,
        "device": "cpu" if BACKEND == "sherpa" else DEVICE,
        "model_loaded": _model is not None,
        "threads": NUM_THREADS if DEVICE == "cpu" or BACKEND == "sherpa" else None,
    }


@app.post("/v1/audio/speech")
async def audio_speech(request: Request):
    try:
        payload = await request.json()
        if "text" in payload:
            return await _minimax_response(payload)
        return await _openai_response(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


@app.on_event("startup")
async def warm_model():
    if os.getenv("TTS_WARM_ON_START", "true").lower() in {"1", "true", "yes"}:
        started = time.perf_counter()
        try:
            await asyncio.to_thread(_generate_segment, "Silent Core is ready.", "heart", 1.0)
            app.state.warmup_seconds = time.perf_counter() - started
        except Exception as exc:
            app.state.warmup_error = str(exc)
