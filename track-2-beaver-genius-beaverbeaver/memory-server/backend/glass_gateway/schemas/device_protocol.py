from typing import Any, Literal
from pydantic import BaseModel, Field


class WakeInfo(BaseModel):
    word: str
    engine: str


class HelloMessage(BaseModel):
    type: Literal["hello"]
    protocol: int = 1
    device_id: str
    client: str
    caps: list[str] = Field(default_factory=list)
    wake: WakeInfo | None = None


class HelloOkMessage(BaseModel):
    type: Literal["hello.ok"] = "hello.ok"
    session_id: str
    heartbeat_ms: int
    limits: dict[str, int]
    server_time_ms: int
    timezone_name: str = "Asia/Shanghai"


class WakeDetectedMessage(BaseModel):
    type: Literal["wake.detected"]
    turn_id: str
    wake_word: str
    confidence: float = 1.0
    ts: int | None = None


class AudioFormat(BaseModel):
    encoding: Literal["pcm_s16le"]
    sample_rate: int
    channels: int


class AudioTurnStartMessage(BaseModel):
    type: Literal["audio.turn.start"]
    turn_id: str
    format: AudioFormat


class AudioChunkMessage(BaseModel):
    type: Literal["audio.chunk"]
    turn_id: str
    index: int
    data_b64: str


class CaptureStreamStartMessage(BaseModel):
    type: Literal["capture.stream.start"]
    stream_id: str = Field(min_length=1, max_length=64)
    started_at_ms: int | None = Field(default=None, ge=0)
    device_monotonic_ms: int | None = Field(default=None, ge=0)
    boot_session_key: str | None = Field(default=None, min_length=1, max_length=160)
    format: AudioFormat
    image_interval_ms: int = Field(default=5000, ge=1000, le=60000)


class CaptureAudioChunkMessage(BaseModel):
    type: Literal["capture.audio.chunk"]
    stream_id: str = Field(min_length=1, max_length=64)
    index: int = Field(ge=0)
    captured_at_ms: int | None = Field(default=None, ge=0)
    device_monotonic_ms: int | None = Field(default=None, ge=0)
    data_b64: str = Field(min_length=1)


class CaptureStreamEndMessage(BaseModel):
    type: Literal["capture.stream.end"]
    stream_id: str = Field(min_length=1, max_length=64)
    ended_at_ms: int | None = Field(default=None, ge=0)
    device_monotonic_ms: int | None = Field(default=None, ge=0)
    reason: Literal["rotation", "shutdown", "network_reset", "external_power"]


class AudioTurnEndMessage(BaseModel):
    type: Literal["audio.turn.end"]
    turn_id: str
    reason: str


class BatteryTelemetry(BaseModel):
    percent: int | None = Field(default=None, ge=0, le=100)
    voltage_mv: int | None = Field(default=None, ge=0, le=6000)
    estimated: bool = True
    external_power: bool = False


class HeartbeatMessage(BaseModel):
    type: Literal["heartbeat"]
    ts: int | None = None
    battery: BatteryTelemetry | None = None
    memory_capture_active: bool | None = None


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class AsrFinalMessage(BaseModel):
    type: Literal["asr.final"] = "asr.final"
    turn_id: str
    text: str


class TtsChunkMessage(BaseModel):
    type: Literal["tts.chunk"] = "tts.chunk"
    index: int
    final: bool
    sample_rate: int
    pcm_b64: str
    text: str | None = None


class UnknownMessage(BaseModel):
    type: str
    payload: dict[str, Any] | None = None
