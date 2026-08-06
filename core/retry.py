"""CodeRisk Agent - Retry Policy

Unified retry decorator with exponential backoff.
Replaces scattered retry logic across modules.
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Callable, Optional, Type

from rich.console import Console

console = Console()

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0


def retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """Retry decorator with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        exceptions: Tuple of exception types to catch
        on_retry: Optional callback(attempt, delay, exception) called before each retry
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        if on_retry:
                            on_retry(attempt + 1, delay, e)
                        else:
                            console.print(
                                f"[yellow]Retry {attempt + 1}/{max_retries} "
                                f"after {delay:.1f}s: {e}[/]"
                            )
                        time.sleep(delay)
            raise last_err
        return wrapper
    return decorator
