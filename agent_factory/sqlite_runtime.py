from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading


SQLiteInitializer = Callable[[], None]
DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 10000


_INITIALIZATION_LOCK = threading.RLock()
_INITIALIZED_DATABASES: dict[tuple[Path, str, str], tuple[int, int]] = {}
_SQLITE_LIFECYCLE_LOCK = threading.RLock()


class ManagedSQLiteConnection(sqlite3.Connection):
    """SQLite connection whose native close is coordinated process-wide.

    SQLite serializes parts of Unix file-descriptor reuse inside the native
    library.  Concurrent connection creation and destruction across unrelated
    stores can otherwise deadlock before SQLite's busy timeout is involved.
    """

    def close(self) -> None:
        with _SQLITE_LIFECYCLE_LOCK:
            super().close()


def sqlite_lifecycle_available() -> bool:
    """Report whether SQLite connection lifecycle coordination can progress."""

    acquired = _SQLITE_LIFECYCLE_LOCK.acquire(blocking=False)
    if not acquired:
        return False
    _SQLITE_LIFECYCLE_LOCK.release()
    return True


def initialize_sqlite_store(
    path: str | Path,
    initializer: SQLiteInitializer,
    *,
    timeout_ms: int,
    wal: bool,
) -> None:
    resolved = Path(path).expanduser().resolve()
    initialization_key = _initializer_key(resolved, initializer)
    with _INITIALIZATION_LOCK:
        identity = _database_identity(resolved)
        if identity is not None and _INITIALIZED_DATABASES.get(initialization_key) == identity:
            return
        if wal:
            _configure_wal(resolved, timeout_ms=timeout_ms)
        initializer()
        initialized_identity = _database_identity(resolved)
        if initialized_identity is not None:
            _INITIALIZED_DATABASES[initialization_key] = initialized_identity


def connect_sqlite(
    path: str | Path,
    *,
    timeout_ms: int = DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    foreign_keys: bool = False,
    uri: bool = False,
    query_only: bool = False,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    database = str(path) if uri else Path(path)
    with _SQLITE_LIFECYCLE_LOCK:
        conn = sqlite3.connect(
            database,
            timeout=timeout_ms / 1000,
            uri=uri,
            check_same_thread=check_same_thread,
            factory=ManagedSQLiteConnection,
        )
    conn.row_factory = sqlite3.Row
    conn.execute(f"pragma busy_timeout = {timeout_ms}")
    if foreign_keys:
        conn.execute("pragma foreign_keys = on")
    if query_only:
        conn.execute("pragma query_only = on")
    return conn


@contextmanager
def sqlite_session(
    path: str | Path,
    *,
    timeout_ms: int = DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    foreign_keys: bool = False,
    uri: bool = False,
    query_only: bool = False,
) -> Iterator[sqlite3.Connection]:
    conn = connect_sqlite(
        path,
        timeout_ms=timeout_ms,
        foreign_keys=foreign_keys,
        uri=uri,
        query_only=query_only,
    )
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _configure_wal(path: Path, *, timeout_ms: int) -> None:
    conn = connect_sqlite(path, timeout_ms=timeout_ms)
    try:
        mode = str(conn.execute("pragma journal_mode = wal").fetchone()[0]).strip().lower()
        if mode != "wal":
            raise RuntimeError(f"failed to enable SQLite WAL mode for {path}: {mode or 'unknown'}")
        conn.commit()
    finally:
        conn.close()


def _database_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino


def _initializer_key(path: Path, initializer: SQLiteInitializer) -> tuple[Path, str, str]:
    function = getattr(initializer, "__func__", initializer)
    return (
        path,
        str(getattr(function, "__module__", type(function).__module__)),
        str(getattr(function, "__qualname__", type(function).__qualname__)),
    )
