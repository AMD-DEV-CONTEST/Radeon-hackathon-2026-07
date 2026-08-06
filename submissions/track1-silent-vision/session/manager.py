from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4


class SessionError(Exception):
    code = "INVALID_SESSION"


class ServerBusyError(SessionError):
    code = "SERVER_BUSY"


class SessionReplacedError(SessionError):
    code = "SESSION_REPLACED"


@dataclass(frozen=True)
class CreatedSession:
    session_id: str
    expires_in_seconds: int


@dataclass
class ActiveSession:
    session_id: str
    created_at: datetime
    last_seen_at: datetime
    active_inference_task: object | None = None
    inference_cancel_event: object | None = None
    streaming: bool = False
    accepting_frames: bool = False
    stream_generation: int = 0
    metadata: dict[str, object] = field(default_factory=dict)

    def reset_stream(self) -> None:
        self.metadata.clear()
        self.streaming = True
        self.accepting_frames = True
        self.stream_generation += 1

    def stop_stream(self) -> None:
        self.metadata.clear()
        self.streaming = False
        self.accepting_frames = False
        self.stream_generation += 1

    def commit_stream(self) -> None:
        self.accepting_frames = False


class SessionManager:
    def __init__(self, pending_ttl: timedelta) -> None:
        self.pending_ttl = pending_ttl
        self._pending: dict[str, datetime] = {}
        self._active: dict[str, ActiveSession] = {}

    def create_pending_session(self) -> CreatedSession:
        session_id = str(uuid4())
        self._pending[session_id] = datetime.now(timezone.utc) + self.pending_ttl
        return CreatedSession(session_id=session_id, expires_in_seconds=int(self.pending_ttl.total_seconds()))

    def activate(self, session_id: str) -> ActiveSession:
        self._remove_expired_pending()
        expires_at = self._pending.pop(session_id, None)
        if expires_at is None:
            raise SessionError("invalid or expired session")
        now = datetime.now(timezone.utc)
        active = ActiveSession(
            session_id=session_id,
            created_at=now,
            last_seen_at=now,
        )
        self._active.clear()
        self._active[session_id] = active
        return active

    def is_current(self, session_id: str) -> bool:
        return session_id in self._active

    def ensure_current(self, active: ActiveSession) -> None:
        if self._active.get(active.session_id) is not active:
            raise SessionReplacedError("session was replaced by a newer connection")

    def get_active(self, session_id: str) -> ActiveSession:
        active = self._active.get(session_id)
        if active is None:
            raise SessionError("invalid active session")
        active.last_seen_at = datetime.now(timezone.utc)
        return active

    def disconnect(self, session_id: str) -> None:
        self._active.pop(session_id, None)
        self._pending.pop(session_id, None)

    def _remove_expired_pending(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [session_id for session_id, expires_at in self._pending.items() if expires_at <= now]
        for session_id in expired:
            self._pending.pop(session_id, None)
