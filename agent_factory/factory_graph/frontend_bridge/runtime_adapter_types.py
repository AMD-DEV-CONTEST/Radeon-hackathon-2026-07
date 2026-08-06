from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.builtin_packages import DEFAULT_AGENT_PACKAGE_ID


Emit = Callable[[FactoryFrontendEvent], None]
SYSTEM_CHAT_PACKAGE_ID = DEFAULT_AGENT_PACKAGE_ID


@dataclass(slots=True)
class FactoryBridgeOptions:
    show_state: bool = False
    show_messages: bool = True


@dataclass(slots=True)
class PendingAgentPackageRun:
    package_id: str
    session_id: str
    normalizer: RuntimeEventNormalizer
    interrupt_id: str | None = None
    interrupt_event_id: str | None = None
    interrupt_payload: dict[str, Any] = field(default_factory=dict)
    group_id: str | None = None
    group_run_id: str | None = None
    workdir_root: Any | None = None


@dataclass(slots=True)
class PendingCreateAgentRun:
    session_id: str
    factory_session_id: str | None = None
    request_id: str | None = None
    interrupt_id: str | None = None
    interrupt_event_id: str | None = None
    interrupt_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PendingEvolutionRun:
    package_id: str
    session_id: str
    request_id: str | None = None
    trace_id: str | None = None
    interrupt_id: str | None = None
    interrupt_event_id: str | None = None
    interrupt_payload: dict[str, Any] = field(default_factory=dict)
