from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

Language = Literal["zh", "en", "unknown"]
RecognitionLanguage = Literal["zh", "en"]
AgentAction = Literal["respond", "confirm", "unknown", "execute", "reject", "ignore"]
CommandIntentName = Literal[
    "LIGHT_ON", "LIGHT_OFF", "OPEN_DOOR", "CHAT_OTHER", "UNKNOWN"
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_SESSION = "INVALID_SESSION"
    SESSION_REPLACED = "SESSION_REPLACED"
    SERVER_BUSY = "SERVER_BUSY"
    FACE_NOT_FOUND = "FACE_NOT_FOUND"
    MULTIPLE_FACES = "MULTIPLE_FACES"
    INVALID_MOUTH_BOX = "INVALID_MOUTH_BOX"
    GPU_OUT_OF_MEMORY = "GPU_OUT_OF_MEMORY"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class BaseEvent(BaseModel):
    type: str
    sessionId: str
    timestamp: datetime = Field(default_factory=utc_now)


class MouthBox(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)


class CommandDecision(BaseModel):
    intent: CommandIntentName
    accepted: bool
    executable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    margin: float = Field(ge=0.0, le=1.0)
    topK: list[dict[str, Any]]
    logits: list[float] | dict[str, float]
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CalibrationRequest(BaseModel):
    type: Literal["calibration.start"] = "calibration.start"
    profileId: str
    language: RecognitionLanguage
    phraseId: str
    phrase: str = ""
    scope: Literal["personal", "global"] = "personal"


class ClipStartRequest(BaseModel):
    type: Literal["clip.start"] = "clip.start"
    profileId: str
    language: RecognitionLanguage


class CalibrationSaved(BaseEvent):
    type: Literal["calibration.saved"] = "calibration.saved"
    profileId: str
    scope: Literal["personal", "global"]
    intent: CommandIntentName
    samplePath: str
    frames: int
    detectedFrames: int


class AgentResult(BaseModel):
    type: Literal["agent.result"] = "agent.result"
    action: AgentAction
    language: Language
    text: str
    arguments: dict[str, Any]
    requiresConfirmation: bool


class ErrorEvent(BaseEvent):
    type: Literal["error"] = "error"
    stage: str
    code: ErrorCode
    message: str
    recoverable: bool
