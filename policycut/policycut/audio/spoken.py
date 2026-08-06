"""Normalization of spoken-form PII tokens (pure python, no dependencies).

Converts a list of transcript word strings into a normalized string where
spoken digit words become digits and spoken symbol words become symbols,
so that regexes for phone numbers / emails match spoken PII:

    ["five", "five", "five", "dash", "one", "two", "one", "two"]
        -> "555-1212"
    ["john", "dot", "doe", "at", "gmail", "dot", "com"]
        -> "john.doe@gmail.com"

Both public functions return ``(string, char_map)`` where ``char_map[i]`` is
the index (into the input ``words`` list) of the word that produced character
``i`` of the string. Separator characters map to the previous word's index.

Joining rules for the normalized string:
- adjacent digit pieces are glued together   ("one two"      -> "12")
- symbol pieces glue to both neighbours      ("a at b"       -> "a@b")
- everything else is separated by one space  ("my address"   -> "my address")
"""

from __future__ import annotations

import re

# Spoken digit words -> digit characters. "oh" is the spoken zero.
DIGIT_WORDS: dict[str, str] = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

# "double five" -> "55", "triple seven" -> "777"
MULTIPLIER_WORDS: dict[str, int] = {"double": 2, "triple": 3}

# Spoken symbol words -> symbol characters.
SYMBOL_WORDS: dict[str, str] = {
    "dot": ".",
    "point": ".",
    "at": "@",
    "dash": "-",
    "hyphen": "-",
    "minus": "-",
    "underscore": "_",
}

_EDGE_PUNCT_RE = re.compile(r"^\W+|\W+$")
_DIGITISH_RE = re.compile(r"[0-9()+.\-]*[0-9][0-9()+.\-]*")


def _clean(token: str) -> str:
    """Lowercase and strip leading/trailing punctuation (keeps internal chars)."""
    return _EDGE_PUNCT_RE.sub("", str(token).strip().lower())


def _classify(token: str) -> tuple[str | None, str]:
    """Return (kind, normalized_piece) for one raw token.

    kind is one of "digit", "symbol", "word", or None (token is pure
    punctuation / empty and should be skipped).
    """
    t = str(token).strip().lower()
    if t in ("@", ".", "-", "_"):
        return "symbol", t
    core = _EDGE_PUNCT_RE.sub("", t)
    if not core:
        return None, ""
    if core in DIGIT_WORDS:
        return "digit", DIGIT_WORDS[core]
    if core in SYMBOL_WORDS:
        return "symbol", SYMBOL_WORDS[core]
    if _DIGITISH_RE.fullmatch(core):
        return "digit", core
    return "word", core


def _needs_space(prev_kind: str | None, kind: str) -> bool:
    if prev_kind is None:
        return False
    if prev_kind == "symbol" or kind == "symbol":
        return False
    if prev_kind == "digit" and kind == "digit":
        return False
    return True


def normalize_spoken(words: list[str]) -> tuple[str, list[int]]:
    """Normalize spoken-form tokens into a matchable string.

    Returns (normalized_string, char_map) where char_map[i] is the input word
    index responsible for character i. Empty/punctuation-only tokens are
    skipped; "double"/"triple" followed by a digit word consume both tokens.
    """
    chars: list[str] = []
    cmap: list[int] = []
    prev_kind: str | None = None
    i = 0
    n = len(words)
    while i < n:
        core = _clean(words[i])
        # "double five" / "triple seven" -> repeated digit
        if core in MULTIPLIER_WORDS and i + 1 < n:
            nk, npiece = _classify(words[i + 1])
            if nk == "digit" and len(npiece) == 1:
                count = MULTIPLIER_WORDS[core]
                if _needs_space(prev_kind, "digit"):
                    chars.append(" ")
                    cmap.append(cmap[-1])
                for rep in range(count):
                    chars.append(npiece)
                    # first repetition attributed to the multiplier word,
                    # the rest to the digit word, for tight timestamps.
                    cmap.append(i if rep == 0 else i + 1)
                prev_kind = "digit"
                i += 2
                continue
        kind, piece = _classify(words[i])
        if kind is None or not piece:
            i += 1
            continue
        if _needs_space(prev_kind, kind):
            chars.append(" ")
            cmap.append(cmap[-1])
        for ch in piece:
            chars.append(ch)
            cmap.append(i)
        prev_kind = kind
        i += 1
    return "".join(chars), cmap


def join_raw(words: list[str]) -> tuple[str, list[int]]:
    """Join raw tokens with single spaces, with the same char->word mapping.

    Token text is preserved verbatim (only surrounding whitespace stripped),
    so standard regexes (formatted phone numbers, literal emails) match.
    """
    chars: list[str] = []
    cmap: list[int] = []
    for idx, word in enumerate(words):
        text = str(word).strip()
        if not text:
            continue
        if chars:
            chars.append(" ")
            cmap.append(cmap[-1])
        for ch in text:
            chars.append(ch)
            cmap.append(idx)
    return "".join(chars), cmap
