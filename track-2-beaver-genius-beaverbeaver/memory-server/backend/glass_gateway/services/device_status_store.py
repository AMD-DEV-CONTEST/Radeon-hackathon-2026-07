from __future__ import annotations

import time
from typing import Any, Callable


class DeviceStatusStore:
    def __init__(self, now_ms: Callable[[], int] | None = None) -> None:
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._devices: dict[str, dict[str, Any]] = {}

    def connect(self, device_id: str, *, client: str, caps: list[str]) -> dict[str, Any]:
        item = self._devices.get(device_id, {"device_id": device_id})
        item.update(
            {
                "connected": True,
                "client": client,
                "caps": list(caps),
                "last_seen_at_ms": self.now_ms(),
            }
        )
        item.pop("disconnected_at_ms", None)
        self._devices[device_id] = item
        return dict(item)

    def heartbeat(
        self,
        device_id: str,
        *,
        battery: dict[str, Any] | None,
        memory_capture_active: bool | None,
    ) -> dict[str, Any]:
        item = self._devices.get(device_id, {"device_id": device_id})
        item.update(
            {
                "connected": True,
                "last_seen_at_ms": self.now_ms(),
                "battery": battery,
                "memory_capture_active": memory_capture_active,
            }
        )
        self._devices[device_id] = item
        return dict(item)

    def disconnect(self, device_id: str) -> None:
        item = self._devices.get(device_id)
        if item:
            item["connected"] = False
            item["disconnected_at_ms"] = self.now_ms()

    def snapshot(self) -> dict[str, Any]:
        items = sorted(
            (dict(item) for item in self._devices.values()),
            key=lambda item: (
                bool(item.get("connected")),
                int(item.get("last_seen_at_ms") or 0),
            ),
            reverse=True,
        )
        return {
            "server_time_ms": self.now_ms(),
            "device": items[0] if items else None,
            "items": items,
        }
