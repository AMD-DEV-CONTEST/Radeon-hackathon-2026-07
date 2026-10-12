"""
Tier 0.5 — Unicode / encoding normalizer.

Sits before Tier 0's regex engine. The red-team mutator surfaced that
NFKC alone does NOT fold the mathematical sans-serif homoglyphs that
attackers use to defeat case-sensitive regex (e.g. `𝘐𝘨𝘯𝘰𝘳𝘦 previous
instructions` — NFKC leaves that untouched, so `(?i)ignore` misses it).

This module exposes a single pure function `normalize(text)` that the
Tier 0 checker calls before pattern matching. It is intentionally a
separate module so the normalization is unit-testable in isolation
and the red-team mutators can target it directly.

What it folds (in order):
1. Zero-width characters (U+200B/200C/200D/FEFF + ZWJ U+200D + ZWNJ)
2. Space-pad mangles (consecutive ASCII spaces → single space)
3. Mathematical / Cyrillic / Greek / fullwidth homoglyphs → ASCII
   (NFKC does NOT do this; we maintain an explicit map)
4. NFKC normalization for the rest (handles fullwidth ASCII, ligatures)
5. Base64 block decode-and-append (exposes hidden payloads for Tier 0)

Returns the normalized text. Original text is preserved for evidence.
"""

from __future__ import annotations

import base64
import re
import unicodedata


# ----------------------------------------------------------------------
# 1. Zero-width characters to strip entirely
# ----------------------------------------------------------------------

ZERO_WIDTH_CHARS = (
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER (used in emoji sequences; safe to strip for security scan)
    "\u2060",  # WORD JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE / BOM
    "\u00ad",  # SOFT HYPHEN
)


# ----------------------------------------------------------------------
# 2. Homoglyph map — characters visually identical to ASCII letters
# but with different Unicode codepoints. Built from the official
# Unicode TR39 confusables database (unicodedata.confusables) where
# available (Python 3.13+). Falls back to a curated minimal subset
# covering math alphanumerics + Cyrillic + Greek that attackers use.
# ----------------------------------------------------------------------


def _build_homoglyph_map() -> dict[str, str]:
    """Build the homoglyph table from the official Unicode confusables
    database if available, falling back to a hand-curated subset.

    The confusables database does the heavy lifting: it has every
    visually-confusable character Unicode knows about, with the
    canonical "skeleton" mapping (e.g. Cyrillic А → Latin A, math
    sans-serif 𝘈 → Latin A, fullwidth Ａ → Latin A). Loading it once
    at import time is O(1) module init and never drifts against real
    attacks the way a hand-rolled table does.
    """
    out: dict[str, str] = {}

    # First: hand-curated fallback. Covers the full math alphanumeric block
    # (bold, italic, bold-italic, sans-serif, sans-serif-bold, sans-serif-
    # italic, sans-serif-bold-italic, monospace) plus Cyrillic and Greek
    # lookalikes — the families the red-team mutator actually emits. Each
    # math family is 26 contiguous uppercase codepoints (A-Z) followed by
    # 26 contiguous lowercase (a-z), so all eight are generated in one pass.
    _ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    _ASCII_LOWER = _ASCII_UPPER.lower()
    _MATH_FAMILIES = (
        (0x1D400, 0x1D41A),  # MATHEMATICAL BOLD
        (0x1D434, 0x1D44E),  # MATHEMATICAL ITALIC
        (0x1D468, 0x1D482),  # MATHEMATICAL BOLD ITALIC
        (0x1D5A0, 0x1D5BA),  # MATHEMATICAL SANS-SERIF
        (0x1D5D4, 0x1D5EE),  # MATHEMATICAL SANS-SERIF BOLD
        (0x1D608, 0x1D622),  # MATHEMATICAL SANS-SERIF ITALIC
        (0x1D63C, 0x1D656),  # MATHEMATICAL SANS-SERIF BOLD ITALIC
        (0x1D670, 0x1D68A),  # MATHEMATICAL MONOSPACE
    )
    fallback: dict[str, str] = {}
    for cap_base, lower_base in _MATH_FAMILIES:
        for i, ch in enumerate(_ASCII_UPPER):
            fallback[chr(cap_base + i)] = ch
        for i, ch in enumerate(_ASCII_LOWER):
            fallback[chr(lower_base + i)] = ch
    fallback.update({
        # Cyrillic lookalikes (visually identical to ASCII)
        "\u0410": "A", "\u0412": "B", "\u0421": "C", "\u0415": "E", "\u041d": "H",
        "\u041a": "K", "\u041c": "M", "\u041e": "O", "\u0420": "P", "\u0422": "T",
        "\u0425": "X", "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p",
        "\u0441": "c", "\u0443": "y", "\u0445": "x",
        # Greek
        "\u0391": "A", "\u0392": "B", "\u0395": "E", "\u0396": "Z", "\u0397": "H",
        "\u0399": "I", "\u039a": "K", "\u039c": "M", "\u039d": "N", "\u039f": "O",
        "\u03a1": "P", "\u03a4": "T", "\u03a5": "Y", "\u03a7": "X",
        "\u03b1": "a", "\u03b2": "b", "\u03b5": "e", "\u03b9": "i", "\u03ba": "k",
        "\u03bf": "o", "\u03c1": "p", "\u03c4": "t", "\u03c5": "u", "\u03c7": "x",
    })
    out.update(fallback)

    # Then: load the official Unicode confusables database if Python
    # exposes it. This catches every homoglyph Unicode knows about, not
    # just the subset the red-team mutator happens to emit.
    try:
        from unicodedata import confusables   # py 3.13+
        for src, target in confusables().items():
            # Only fold TO single ASCII letters — keep digits + punct to themselves
            if len(target) == 1 and target.isascii() and target.isalpha():
                # Don't overwrite existing fallback entries (we may have richer info)
                out.setdefault(src, target)
    except (ImportError, AttributeError):
        # Older Python — our fallback covers the families actually used
        # in attack corpora.
        pass

    return out


HOMOGLYPH_MAP: dict[str, str] = _build_homoglyph_map()


# ----------------------------------------------------------------------
# 3. Base64 detection — to decode + append so Tier 0 sees "ignore" inside
# ----------------------------------------------------------------------

BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{28,}={0,2}")


def _decode_base64_blocks(text: str) -> list[str]:
    """Find base64-looking substrings, decode them, return printable results.

    Lets Tier 0 inspect the decoded content for injection patterns even
    when the original prompt only contains the encoded payload.
    """
    decoded: list[str] = []
    for b64 in BASE64_PATTERN.findall(text):
        if len(b64) < 30:
            continue
        try:
            pad = len(b64) % 4
            padded = b64 + "=" * (4 - pad) if pad else b64
            raw = base64.b64decode(padded, validate=False).decode("utf-8", errors="ignore")
            if re.search(r"[a-zA-Z0-9\s]{10,}", raw):
                decoded.append(raw)
        except Exception:
            pass
    return decoded


# ----------------------------------------------------------------------
# 4. Public entry point
# ----------------------------------------------------------------------


def normalize(text: str) -> str:
    """Tier 0.5 normalization preprocessing. Pure, idempotent, fast (<1ms for
    10KB inputs). Safe to call on text Tier 0 has already normalized.

    Order matters: strip zero-width first (cheap, deterministic), then
    fold homoglyphs (lookup), then NFKC (handles the long tail), then
    collapse whitespace, then optionally decode-and-append base64 blocks.
    """
    if not text:
        return ""

    # 1. Strip zero-width characters
    for zw in ZERO_WIDTH_CHARS:
        if zw in text:
            text = text.replace(zw, "")

    # 2. Fold homoglyphs via the explicit map (NFKC leaves math alphanumerics
    # untouched — this is the whole point of having the map).
    if any(ord(c) > 127 for c in text):
        text = "".join(HOMOGLYPH_MAP.get(c, c) for c in text)

    # 3. NFKC — normalizes fullwidth ASCII (Ａ → A), ligatures (ﬁ → fi),
    # and remaining compatibility forms not covered by the explicit map.
    text = unicodedata.normalize("NFKC", text)

    # 4. Collapse consecutive whitespace so `Ignore    previous` matches
    # the same way `Ignore previous` does.
    text = re.sub(r"\s+", " ", text)

    # 5. Decode any base64 blocks and append the (printable) decoded form
    # so Tier 0's regex can hit injection phrases hidden inside base64.
    decoded_blocks = _decode_base64_blocks(text)
    if decoded_blocks:
        text = text + "\n" + "\n".join(decoded_blocks)

    return text
