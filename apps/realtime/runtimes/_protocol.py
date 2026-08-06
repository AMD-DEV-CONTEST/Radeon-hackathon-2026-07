"""Core protocols, types, and registry for the Runtime abstraction (M6.2).

Separated from __init__.py to avoid circular imports when runtime
implementations (e.g. so101/) need to reference these types and register.

M8: Added CameraSource and camera_sources to RuntimeInfo for vision pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Tuple


class RuntimeReader(Protocol):
    """Read joint positions + optional telemetry from a robot arm."""

    is_connected: bool

    def connect(self) -> bool: ...
    def read_positions(self) -> Optional[List[float]]: ...
    def read_telemetry(self) -> Dict[str, Optional[List[Optional[float]]]]: ...
    def disconnect(self) -> None: ...


class RuntimeWriter(Protocol):
    """Write joint positions to a robot arm with torque gating."""

    is_connected: bool
    torque_enabled: bool

    def connect(self) -> bool: ...
    def preflight(self) -> Tuple[bool, str]: ...
    def enable_torque(self) -> bool: ...
    def disable_torque(self) -> None: ...
    def write_positions(self, joints_rad: Dict[str, float]) -> int: ...
    def disconnect(self) -> None: ...


@dataclass
class CameraSource:
    """Describes a camera that can be attached to a runtime."""

    camera_id: str
    display_name: str
    device_type: str = "usb"          # "usb" | "realsense" | "ip"
    default_device: Optional[str] = None  # e.g. "/dev/video0", "0", IP addr
    width: int = 640
    height: int = 480
    fps: int = 30


@dataclass
class RuntimeInfo:
    """Static metadata about a runtime — used for UI, skill matching, etc."""

    runtime_id: str
    robot_type: str
    display_name: str
    joint_count: int
    joint_names: List[str]
    urdf_url: Optional[str] = None
    supports_telemetry: bool = False
    camera_sources: List[CameraSource] = field(default_factory=list)


# Shared registry dict — lives here so sub-packages can register without
# importing the parent __init__.py (avoids circular import).
RUNTIME_REGISTRY: Dict[str, type] = {}


def register_runtime(runtime_id: str, cls: type) -> None:
    RUNTIME_REGISTRY[runtime_id] = cls


def get_runtime_class(runtime_id: str) -> type:
    if runtime_id not in RUNTIME_REGISTRY:
        available = ", ".join(sorted(RUNTIME_REGISTRY.keys())) or "(none)"
        raise ValueError(f"Unknown runtime '{runtime_id}'. Available: {available}")
    return RUNTIME_REGISTRY[runtime_id]


def list_runtimes() -> List[str]:
    return sorted(RUNTIME_REGISTRY.keys())
