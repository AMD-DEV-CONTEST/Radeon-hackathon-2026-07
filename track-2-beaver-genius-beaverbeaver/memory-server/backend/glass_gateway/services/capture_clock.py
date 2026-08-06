from __future__ import annotations

from dataclasses import dataclass


BEIJING_TIMEZONE = "Asia/Shanghai"
MAX_MONOTONIC_DELTA_MS = 7 * 24 * 60 * 60 * 1000
# Device monotonic clocks are only useful when all media streams share the same
# clock. Some ESP clients currently report audio and photo monotonic values from
# different origins. Never allow that client-side mismatch to move evidence far
# away from the authoritative server receive timeline.
MAX_CAPTURE_SERVER_DRIFT_MS = 60 * 1000


@dataclass(frozen=True)
class CaptureTime:
    captured_at_ms: int
    device_monotonic_ms: int | None
    server_received_at_ms: int
    server_anchor_ms: int
    device_monotonic_anchor_ms: int | None
    timezone_name: str
    source: str


@dataclass(frozen=True)
class ServerClockAnchor:
    server_anchor_ms: int
    device_monotonic_anchor_ms: int | None
    timezone_name: str = BEIJING_TIMEZONE

    def map(
        self,
        *,
        device_monotonic_ms: int | None,
        server_received_at_ms: int,
        max_server_drift_ms: int = MAX_CAPTURE_SERVER_DRIFT_MS,
    ) -> CaptureTime:
        source = "server_received_fallback"
        captured_at_ms = server_received_at_ms
        if self.device_monotonic_anchor_ms is not None and device_monotonic_ms is not None:
            delta_ms = device_monotonic_ms - self.device_monotonic_anchor_ms
            if abs(delta_ms) <= MAX_MONOTONIC_DELTA_MS:
                mapped_at_ms = self.server_anchor_ms + delta_ms
                if abs(mapped_at_ms - server_received_at_ms) <= max_server_drift_ms:
                    captured_at_ms = mapped_at_ms
                    source = "server_anchor_monotonic"
                else:
                    source = "server_received_drift_guard"
        return CaptureTime(
            captured_at_ms=captured_at_ms,
            device_monotonic_ms=device_monotonic_ms,
            server_received_at_ms=server_received_at_ms,
            server_anchor_ms=self.server_anchor_ms,
            device_monotonic_anchor_ms=self.device_monotonic_anchor_ms,
            timezone_name=self.timezone_name,
            source=source,
        )
