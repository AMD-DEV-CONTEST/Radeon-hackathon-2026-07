"""tests/test_determinex_atomic_io.py — canonical atomic write/read helpers.

determinex_atomic_io.py replaces the byte-for-byte-identical write_text_atomic/
write_json_atomic pair independently copy-pasted into pb_pool_status.py and
pb_missing_intake.py. Covers real writes, the tenacity-backed retry-on-
PermissionError path, and load_json_with_retry's empty/malformed/missing-file
semantics (preserved exactly from the original hand-rolled pb_pool_status.py
`load()`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from determinex_atomic_io import (  # noqa: E402
    load_json_with_retry,
    write_json_atomic,
    write_text_atomic,
)


def test_write_text_atomic_creates_parent_dirs_and_writes(tmp_path):
    p = tmp_path / "sub" / "dir" / "out.txt"
    write_text_atomic(p, "hello world")
    assert p.read_text(encoding="utf-8") == "hello world"


def test_write_json_atomic_round_trips(tmp_path):
    p = tmp_path / "out.json"
    write_json_atomic(p, {"a": 1, "b": [1, 2, 3]})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "b": [1, 2, 3]}


def test_write_text_atomic_no_leftover_temp_file(tmp_path):
    p = tmp_path / "out.txt"
    write_text_atomic(p, "content")
    leftovers = [f for f in tmp_path.iterdir() if f != p]
    assert leftovers == [], f"temp file(s) left behind: {leftovers}"


def test_write_retries_past_transient_permission_error(tmp_path, monkeypatch):
    calls = {"n": 0}
    real_replace = Path.replace

    def flaky_replace(self, target):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("simulated transient lock")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    p = tmp_path / "flaky.txt"
    write_text_atomic(p, "retried ok")
    assert p.read_text(encoding="utf-8") == "retried ok"
    assert calls["n"] == 3


def test_write_exhausts_retries_and_reraises(tmp_path, monkeypatch):
    calls = {"n": 0}

    def always_fail(self, target):
        calls["n"] += 1
        raise PermissionError("permanently locked")

    monkeypatch.setattr(Path, "replace", always_fail)
    p = tmp_path / "stuck.txt"
    with pytest.raises(PermissionError):
        write_text_atomic(p, "never")
    assert calls["n"] == 10


def test_load_json_with_retry_missing_file_returns_default(tmp_path):
    assert load_json_with_retry(tmp_path / "missing.json", {"fallback": True}) == {"fallback": True}


def test_load_json_with_retry_empty_file_returns_default(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    assert load_json_with_retry(p, {"fallback": True}) == {"fallback": True}


def test_load_json_with_retry_parses_real_content(tmp_path):
    p = tmp_path / "real.json"
    p.write_text(json.dumps({"z": 3}), encoding="utf-8")
    assert load_json_with_retry(p, None) == {"z": 3}


def test_load_json_with_retry_reraises_on_persistent_malformed_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_json_with_retry(p, None)


def test_load_json_with_retry_recovers_from_transient_empty_read(tmp_path):
    """Simulates reading mid-write: first read empty, second read has content."""
    p = tmp_path / "racing.json"
    reads = {"n": 0}
    real_read_text = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        reads["n"] += 1
        if reads["n"] == 1:
            return ""
        return real_read_text(self, *args, **kwargs)

    p.write_text(json.dumps({"ok": True}), encoding="utf-8")
    import determinex_atomic_io as aio

    orig = aio.Path.read_text
    aio.Path.read_text = flaky_read_text
    try:
        result = load_json_with_retry(p, None)
    finally:
        aio.Path.read_text = orig
    assert result == {"ok": True}
    assert reads["n"] == 2
