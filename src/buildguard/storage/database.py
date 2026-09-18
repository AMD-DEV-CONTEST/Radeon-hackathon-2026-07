"""SQLAlchemy engine and transaction management."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from buildguard.storage.models import Base

SCHEMA_VERSION = 3


class Database:
    """Own a SQLite engine and short-lived repository sessions."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(f"sqlite:///{self.path.as_posix()}", future=True)
        event.listen(self.engine, "connect", self._configure_sqlite)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _configure_sqlite(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def _schema_version(self) -> int | None:
        if not self.path.is_file() or self.path.stat().st_size == 0:
            return None
        try:
            with self.engine.connect() as connection:
                if "schema_metadata" not in inspect(connection).get_table_names():
                    return 1
                value = connection.execute(
                    text("SELECT version FROM schema_metadata WHERE id = 1")
                ).scalar_one_or_none()
                return int(value) if value is not None else 1
        except (OSError, TypeError, ValueError, SQLAlchemyError):
            return None

    def initialize(self) -> None:
        previous_version = self._schema_version()
        if previous_version is not None and previous_version < SCHEMA_VERSION:
            backup = self.path.with_suffix(
                self.path.suffix + f".pre-v{SCHEMA_VERSION}.bak"
            )
            if not backup.exists():
                shutil.copy2(self.path, backup)
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_metadata ("
                    "id INTEGER PRIMARY KEY CHECK (id = 1), "
                    "version INTEGER NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO schema_metadata (id, version) "
                    "VALUES (1, :version) "
                    "ON CONFLICT(id) DO UPDATE SET version = excluded.version"
                ),
                {"version": SCHEMA_VERSION},
            )

    def check(self) -> dict[str, object]:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "ok": True,
            "path": str(self.path),
            "schema_version": self._schema_version(),
            "tables": sorted(inspect(self.engine).get_table_names()),
        }

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
