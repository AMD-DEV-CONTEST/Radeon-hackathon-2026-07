import base64
import io
import wave

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect, WebSocketState

from glass_gateway.app_state import app_state
from glass_gateway.schemas.cards import UiPatch
from glass_gateway.schemas.device_protocol import TtsChunkMessage

router = APIRouter(prefix="/v1/preview")


class TtsPreviewRequest(BaseModel):
    text: str


class AskTextPreviewRequest(BaseModel):
    text: str


def _wav_to_pcm16_mono(wav_bytes: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise HTTPException(status_code=400, detail="only 16-bit wav is supported")

    if channels == 1:
        return frames, sample_rate

    frame_count = len(frames) // (sample_width * channels)
    out = bytearray(frame_count * sample_width)
    for i in range(frame_count):
        src = i * sample_width * channels
        dst = i * sample_width
        out[dst : dst + sample_width] = frames[src : src + sample_width]
    return bytes(out), sample_rate


def _get_socket(device_id: str):
    socket = app_state.device_sockets.get(device_id)
    if socket is None:
        raise HTTPException(status_code=404, detail="device is not connected")
    if socket.client_state != WebSocketState.CONNECTED:
        app_state.device_sockets.pop(device_id, None)
        app_state.sessions.remove(device_id)
        raise HTTPException(status_code=404, detail="device is not connected")
    return socket


async def _send_json_or_drop(device_id: str, payload: dict) -> None:
    socket = _get_socket(device_id)
    try:
        await socket.send_json(payload)
    except (RuntimeError, WebSocketDisconnect):
        app_state.device_sockets.pop(device_id, None)
        app_state.sessions.remove(device_id)
        raise HTTPException(status_code=404, detail="device is not connected")


@router.post("/devices/{device_id}/cards")
async def send_card(device_id: str, patch: UiPatch) -> dict[str, str]:
    await _send_json_or_drop(device_id, patch.model_dump(mode="json"))
    return {"status": "sent"}


@router.post("/devices/{device_id}/tts")
async def send_tts(device_id: str, req: TtsPreviewRequest) -> dict[str, str]:
    pcm, sample_rate = await app_state.tts.synthesize(req.text)
    if not pcm:
        raise HTTPException(status_code=502, detail="tts synthesis failed")

    chunk_size = 6000
    for index, offset in enumerate(range(0, len(pcm), chunk_size)):
        chunk = pcm[offset : offset + chunk_size]
        await _send_json_or_drop(
            device_id,
            TtsChunkMessage(
                index=index,
                final=offset + chunk_size >= len(pcm),
                sample_rate=sample_rate,
                pcm_b64=base64.b64encode(chunk).decode(),
                text=req.text if index == 0 else None,
            ).model_dump(mode="json"),
        )
    return {"status": "sent"}


@router.post("/devices/{device_id}/force-listen")
async def force_listen(device_id: str) -> dict[str, str]:
    await _send_json_or_drop(device_id, {"type": "debug.force_listen"})
    return {"status": "sent"}


@router.post("/devices/{device_id}/record-wake-sample")
async def record_wake_sample(device_id: str) -> dict[str, str]:
    await _send_json_or_drop(device_id, {"type": "debug.record_wake_sample"})
    return {"status": "sent"}


@router.post("/devices/{device_id}/record-query-sample")
async def record_query_sample(device_id: str) -> dict[str, str]:
    await _send_json_or_drop(device_id, {"type": "debug.record_query_sample"})
    return {"status": "sent"}


@router.post("/devices/{device_id}/ask-text")
async def ask_text(device_id: str, req: AskTextPreviewRequest) -> dict[str, str]:
    answer = await app_state.llm.complete(req.text)
    patch = app_state.cards.answer_patch(9000, answer)
    await _send_json_or_drop(device_id, patch.model_dump(mode="json"))

    pcm, sample_rate = await app_state.tts.synthesize(answer)
    if not pcm:
        return {"status": "sent", "tts": "unavailable"}

    chunk_size = 6000
    for index, offset in enumerate(range(0, len(pcm), chunk_size)):
        chunk = pcm[offset : offset + chunk_size]
        await _send_json_or_drop(
            device_id,
            TtsChunkMessage(
                index=index,
                final=offset + chunk_size >= len(pcm),
                sample_rate=sample_rate,
                pcm_b64=base64.b64encode(chunk).decode(),
                text=answer if index == 0 else None,
            ).model_dump(mode="json"),
        )
    return {"status": "sent", "tts": "sent"}


@router.post("/devices/{device_id}/voice-roundtrip")
async def voice_roundtrip(device_id: str, file: UploadFile = File(...)) -> dict[str, str]:
    wav_bytes = await file.read()
    if not wav_bytes:
        raise HTTPException(status_code=400, detail="empty wav file")

    pcm, sample_rate = _wav_to_pcm16_mono(wav_bytes)
    transcript = await app_state.asr.transcribe(pcm, sample_rate=sample_rate)
    if not transcript:
        raise HTTPException(status_code=502, detail="asr returned empty text")

    answer = await app_state.llm.complete(transcript)
    patch = app_state.cards.answer_patch(9000, answer)
    await _send_json_or_drop(device_id, patch.model_dump(mode="json"))

    tts_pcm, tts_rate = await app_state.tts.synthesize(answer)
    if tts_pcm:
        chunk_size = 6000
        for index, offset in enumerate(range(0, len(tts_pcm), chunk_size)):
            chunk = tts_pcm[offset : offset + chunk_size]
            await _send_json_or_drop(
                device_id,
                TtsChunkMessage(
                    index=index,
                    final=offset + chunk_size >= len(tts_pcm),
                    sample_rate=tts_rate,
                    pcm_b64=base64.b64encode(chunk).decode(),
                    text=answer if index == 0 else None,
                ).model_dump(mode="json"),
            )

    return {"status": "sent", "transcript": transcript, "answer": answer}
