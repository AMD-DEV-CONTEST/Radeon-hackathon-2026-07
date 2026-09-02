def clamp(value: int, lower: int, upper: int) -> int:
    """Return value constrained to the inclusive interval."""
    return min(max(value, lower), upper)
