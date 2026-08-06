"""Performance timing utilities."""

import logging
import time
from collections.abc import Callable
from functools import wraps

logger = logging.getLogger(__name__)


def timing(func: Callable | None = None, *, name: str | None = None):
    """Decorator that logs function execution time.

    Usage:
        @timing
        def slow_func(): ...

        @timing(name="custom_label")
        def another(): ...
    """

    def decorator(fn: Callable):
        label = name or fn.__name__

        @wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = fn(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger.debug("%s took %.3fs", label, elapsed)
            return result

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
