from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from policyseal.storage.tables import Base


def _enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


@dataclass(frozen=True, slots=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    @classmethod
    def from_url(cls, url: str) -> Database:
        options: dict[str, object] = {"future": True}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            options["connect_args"] = {"check_same_thread": False}
            options["poolclass"] = StaticPool
        engine = create_engine(url, **options)
        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        return cls(
            engine=engine,
            session_factory=sessionmaker(engine, expire_on_commit=False, class_=Session),
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
