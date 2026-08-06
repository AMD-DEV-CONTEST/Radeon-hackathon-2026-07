from __future__ import annotations

import hashlib
from typing import Any


def scheduler_run_session_id(
    job: Any,
    run: Any,
    *,
    namespace: str,
) -> str:
    """Return an internal, non-conversation session id for one scheduler run."""
    identity = "\x00".join(
        (
            str(getattr(job, "owner_type", "") or ""),
            str(getattr(job, "owner_id", "") or ""),
            str(getattr(job, "job_id", "") or ""),
            str(getattr(run, "run_id", "") or ""),
            namespace.strip(),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"scheduler_{digest}"
