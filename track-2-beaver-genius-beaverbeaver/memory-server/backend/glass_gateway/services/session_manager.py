from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DeviceSession:
    session_id: str
    device_id: str
    connected_at: datetime = field(default_factory=utc_now)
    last_seen_at: datetime = field(default_factory=utc_now)
    seq: int = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class SessionManager:
    def __init__(self) -> None:
        self._sessions_by_device: dict[str, DeviceSession] = {}

    def create(self, device_id: str) -> DeviceSession:
        session = DeviceSession(session_id=f"sess_{uuid4().hex[:12]}", device_id=device_id)
        self._sessions_by_device[device_id] = session
        return session

    def get(self, device_id: str) -> DeviceSession | None:
        return self._sessions_by_device.get(device_id)

    def touch(self, device_id: str) -> None:
        session = self.get(device_id)
        if session:
            session.last_seen_at = utc_now()

    def remove(self, device_id: str) -> None:
        self._sessions_by_device.pop(device_id, None)

    def list_devices(self) -> list[str]:
        return sorted(self._sessions_by_device)
