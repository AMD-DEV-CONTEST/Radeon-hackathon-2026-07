"""Short unique id generation (contract section 0).

Prefixes: ``p_`` projects, ``e_`` events, ``j_`` jobs, ``t_`` tracks.
"""

from __future__ import annotations

import uuid

__all__ = ["new_id", "new_project_id", "new_event_id", "new_job_id", "new_track_id"]


def new_id(prefix: str) -> str:
    """Return ``prefix`` + 10 hex chars from a random UUID4.

    Accepts the prefix with or without the trailing underscore
    (``new_id("e")`` and ``new_id("e_")`` both yield ``e_xxxxxxxxxx``).
    """
    if not prefix.endswith("_"):
        prefix = prefix + "_"
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def new_project_id() -> str:
    return new_id("p_")


def new_event_id() -> str:
    return new_id("e_")


def new_job_id() -> str:
    return new_id("j_")


def new_track_id() -> str:
    return new_id("t_")
