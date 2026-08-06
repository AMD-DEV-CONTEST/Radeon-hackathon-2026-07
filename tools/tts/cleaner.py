import re

GREEK_LETTERS = {
    "alpha": "alpha", "beta": "beta", "gamma": "gamma", "delta": "delta",
    "epsilon": "epsilon", "zeta": "zeta", "eta": "eta", "theta": "theta",
    "iota": "iota", "kappa": "kappa", "lambda": "lambda", "mu": "mu",
    "nu": "nu", "xi": "xi", "pi": "pi", "rho": "rho", "sigma": "sigma",
    "tau": "tau", "upsilon": "upsilon", "phi": "phi", "chi": "chi",
    "psi": "psi", "omega": "omega",
}

# Multi-character commands first so e.g. \sum isn't half-matched by something shorter.
SYMBOL_WORDS = {
    "sum": "the sum of",
    "int": "the integral of",
    "prod": "the product of",
    "partial": "partial",
    "infty": "infinity",
    "nabla": "gradient of",
    "pm": "plus or minus",
    "mp": "minus or plus",
    "times": "times",
    "cdot": "times",
    "div": "divided by",
    "leq": "less than or equal to",
    "geq": "greater than or equal to",
    "neq": "not equal to",
    "approx": "approximately",
    "equiv": "is equivalent to",
    "rightarrow": "goes to",
    "to": "goes to",
    "leftarrow": "comes from",
    "ldots": "and so on",
    "cdots": "and so on",
    "forall": "for all",
    "exists": "there exists",
    "in": "in",
    "subset": "is a subset of",
    "cup": "union",
    "cap": "intersection",
    "emptyset": "the empty set",
}

_FRAC_RE = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT_RE = re.compile(r"\\sqrt(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_SUPERSCRIPT_BRACE_RE = re.compile(r"\^\{([^{}]+)\}")
_SUPERSCRIPT_CHAR_RE = re.compile(r"\^(\w)")
_SUBSCRIPT_BRACE_RE = re.compile(r"_\{([^{}]+)\}")
_SUBSCRIPT_CHAR_RE = re.compile(r"_(\w)")
_LEFTOVER_COMMAND_RE = re.compile(r"\\([a-zA-Z]+)")
_MATH_DELIMITER_RE = re.compile(r"\${1,2}")
_WHITESPACE_RE = re.compile(r"\s+")


def _build_symbol_pattern(words: dict) -> re.Pattern:
    keys_by_length = sorted(words, key=len, reverse=True)
    alternation = "|".join(re.escape(k) for k in keys_by_length)
    return re.compile(r"\\(" + alternation + r")(?![a-zA-Z])")


_GREEK_RE = _build_symbol_pattern(GREEK_LETTERS)
_SYMBOL_RE = _build_symbol_pattern(SYMBOL_WORDS)


def clean_for_tts(text: str) -> str:
    if not text:
        return ""

    try:
        cleaned = text
        cleaned = cleaned.replace("\\[", " ").replace("\\]", " ")
        cleaned = cleaned.replace("\\(", " ").replace("\\)", " ")
        cleaned = _MATH_DELIMITER_RE.sub(" ", cleaned)

        cleaned = _FRAC_RE.sub(lambda m: f"{m.group(1)} over {m.group(2)}", cleaned)
        cleaned = _SQRT_RE.sub(lambda m: f"the square root of {m.group(1)}", cleaned)

        cleaned = _GREEK_RE.sub(lambda m: GREEK_LETTERS[m.group(1)], cleaned)
        cleaned = _SYMBOL_RE.sub(lambda m: SYMBOL_WORDS[m.group(1)], cleaned)

        cleaned = _SUPERSCRIPT_BRACE_RE.sub(lambda m: f" to the power of {m.group(1)} ", cleaned)
        cleaned = _SUPERSCRIPT_CHAR_RE.sub(lambda m: f" to the power of {m.group(1)} ", cleaned)
        cleaned = _SUBSCRIPT_BRACE_RE.sub(lambda m: f" sub {m.group(1)} ", cleaned)
        cleaned = _SUBSCRIPT_CHAR_RE.sub(lambda m: f" sub {m.group(1)} ", cleaned)

        # Any LaTeX command we don't recognize: drop the backslash, keep the word.
        cleaned = _LEFTOVER_COMMAND_RE.sub(lambda m: m.group(1), cleaned)
        cleaned = cleaned.replace("{", " ").replace("}", " ")

        cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
        return cleaned
    except re.error:
        # Should never happen with the fixed patterns above, but a malformed
        # input should degrade to plain whitespace-normalized text, not crash.
        return _WHITESPACE_RE.sub(" ", text).strip()


def split_sentences(text: str, max_chars: int = 220) -> list:
    if not text:
        return []

    raw_sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    raw_sentences = [s for s in raw_sentences if s]
    if not raw_sentences:
        return [text.strip()] if text.strip() else []

    chunks = []
    current = ""
    for sentence in raw_sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)

    # A single sentence longer than max_chars is left intact; better to
    # synthesize one long chunk than to silently drop text.
    return chunks