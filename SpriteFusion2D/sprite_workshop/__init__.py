"""Sprite Workshop: pixel asset pipeline on top of the frozen snapping core.

Importing this package must stay cheap.  Torch is only pulled in when
``recovery`` actually runs, so ``sprite-workshop --help`` and ``doctor`` do not
pay a multi-second import (BACKEND_CLI_PLAN.md 8.1, FRONTEND_PLAN.md 3.1).
"""

from __future__ import annotations

from .errors import (
    BackendUnavailableError,
    ExitCode,
    NotFoundError,
    OperationError,
    RefusedError,
    UsageError,
    WorkshopError,
)
from .model import (
    AssetRef,
    Frame,
    FrameSet,
    OperationReport,
    Point,
    Rect,
    RgbaImage,
    Size,
    WorkshopWarning,
)
from .project import SCHEMA_VERSION, Project

__all__ = [
    "AssetRef",
    "BackendUnavailableError",
    "ExitCode",
    "Frame",
    "FrameSet",
    "NotFoundError",
    "OperationError",
    "OperationReport",
    "Point",
    "Project",
    "Rect",
    "RefusedError",
    "RgbaImage",
    "SCHEMA_VERSION",
    "Size",
    "UsageError",
    "WorkshopError",
    "WorkshopWarning",
]
