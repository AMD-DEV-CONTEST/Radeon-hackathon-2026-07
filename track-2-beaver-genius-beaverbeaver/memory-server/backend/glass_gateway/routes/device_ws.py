import base64
import logging

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from glass_gateway.app_state import app_state
from glass_gateway.auth import auth_registry
from glass_gateway.schemas.device_protocol import (
    AudioChunkMessage,
    AudioTurnEndMessage,
    AudioTurnStartMessage,
    HeartbeatMessage,
    HelloMessage,
    HelloOkMessage,
    TtsChunkMessage,
    WakeDetectedMessage,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _authorized(websocket: WebSocket) -> bool:
    return auth_registry.bind_authorization(
        websocket.headers.get("authorization")
    ) is not None


def _authorized_header(authorization: str | None) -> bool:
    return auth_registry.authorized(authorization)


@router.get("/v1/device/status")
async def device_status(authorization: str | None = Header(default=None)) -> dict:
    if not _authorized_header(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    return app_state.device_status.snapshot()


async def _send_json_if_connected(websocket: WebSocket, payload: dict) -> bool:
    try:
        await websocket.send_json(payload)
    except (RuntimeError, WebSocketDisconnect):
        return False
    return True


@router.websocket("/v1/device/ws")
async def device_ws(websocket: WebSocket) -> None:
    if not _authorized(websocket):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    device_id: str | None = None

    try:
        hello_raw = await websocket.receive_json()
        hello = HelloMessage.model_validate(hello_raw)
        device_id = hello.device_id
        session = app_state.sessions.create(device_id)
        app_state.device_sockets[device_id] = websocket
        app_state.device_status.connect(device_id, client=hello.client, caps=hello.caps)
        await websocket.send_json(
            HelloOkMessage(
                session_id=session.session_id,
                heartbeat_ms=app_state.settings.heartbeat_ms,
                limits={
                    "audio_chunk_bytes": app_state.settings.audio_chunk_bytes,
                    "command_max_ms": app_state.settings.command_max_ms,
                },
                server_time_ms=app_state.capture.now_ms(),
                timezone_name="Asia/Shanghai",
            ).model_dump(mode="json")
        )

        while True:
            raw = await websocket.receive_json()
            message_type = raw.get("type")
            app_state.sessions.touch(device_id)

            if message_type == "heartbeat":
                try:
                    heartbeat = HeartbeatMessage.model_validate(raw)
                except ValidationError as exc:
                    logger.warning("invalid heartbeat ignored device_id=%s: %s", device_id, exc)
                    await websocket.send_json(
                        {"type": "heartbeat.ok", "ts": raw.get("ts"), "telemetry_valid": False}
                    )
                    continue
                app_state.device_status.heartbeat(
                    device_id,
                    battery=(
                        heartbeat.battery.model_dump(mode="json")
                        if heartbeat.battery is not None
                        else None
                    ),
                    memory_capture_active=heartbeat.memory_capture_active,
                )
                await websocket.send_json({"type": "heartbeat.ok", "ts": heartbeat.ts})
            elif message_type == "wake.detected":
                WakeDetectedMessage.model_validate(raw)
                patch = app_state.cards.wake_patch(session.next_seq())
                await websocket.send_json(patch.model_dump(mode="json"))
            elif message_type == "audio.turn.start":
                msg = AudioTurnStartMessage.model_validate(raw)
                app_state.audio_turns.start(msg.turn_id)
                patch = app_state.cards.thinking_patch(session.next_seq())
                await websocket.send_json(patch.model_dump(mode="json"))
            elif message_type == "audio.chunk":
                msg = AudioChunkMessage.model_validate(raw)
                app_state.audio_turns.add_chunk(msg.turn_id, msg.index, msg.data_b64)
            elif message_type == "audio.turn.end":
                msg = AudioTurnEndMessage.model_validate(raw)
                pcm = app_state.audio_turns.finish(msg.turn_id)
                text = await app_state.asr.transcribe(pcm, sample_rate=16000)
                await websocket.send_json({"type": "asr.final", "turn_id": msg.turn_id, "text": text})
                if not text:
                    patch = app_state.cards.error_patch(session.next_seq(), "我没听清，请再说一遍。")
                    await websocket.send_json(patch.model_dump(mode="json"))
                else:
                    answer = await app_state.llm.complete(text)
                    patch = app_state.cards.answer_patch(session.next_seq(), answer)
                    await websocket.send_json(patch.model_dump(mode="json"))
                    tts_pcm, sample_rate = await app_state.tts.synthesize(answer)
                    if tts_pcm:
                        chunk_size = 6000
                        for index, offset in enumerate(range(0, len(tts_pcm), chunk_size)):
                            chunk = tts_pcm[offset : offset + chunk_size]
                            await websocket.send_json(
                                TtsChunkMessage(
                                    index=index,
                                    final=offset + chunk_size >= len(tts_pcm),
                                    sample_rate=sample_rate,
                                    pcm_b64=base64.b64encode(chunk).decode(),
                                    text=answer if index == 0 else None,
                                ).model_dump(mode="json")
                            )
            else:
                await websocket.send_json(
                    {"type": "error", "code": "unknown_message", "message": str(message_type)}
                )
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("device websocket failed device_id=%s", device_id)
        raise
    finally:
        if device_id:
            current = app_state.device_sockets.get(device_id)
            if current is websocket:
                app_state.device_sockets.pop(device_id, None)
                app_state.sessions.remove(device_id)
                app_state.device_status.disconnect(device_id)
