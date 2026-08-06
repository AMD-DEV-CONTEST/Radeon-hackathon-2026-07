"""Session handlers: implementation of the analysis/resize handlers."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def choose_strategy(
    full_context: Any,
    context_window: Any,
    memo: Any,
    settings: dict,
) -> str | None:
    """analysis handler: determine whether the window needs processing.

    Args:
        full_context: the complete conversation history
        context_window: the current window
        memo: the current memo
        settings: the configuration

    Returns:
        the strategy name (e.g., "key_fields_compress") or None
    """
    max_length = settings.get("session", {}).get("max_length", 500)
    window_len = len(context_window) if context_window else 0

    if window_len >= 7:
        logger.info("window length %d >= 7, triggering compression", window_len)
        return settings.get("session", {}).get("default_strategy", "key_fields_compress")

    return None


async def key_fields_compress(
    full_context: Any,
    context_window: Any,
    memo: Any,
    settings: dict,
) -> tuple:
    """resize handler: key-field compression, keeping constraints + ref.

    Note: the full version should call the model for compression. A simplified version is implemented here first.

    Args:
        full_context: the complete conversation history
        context_window: the current window
        memo: the current memo
        settings: the configuration

    Returns:
        (new_full_context, new_context_window, new_memo)
    """
    if context_window is None:
        return None, None, memo

    # simplified version: keep the most recent 3 items, extract key fields from the rest
    recent = list(context_window[-3:]) if len(context_window) > 3 else list(context_window)

    new_memo = {
        "confirmed_constraints": [],
        "open_questions": [],
        "workspace_refs": [],
        "compressed_turns": len(context_window) - len(recent),
    }

    logger.info("compressed window: %d → %d items", len(context_window), len(recent))
    return None, recent, new_memo