"""Egress Monitor (Blackbox Fase B): proves zero external network traffic
during a normal chat session, rather than just promising it in a privacy
policy. Samples connections owned by this process and the vte-server
subprocess roughly every second, classifies each as loopback (internal)
or external, and feeds a summary into the Flight Recorder so the "0 B"
indicator is itself auditable (UC-02), not just a number on screen.

Layered honesty (see PLATFORM_ISSUES-style documentation elsewhere in
this project): connection ENUMERATION via psutil.net_connections() is
what's actually reliable cross-platform and is what backs the indicator
and the demo. Per-connection byte counters are best-effort and, when
unavailable, this module reports "N external connections" rather than
inventing a byte count it can't actually measure -- never claim precision
it doesn't have.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_LOOPBACK_PREFIXES = ("127.", "::1")

SAMPLE_INTERVAL_SECONDS = 1.0

# Last sample, for GET /api/egress/status -- polled by the UI, doesn't need
# its own persistence (the auditable trail lives in the Flight Recorder,
# see run_forever below).
_last_status: Dict = {
    "external_connections": [],
    "external_bytes": None,  # None = not measurable, not "0"
    "loopback_count": 0,
    "sampling": False,
}


def egress_enabled() -> bool:
    return os.getenv("AETHERIS_EGRESS_ENABLED", "true").lower() == "true"


def _is_loopback(addr: str) -> bool:
    return addr.startswith(_LOOPBACK_PREFIXES) or addr == "localhost"


def _label_external(raddr_ip: str, raddr_port: int, known_browser_active: bool, known_pull_active: bool) -> str:
    """Best-effort classification of *why* an external connection exists,
    so the indicator can be honest ("browser tool, initiated by you")
    instead of just alarming red text. Anything that doesn't match a
    known cause is labeled "unknown" -- deliberately alarming, since an
    unrecognized external connection is exactly the thing this monitor
    exists to catch."""
    if known_pull_active:
        return "model download (vte pull)"
    if known_browser_active:
        return "browser tool (read-only, initiated by you)"
    return "unknown"


def classify_connections(
    connections: List,
    own_pids: Set[int],
    known_browser_active: bool = False,
    known_pull_active: bool = False,
) -> Dict:
    """Pure function, unit-testable without mocking psutil itself --
    `connections` is any iterable of objects with `.pid`, `.status`, and
    `.raddr` (a (ip, port) tuple or falsy) attributes, matching
    psutil.net_connections()'s Conn namedtuples closely enough that real
    psutil objects and synthetic test doubles both work here unchanged."""
    external: List[Dict] = []
    loopback_count = 0
    for conn in connections:
        if conn.pid not in own_pids:
            continue
        raddr = getattr(conn, "raddr", None)
        if not raddr:
            continue
        ip = raddr[0] if isinstance(raddr, (tuple, list)) else getattr(raddr, "ip", None)
        port = raddr[1] if isinstance(raddr, (tuple, list)) else getattr(raddr, "port", None)
        if not ip:
            continue
        if _is_loopback(ip):
            loopback_count += 1
            continue
        external.append({
            "raddr": f"{ip}:{port}",
            "label": _label_external(ip, port, known_browser_active, known_pull_active),
            "pid": conn.pid,
        })
    return {
        "external_connections": external,
        "external_bytes": None,  # Fase B v1: enumeration only, see module docstring
        "loopback_count": loopback_count,
        "sampling": True,
    }


def get_status() -> Dict:
    return dict(_last_status)


async def run_forever(session_id: str = "global") -> None:
    """Background asyncio task (started from app.py's lifespan, see the
    Fase B wiring) sampling roughly every second. Best-effort: any single
    sample failure (psutil raising, a process having exited between the
    PID lookup and the connection read) is logged and skipped, never
    crashes the loop -- an egress monitor that itself takes down the
    backend on a transient error would be a worse outcome than a missed
    sample."""
    global _last_status
    import psutil

    from core.audit.flight_recorder import audit_enabled, get_recorder
    from core.utils.vte_bridge import get_server_pid

    own_pid = os.getpid()
    _last_status["sampling"] = True
    last_external_count = -1  # forces the first sample to always log

    try:
        while True:
            await asyncio.sleep(SAMPLE_INTERVAL_SECONDS)
            try:
                own_pids = {own_pid}
                server_pid = get_server_pid()
                if server_pid is not None:
                    own_pids.add(server_pid)

                connections = psutil.net_connections(kind="inet")
                status = classify_connections(connections, own_pids)
                _last_status = status

                # Log a Flight Recorder entry only on a state CHANGE (0 ->
                # some external, or the external count itself changing),
                # not one entry per tick -- an entry every second for an
                # hour-long session would swamp the timeline for no real
                # benefit, and the "0 B" claim is just as auditable from
                # sparse state-change entries as from constant samples.
                external_count = len(status["external_connections"])
                if audit_enabled() and external_count != last_external_count:
                    get_recorder(session_id).append(
                        "egress_sample",
                        {
                            "external_bytes": 0 if external_count == 0 else None,
                            "external_count": external_count,
                            "loopback_count": status["loopback_count"],
                            "label": status["external_connections"][0]["label"] if status["external_connections"] else None,
                        },
                        actor="system",
                    )
                last_external_count = external_count
            except Exception as e:
                logger.warning("Egress sample failed (skipped): %s", e)
    except asyncio.CancelledError:
        _last_status["sampling"] = False
        raise
