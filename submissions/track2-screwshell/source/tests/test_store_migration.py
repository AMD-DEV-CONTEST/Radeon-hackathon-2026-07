"""P0.5 schema-migration acceptance tests (TTFT_OPTIMIZATION_PLAN.md).

Issue: ``request_events`` was created by an older relay whose ``_COLS`` did not
yet include ``switch_ms`` (and, separately, ``queue_wait_ms`` was never in
``_COLS`` at all -- the coordinator sets it but store.py dropped it). A DB built
before those columns were added keeps the *old* shape forever, because
``CREATE TABLE IF NOT EXISTS`` never alters an existing table. ``record()`` then
INSERTs the full ``_COLS`` set and the extra columns make the statement either
fail silently (old code, count mismatch) or -- with a naive end-appended
migration -- land in the WRONG column (positional INSERT misalignment).

These tests prove the migration adds the missing columns AND that the named-
column INSERT keeps every value in its correct column.
"""
from __future__ import annotations

import sqlite3

from screwshell.observ import store as store_mod
from screwshell.observ.event import RequestEvent
from screwshell.observ.store import ObservStore, _COLS

# Columns missing from the real instance DB (built before f724f98 + the
# queue_wait_ms omission). This is the 20-column "old schema".
_MISSING = ("switch_ms", "queue_wait_ms")
_OLD_COLS = [c for c in _COLS if c not in _MISSING]


def _create_old_db(path):
    """Hand-build the pre-migration request_events table (no migration)."""
    con = sqlite3.connect(str(path / "requests.db"))
    con.execute(
        "CREATE TABLE request_events ("
        + ", ".join(
            f"{c} TEXT" if c in ("request_id", "run_id", "route",
                                 "adapter", "model", "error")
            else f"{c} REAL"
            for c in _OLD_COLS)
        + ")")
    con.commit()
    return con


def _cols_of(db_path):
    con = sqlite3.connect(str(db_path / "requests.db"))
    cols = [r[1] for r in con.execute("PRAGMA table_info(request_events)")]
    con.close()
    return cols


def test_migration_adds_missing_columns(tmp_path):
    _create_old_db(tmp_path)
    before = _cols_of(tmp_path)
    assert "switch_ms" not in before
    assert "queue_wait_ms" not in before

    store = ObservStore(str(tmp_path))
    assert store.enabled is True

    after = _cols_of(tmp_path)
    for c in _MISSING:
        assert c in after, f"migration failed to add {c}"
    # every _COLS column now present
    assert set(_COLS).issubset(set(after))
    # added columns are REAL so floats persist
    con = sqlite3.connect(str(tmp_path / "requests.db"))
    types = {r[1]: r[2] for r in con.execute("PRAGMA table_info(request_events)")}
    con.close()
    assert types["switch_ms"] == "REAL"
    assert types["queue_wait_ms"] == "REAL"


def test_migration_record_roundtrips_correctly(tmp_path):
    """The regression guard: after migration, a recorded event must land each
    value in its OWN column -- not shifted into ok/error/status_code."""
    _create_old_db(tmp_path)
    store = ObservStore(str(tmp_path))

    ev = RequestEvent(
        adapter="btl3", switched=True, switch_ms=1234.5, queue_wait_ms=42.0,
        ttft_ms=1500.0, prefill_ms=1400.0, prompt_tokens=500,
        completion_tokens=16, ok=True, status_code=200)
    store.record(ev)

    con = sqlite3.connect(str(tmp_path / "requests.db"))
    row = con.execute(
        "SELECT adapter, switch_ms, queue_wait_ms, prompt_tokens, "
        "ok, error, status_code FROM request_events").fetchone()
    con.close()
    assert row is not None, "record() did not persist the event"
    (adapter, switch_ms, queue_wait_ms, prompt_tokens,
     ok, error, status_code) = row
    # correct column mapping (would be wrong under a positional INSERT)
    assert adapter == "btl3"
    assert switch_ms == 1234.5
    assert queue_wait_ms == 42.0
    assert prompt_tokens == 500
    assert ok == 1
    assert error is None
    assert status_code == 200


def test_migration_idempotent(tmp_path):
    _create_old_db(tmp_path)
    store1 = ObservStore(str(tmp_path))
    assert store1.enabled
    cols1 = _cols_of(tmp_path)
    # second open on the same (already migrated) DB: no duplicate columns
    store2 = ObservStore(str(tmp_path))
    assert store2.enabled
    cols2 = _cols_of(tmp_path)
    assert cols1 == cols2
    for c in _MISSING:
        assert cols2.count(c) == 1


def test_fresh_db_needs_no_migration(tmp_path):
    """A brand-new DB is created with every _COLS column already present."""
    store = ObservStore(str(tmp_path))
    assert store.enabled
    cols = _cols_of(tmp_path)
    assert set(_COLS).issubset(set(cols))
    # record + read back works on a fresh DB too
    store.record(RequestEvent(adapter="base", switch_ms=10.0,
                              queue_wait_ms=5.0, prompt_tokens=10))
    con = sqlite3.connect(str(tmp_path / "requests.db"))
    n = con.execute("SELECT count(*) FROM request_events").fetchone()[0]
    sw = con.execute("SELECT switch_ms FROM request_events").fetchone()[0]
    con.close()
    assert n == 1
    assert sw == 10.0
