"""Runtime abstraction layer (M6.2).

A Runtime encapsulates everything needed to talk to a specific robot hardware:
- reader: read joint positions + telemetry from the physical arm
- writer: write Goal_Position to the arm, manage torque
- metadata: joint count, URDF path, robot_type string

The first (and default) runtime is SO-101 (`runtimes/so101/`).
To add a new robot, create `runtimes/<name>/` and implement these protocols.

Usage::

    from runtimes import get_runtime_class, list_runtimes

    runtimes = list_runtimes()          # ["so101"]
    SO101 = get_runtime_class("so101")
    reader = SO101.create_reader(port="COM3")
    writer = SO101.create_writer(port="COM5")
"""
from __future__ import annotations

from ._protocol import (  # noqa: F401
    RuntimeInfo,
    RuntimeReader,
    RuntimeWriter,
    register_runtime,
    get_runtime_class,
    list_runtimes,
)


def _auto_register() -> None:
    """Import built-in runtimes so they self-register."""
    try:
        from .so101 import SO101Runtime  # noqa: F401
    except ImportError:
        pass
    try:
        from .reachy_mini import ReachyMiniRuntime  # noqa: F401
    except ImportError:
        pass
    try:
        from .b601_rs import B601RSRuntime  # noqa: F401
    except ImportError:
        pass
    try:
        from .lekiwi import LeKiwiRuntime  # noqa: F401
    except ImportError:
        pass


_auto_register()
