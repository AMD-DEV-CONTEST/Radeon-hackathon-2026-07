"""Statistical helpers for the pycalc demo package."""


def mode(values):
    """Return the most frequent value; ties return the smaller value."""
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    best = None
    best_count = -1
    for value, count in counts.items():
        if count > best_count:
            best = value
            best_count = count
    return best


def normalize(values):
    """Scale numeric values to [0, 1] using min-max scaling."""
    if not values:
        return []
    low = min(values)
    high = max(values)
    return [round(value / high, 4) for value in values]
