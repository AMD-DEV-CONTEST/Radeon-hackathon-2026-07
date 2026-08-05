"""Text summary rendering for pycalc."""


def summary_text(values, title="Summary"):
    """Return a short multi-line summary of the dataset."""
    lines = []
    lines.append(f"# {title}")
    if not values:
        lines.append("(empty)")
        return "\n".join(lines)
    from pycalc.analysis import mode, normalize

    lines.append(f"- values: {len(values)}")
    lines.append(f"- mode: {mode(values)}")
    normalized = [str(value) for value in normalize(values)]
    lines.append("- normalized: " + ", ".join(normalized[:5]))
    return "\n".join(lines)
