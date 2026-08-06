from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Literal


InferencePriority = Literal["foreground", "normal", "background"]


@dataclass(frozen=True, slots=True)
class InferenceRequestContext:
    session_id: str
    request_id: str = ""
    priority: InferencePriority | None = None


_CURRENT_INFERENCE_REQUEST: ContextVar[InferenceRequestContext | None] = ContextVar(
    "agentfactory_current_inference_request",
    default=None,
)


@contextmanager
def inference_request_context(
    *,
    session_id: str,
    request_id: str = "",
    priority: InferencePriority | None = None,
) -> Iterator[None]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("inference request session id is required")
    parent = _CURRENT_INFERENCE_REQUEST.get()
    token = _CURRENT_INFERENCE_REQUEST.set(
        InferenceRequestContext(
            session_id=normalized_session_id,
            request_id=str(request_id or (parent.request_id if parent is not None else "")).strip(),
            priority=priority or (parent.priority if parent is not None else None),
        )
    )
    try:
        yield
    finally:
        _CURRENT_INFERENCE_REQUEST.reset(token)


def current_inference_request() -> InferenceRequestContext | None:
    return _CURRENT_INFERENCE_REQUEST.get()
