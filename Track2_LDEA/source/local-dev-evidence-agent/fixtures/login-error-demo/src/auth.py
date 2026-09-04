"""Minimal auth error classifier — demo fixture for LDEA."""

def classify_login_error(code: str | int | None) -> str:
    """Map login failure codes to stable categories.

    Returns one of: invalid_credentials | locked | rate_limited | unknown
    """
    if code is None:
        return "unknown"
    c = str(code).strip().upper()
    if c in {"AUTH_INVALID", "401", "E_BAD_PASS"}:
        return "invalid_credentials"
    if c in {"AUTH_LOCKED", "423", "E_LOCKED"}:
        return "locked"
    if c in {"AUTH_RATE", "429", "E_RATE"}:
        return "rate_limited"
    return "unknown"

# demo note: categories stabilized for product support
