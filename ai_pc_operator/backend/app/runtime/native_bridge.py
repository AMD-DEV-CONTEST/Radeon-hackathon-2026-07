"""Python ctypes bridge to the native C performance core.

Falls back to pure-Python implementations if the C library is unavailable.
All public functions have identical signatures regardless of backend.

Usage:
    from app.runtime.native_bridge import (
        fuzzy_score, levenshtein, rank_elements,
        validate_bounds, xxhash64, rolling_hash
    )
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

# ─── Attempt to load the C library ────────────────────────────

_native = None
_LIB_NAMES = {
    "win32": ["screenai_core.dll"],
    "linux": ["screenai_core.so"],
    "darwin": ["screenai_core.dylib"],
}

def _find_library() -> Optional[ctypes.CDLL]:
    """Try to locate and load the native library."""
    if _native is not None:
        return _native

    names = _LIB_NAMES.get(sys.platform, _LIB_NAMES["linux"])
    base = Path(__file__).resolve().parent.parent.parent / "native"

    for name in names:
        path = base / name
        if path.exists():
            try:
                lib = ctypes.CDLL(str(path))
                _setup_signatures(lib)
                return lib
            except OSError:
                continue

    # Also check env override
    env_path = os.environ.get("SCREENAI_CORE_PATH")
    if env_path:
        try:
            lib = ctypes.CDLL(env_path)
            _setup_signatures(lib)
            return lib
        except OSError:
            pass

    return None


def _setup_signatures(lib: ctypes.CDLL) -> None:
    """Declare C function signatures for type safety."""
    lib.screenai_levenshtein.argtypes = [
        ctypes.c_char_p, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_int,
    ]
    lib.screenai_levenshtein.restype = ctypes.c_int

    lib.screenai_fuzzy_score.argtypes = [
        ctypes.c_char_p, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_int,
    ]
    lib.screenai_fuzzy_score.restype = ctypes.c_double

    lib.screenai_strcasestr.argtypes = [
        ctypes.c_char_p, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_int,
    ]
    lib.screenai_strcasestr.restype = ctypes.c_void_p

    lib.screenai_xxhash64.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint64,
    ]
    lib.screenai_xxhash64.restype = ctypes.c_uint64

    lib.screenai_rolling_hash.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
    ]
    lib.screenai_rolling_hash.restype = ctypes.c_uint64


_native = _find_library()
C_AVAILABLE = _native is not None


# ─── Pure-Python Fallbacks ────────────────────────────────────

def _py_levenshtein(a: str, b: str) -> int:
    """O(m*n) Levenshtein with O(min(m,n)) space."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Ensure a is the longer string
    if len(b) > len(a):
        a, b = b, a

    m, n = len(a), len(b)
    prev = list(range(n + 1))
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        curr[0] = i
        ac = a[i - 1]
        for j in range(1, n + 1):
            cost = 0 if ac == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            )
        prev, curr = curr, prev

    return prev[n]


def _py_fuzzy_score(query: str, target: str) -> float:
    """Weighted fuzzy match: Levenshtein similarity + containment + prefix."""
    q = query.lower()
    t = target.lower()

    if q == t:
        return 1.0

    q_len = len(q)
    t_len = len(t)
    if q_len == 0 or t_len == 0:
        return 0.0

    # Levenshtein similarity
    dist = _py_levenshtein(q, t)
    max_len = max(q_len, t_len)
    lev_sim = 1.0 - (dist / max_len)

    # Containment
    query_in_target = q in t
    target_in_query = t in q

    # Prefix bonus
    prefix_len = min(q_len, t_len)
    prefix_bonus = 0.15 if q[:prefix_len] == t[:prefix_len] else 0.0

    score = (
        lev_sim * 0.55
        + prefix_bonus
        + (0.30 if query_in_target else 0.0)
        + (0.20 if target_in_query else 0.0)
    )

    return max(0.0, min(1.0, score))


def _py_xxhash64(data: bytes, seed: int = 0) -> int:
    """Simplified xxHash-like fast hash (not crypto-secure)."""
    if not data:
        return seed

    h = seed ^ len(data)
    for b in data:
        h = ((h * 1315423911) ^ b) & 0xFFFFFFFFFFFFFFFF
        h = ((h << 31) | (h >> 33)) & 0xFFFFFFFFFFFFFFFF

    # Avalanche
    h ^= h >> 33
    h = (h * 0x14DEF9DEA2F79CD6) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> 29
    h = (h * 0x165667B19E3779F9) & 0xFFFFFFFFFFFFFFFF
    h ^= h >> 32

    return h


def _py_rolling_hash(data: bytes) -> int:
    """Rolling polynomial hash for screen change detection."""
    BASE = 1315423911
    MOD = (1 << 61) - 1
    h = 0
    for b in data:
        h = ((h * BASE) ^ b) % MOD
    return h


def _py_validate_bounds(
    x1: List[int], y1: List[int],
    x2: List[int], y2: List[int],
    is_pane: Optional[List[int]],
    screen_w: int, screen_h: int,
) -> List[int]:
    """Validate element bounds, return indices of valid elements."""
    count = len(x1)
    valid = []
    min_size = 4
    area_total = screen_w * screen_h

    for i in range(count):
        w = x2[i] - x1[i]
        h = y2[i] - y1[i]
        if w < min_size or h < min_size:
            continue
        if x2[i] < 0 or y2[i] < 0 or x1[i] > screen_w or y1[i] > screen_h:
            continue
        elem_area = w * h
        pane = is_pane[i] if is_pane and i < len(is_pane) else 0
        if not pane and elem_area > int(area_total * 0.98):
            continue
        valid.append(i)

    return valid


# ─── Public API (unified) ─────────────────────────────────────

def levenshtein(a: str, b: str) -> int:
    """Edit distance between two strings."""
    if C_AVAILABLE:
        return _native.screenai_levenshtein(
            a.encode("utf-8"), len(a.encode("utf-8")),
            b.encode("utf-8"), len(b.encode("utf-8")),
        )
    return _py_levenshtein(a, b)


def fuzzy_score(query: str, target: str) -> float:
    """Weighted fuzzy match score [0.0, 1.0]."""
    if C_AVAILABLE:
        q_bytes = query.encode("utf-8")
        t_bytes = target.encode("utf-8")
        return _native.screenai_fuzzy_score(
            q_bytes, len(q_bytes),
            t_bytes, len(t_bytes),
        )
    return _py_fuzzy_score(query, target)


def xxhash64(data: bytes, seed: int = 0) -> int:
    """Fast non-cryptographic hash."""
    if C_AVAILABLE:
        buf = (ctypes.c_uint8 * len(data))(*data)
        return _native.screenai_xxhash64(buf, len(data), seed)
    return _py_xxhash64(data, seed)


def rolling_hash(data: bytes) -> int:
    """Rolling hash for incremental change detection."""
    if C_AVAILABLE:
        buf = (ctypes.c_uint8 * len(data))(*data)
        return _native.screenai_rolling_hash(buf, len(data))
    return _py_rolling_hash(data)


def validate_bounds(
    x1: List[int], y1: List[int],
    x2: List[int], y2: List[int],
    is_pane: Optional[List[int]],
    screen_w: int, screen_h: int,
) -> List[int]:
    """Validate element bounds, return indices of valid elements."""
    count = len(x1)
    if count == 0:
        return []

    if C_AVAILABLE:
        arr_x1 = (ctypes.c_int * count)(*x1)
        arr_y1 = (ctypes.c_int * count)(*y1)
        arr_x2 = (ctypes.c_int * count)(*x2)
        arr_y2 = (ctypes.c_int * count)(*y2)
        pane_arr = (ctypes.c_int * count)(*(is_pane or [0] * count))
        out_arr = (ctypes.c_int * count)()
        n = _native.screenai_validate_bounds(
            arr_x1, arr_y1, arr_x2, arr_y2, pane_arr,
            count, screen_w, screen_h, out_arr,
        )
        return [out_arr[i] for i in range(n)]

    return _py_validate_bounds(x1, y1, x2, y2, is_pane, screen_w, screen_h)


def rank_elements(
    elements: List[dict],
    query: str,
    text_getter=None,
) -> int:
    """Rank UI elements by relevance to query. Returns index of best element.

    elements: list of dicts with 'confidence', 'bounds', 'source' keys
    text_getter: optional callable(element) -> str for text extraction
    """
    if not elements:
        return -1

    if text_getter is None:
        text_getter = lambda e: e.get("label", "") or e.get("automation_id", "")

    if C_AVAILABLE and len(elements) > 10:
        count = len(elements)
        conf_arr = (ctypes.c_double * count)(*[
            e.get("confidence", 0.5) for e in elements
        ])
        bx1, by1, bx2, by2 = [], [], [], []
        sr_arr = []
        for e in elements:
            bounds = e.get("bounds", [0, 0, 0, 0])
            bx1.append(bounds[0])
            by1.append(bounds[1])
            bx2.append(bounds[2])
            by2.append(bounds[3])
            sr_arr.append(0 if e.get("source") == "uia" else 1)

        arr_x1 = (ctypes.c_int * count)(*bx1)
        arr_y1 = (ctypes.c_int * count)(*by1)
        arr_x2 = (ctypes.c_int * count)(*bx2)
        arr_y2 = (ctypes.c_int * count)(*by2)
        arr_sr = (ctypes.c_int * count)(*sr_arr)

        # Build a text_match array using fuzzy_score per element
        # (C core uses confidences as combined signal; we pre-compute)
        for i, e in enumerate(elements):
            text = text_getter(e)
            text_match = fuzzy_score(query, text) if text else 0.0
            conf_arr[i] = conf_arr[i] * 0.5 + text_match * 0.5

        class ES(ctypes.Structure):
            _fields_ = [("index", ctypes.c_int), ("score", ctypes.c_double)]

        out_arr = (ES * count)()
        best = _native.screenai_rank_elements(
            query.encode("utf-8"), len(query.encode("utf-8")),
            conf_arr, arr_x1, arr_y1, arr_x2, arr_y2, arr_sr,
            count, out_arr,
        )
        return best

    # Pure-Python fallback
    best_idx = -1
    best_score = -1.0

    for i, e in enumerate(elements):
        text = text_getter(e)
        text_match = fuzzy_score(query, text) if text else 0.0
        confidence = e.get("confidence", 0.5)

        bounds = e.get("bounds", [0, 0, 0, 0])
        w = bounds[2] - bounds[0]
        h = bounds[3] - bounds[1]
        area = w * h if w > 0 and h > 0 else 0
        size_score = min(1.0, area / 50000.0)

        source = e.get("source", "vision")
        source_bonus = 0.12 if source == "uia" else (0.04 if source == "merged" else 0.0)

        score = (
            text_match * 0.62
            + confidence * 0.22
            + size_score * 0.04
            + source_bonus
        )

        if score > best_score:
            best_score = score
            best_idx = i

    return best_idx
