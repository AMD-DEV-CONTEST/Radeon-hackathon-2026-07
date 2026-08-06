from __future__ import annotations


def exception_leaf_messages(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        messages = [
            message
            for nested in exc.exceptions
            for message in exception_leaf_messages(nested)
        ]
        return list(dict.fromkeys(messages))
    message = str(exc).strip()
    return [f"{type(exc).__name__}: {message}" if message else type(exc).__name__]


def exception_contains(exc: BaseException, exception_type: type[BaseException]) -> bool:
    if isinstance(exc, exception_type):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(exception_contains(nested, exception_type) for nested in exc.exceptions)
    return False


def exception_summary(exc: BaseException) -> str:
    return "; ".join(exception_leaf_messages(exc))
