from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredEvidence:
    evidence_id: str
    media_type: str
    path: Path
    captured_at_ms: int
    sha256: str
    bytes: int
    device_monotonic_ms: int | None = None
    server_received_at_ms: int | None = None
    server_anchor_ms: int | None = None
    device_monotonic_anchor_ms: int | None = None
    timezone_name: str = "Asia/Shanghai"
    capture_time_source: str = "server_received_fallback"
    device_id: str | None = None
    boot_id: str | None = None
    stream_id: str | None = None
    sequence: int | None = None
    captured_at_device_ms: int | None = None
    clock_synced: bool | None = None
    duration_ms: int = 0
    clock_anomaly: bool = False
    clock_deviation_ms: int | None = None
