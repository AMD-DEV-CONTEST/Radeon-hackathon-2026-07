"""Port lock manager — prevents concurrent access to serial ports.

Lightly adapted from MakerMods-LeRobot-UI port_lock_manager.py. Tracks which
serial ports are in use by which feature (teleop, recording, calibration...)
so that features never fight over the same ``/dev/ttyACM*`` device — a
classic Feetech bus wedges the moment two processes try to open the port.

All-or-nothing acquisition: when acquiring multiple ports, either all succeed
or none are acquired. Fails immediately with ``PortInUseError`` rather than
blocking, so the caller can surface a useful error to the UI.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class PortInUseError(Exception):
    """Raised when a port is already locked by another feature."""

    def __init__(self, port: str, owner: str):
        self.port = port
        self.owner = owner
        super().__init__(f"Port {port} is currently in use by {owner}")


@dataclass
class PortLease:
    port: str
    owner: str  # "teleop", "recording", "wiggle", ...
    mode: str  # "direct" (Python bus) or "subprocess" (CLI child)
    acquired_at: datetime = field(default_factory=datetime.now)
    process_id: Optional[str] = None


class PortLockManager:
    def __init__(self) -> None:
        self._leases: dict[str, PortLease] = {}  # normalized port -> lease
        self._lock = asyncio.Lock()
        self._process_ports: dict[str, list[str]] = {}

    @staticmethod
    def _normalize(port: str) -> str:
        try:
            return os.path.realpath(port)
        except (OSError, ValueError):
            return port

    async def acquire(
        self,
        ports: list[str],
        owner: str,
        mode: str = "direct",
        process_id: Optional[str] = None,
    ) -> None:
        normalized = [self._normalize(p) for p in ports]

        async with self._lock:
            for norm, raw in zip(normalized, ports):
                if norm in self._leases:
                    existing = self._leases[norm]
                    raise PortInUseError(raw, existing.owner)

            for norm, raw in zip(normalized, ports):
                self._leases[norm] = PortLease(
                    port=raw, owner=owner, mode=mode, process_id=process_id,
                )

            if process_id:
                self._process_ports[process_id] = normalized

        logger.info("port lock acquired: %s by %s (%s)", ports, owner, mode)

    async def register_process(self, process_id: str, ports: list[str]) -> None:
        normalized = [self._normalize(p) for p in ports]
        async with self._lock:
            for norm in normalized:
                if norm in self._leases:
                    self._leases[norm].process_id = process_id
            self._process_ports[process_id] = normalized

    async def release(self, ports: list[str]) -> None:
        normalized = [self._normalize(p) for p in ports]
        async with self._lock:
            for norm in normalized:
                lease = self._leases.pop(norm, None)
                if lease and lease.process_id:
                    self._process_ports.pop(lease.process_id, None)
        logger.info("port lock released: %s", ports)

    async def release_for_process(self, process_id: str) -> None:
        async with self._lock:
            normalized_ports = self._process_ports.pop(process_id, [])
            for norm in normalized_ports:
                self._leases.pop(norm, None)
        if normalized_ports:
            logger.info("port locks released for process %s", process_id)

    async def release_all(self) -> None:
        async with self._lock:
            self._leases.clear()
            self._process_ports.clear()
        logger.info("all port locks released")

    def is_port_busy(self, port: str) -> tuple[bool, Optional[str]]:
        norm = self._normalize(port)
        lease = self._leases.get(norm)
        if lease:
            return True, lease.owner
        return False, None

    def get_status(self) -> dict[str, dict]:
        return {
            lease.port: {
                "owner": lease.owner,
                "mode": lease.mode,
                "acquired_at": lease.acquired_at.isoformat(),
                "process_id": lease.process_id,
            }
            for lease in self._leases.values()
        }

    @asynccontextmanager
    async def hold(self, ports: list[str], owner: str):
        """``async with port_lock_manager.hold([...], "wiggle"): ...``"""
        await self.acquire(ports, owner, mode="direct")
        try:
            yield
        finally:
            await self.release(ports)


port_lock_manager = PortLockManager()
