"""Tests for spoken-form normalization (policycut/audio/spoken.py).

Contract: spoken digit words are collapsed into contiguous digits
("zero one two" -> "012"), "dot"/"at" reconstruct emails, and a
char -> word-index map ties every normalized character back to the source
word (so PII regex hits can be mapped to word timestamps).

The exact function name is not pinned by CONTRACTS.md, so this test locates
the normalizer through a small adapter over the module's public callables.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import policycut.audio.spoken as spoken_mod

_FN_CANDIDATES = [
    "normalize_spoken",
    "normalize_spoken_words",
    "normalize_spoken_text",
    "normalize_words",
    "build_normalized_text",
    "spoken_to_normalized",
    "normalize",
]


def _find_normalizer():
    for name in _FN_CANDIDATES:
        fn = getattr(spoken_mod, name, None)
        if callable(fn):
            return fn
    # last resort: any public callable mentioning "normal" or "spoken"
    for name in dir(spoken_mod):
        if name.startswith("_"):
            continue
        fn = getattr(spoken_mod, name)
        if callable(fn) and not inspect.isclass(fn) and ("normal" in name or "spoken" in name):
            return fn
    pytest.fail(
        f"no spoken-form normalizer found in policycut.audio.spoken "
        f"(tried {_FN_CANDIDATES})"
    )


def _unpack(out):
    """Extract (normalized_text, char_map) from various return shapes."""
    if isinstance(out, tuple) and len(out) >= 2 and isinstance(out[0], str):
        return out[0], out[1]
    if isinstance(out, str):
        return out, None
    if isinstance(out, dict):
        text = out.get("text") or out.get("normalized") or out.get("normalized_text")
        cmap = out.get("char_map") or out.get("char_to_word") or out.get("map")
        if text is not None:
            return text, cmap
    for text_attr in ("text", "normalized", "normalized_text"):
        if hasattr(out, text_attr):
            text = getattr(out, text_attr)
            for map_attr in ("char_map", "char_to_word", "char_to_word_map", "map"):
                if hasattr(out, map_attr):
                    return text, getattr(out, map_attr)
            return text, None
    return None, None


def normalize(words: list[str]):
    """Call the normalizer with whatever word representation it accepts."""
    fn = _find_normalizer()
    attempts = [
        words,
        [
            {"text": w, "word": w, "start": i * 0.5, "end": i * 0.5 + 0.4,
             "start_s": i * 0.5, "end_s": i * 0.5 + 0.4}
            for i, w in enumerate(words)
        ],
        [
            SimpleNamespace(text=w, word=w, start=i * 0.5, end=i * 0.5 + 0.4,
                            start_s=i * 0.5, end_s=i * 0.5 + 0.4)
            for i, w in enumerate(words)
        ],
        " ".join(words),
    ]
    last_exc = None
    for arg in attempts:
        try:
            out = fn(arg)
        except Exception as exc:  # try the next input shape
            last_exc = exc
            continue
        text, cmap = _unpack(out)
        if text is not None:
            return text, cmap
    pytest.fail(f"could not invoke spoken normalizer with any input shape: {last_exc}")


def _map_entry_to_word_index(entry, words: list[str]) -> int | None:
    """char_map entries may be int word indices or word-like objects."""
    if isinstance(entry, int):
        return entry
    if isinstance(entry, dict):
        start = entry.get("start", entry.get("start_s"))
    else:
        start = getattr(entry, "start", getattr(entry, "start_s", None))
    if start is not None:
        # conftest-style synthetic timing: word i starts at i * 0.5
        return round(float(start) / 0.5)
    return None


class TestDigits:
    def test_spoken_digits_become_contiguous(self):
        text, _ = normalize("zero one two".split())
        assert "012" in text.replace(" ", "") or "012" in text
        # contract example is contiguous "012"
        assert "012" in text

    def test_full_digit_vocabulary(self):
        words = "zero one two three four five six seven eight nine".split()
        text, _ = normalize(words)
        assert "0123456789" in text

    def test_digits_embedded_in_sentence(self):
        words = "my number is five five five zero one two three four".split()
        text, _ = normalize(words)
        assert "55501234" in text
        # surrounding normal words survive normalization
        assert "number" in text.lower()


class TestDoubleTriple:
    def test_double(self):
        text, _ = normalize(["double", "five"])
        assert "55" in text

    def test_triple(self):
        text, _ = normalize(["triple", "seven"])
        assert "777" in text

    def test_double_in_sequence(self):
        text, _ = normalize("five double three nine".split())
        assert "5339" in text


class TestEmailReconstruction:
    def test_dot_at_email(self):
        words = "john dot smith at example dot com".split()
        text, _ = normalize(words)
        compact = text.replace(" ", "")
        assert "john.smith@example.com" in compact

    def test_at_and_dot_symbols_present(self):
        text, _ = normalize("jane at mail dot org".split())
        compact = text.replace(" ", "")
        assert "jane@mail.org" in compact


class TestCharWordMap:
    def test_map_covers_normalized_text(self):
        words = "my number is five five five zero one two three four".split()
        text, cmap = normalize(words)
        assert cmap is not None, "normalizer must return a char->word map"
        assert len(cmap) >= len(text.rstrip()), (
            f"char map length {len(cmap)} shorter than text length {len(text)}"
        )

    def test_digit_chars_map_to_digit_words(self):
        words = "my number is five five five zero one two three four".split()
        # digit words occupy word indices 3..10
        text, cmap = normalize(words)
        assert cmap is not None
        idx = text.index("55501234")
        first = _map_entry_to_word_index(cmap[idx], words)
        last = _map_entry_to_word_index(cmap[idx + 7], words)
        assert first is not None and last is not None
        assert first == 3, f"first digit char should map to word 3 ('five'), got {first}"
        assert last == 10, f"last digit char should map to word 10 ('four'), got {last}"

    def test_plain_words_map_to_own_indices(self):
        words = ["hello", "world"]
        text, cmap = normalize(words)
        assert cmap is not None
        assert "hello" in text and "world" in text
        h = text.index("hello")
        w = text.index("world")
        assert _map_entry_to_word_index(cmap[h], words) == 0
        assert _map_entry_to_word_index(cmap[w], words) == 1

    def test_email_map_endpoints(self):
        words = "john dot smith at example dot com".split()
        text, cmap = normalize(words)
        assert cmap is not None
        compact = text.replace(" ", "")
        assert "john.smith@example.com" in compact
        j = text.index("john")
        first = _map_entry_to_word_index(cmap[j], words)
        assert first == 0
        # last char of "com" maps to the final word
        m = text.rindex("com") + 2
        last = _map_entry_to_word_index(cmap[m], words)
        assert last == len(words) - 1
